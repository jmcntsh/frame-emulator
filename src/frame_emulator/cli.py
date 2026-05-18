from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .core import FrameEmulator
from .sdk import FrameMsgEmulator, TxPlainText, TxSprite
from .sources import MotionReading, StaticMotionSource


async def run_demo(snapshot: str | None = None) -> FrameEmulator:
    frame = FrameMsgEmulator()
    await frame.connect()
    await frame.print_short_text("Loading...")
    await frame.upload_stdlua_libs(["data", "plain_text", "sprite"])
    await frame.upload_frame_app(contents="-- emulator demo app")
    await frame.start_frame_app()
    palette = bytes(
        [
            0, 0, 0,
            255, 255, 255,
            255, 0, 0,
            0, 180, 255,
        ]
    )
    pixels = bytes((x // 20 + y // 20) % 4 for y in range(80) for x in range(160))
    await frame.send_message(0x20, TxSprite(160, 80, 4, palette, pixels).pack())
    await frame.send_message(0x0A, TxPlainText("Frame emulator\nnative lens", x=24, y=24, palette_offset=10).pack())

    if snapshot:
        frame.save_snapshot(snapshot)
    return frame.emulator


def main() -> None:
    parser = argparse.ArgumentParser(description="Brilliant Labs Frame emulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="run a headless SDK demo")
    demo.add_argument("--snapshot", help="write the visible display to a PPM image")
    demo.add_argument("--json-log", action="store_true", help="print event log as JSON")
    demo.add_argument("--event-log", help="write event log JSON")
    demo.add_argument("--trace", help="write protocol trace JSON")
    demo.add_argument("--session", help="write complete emulator session JSON")

    lens = subparsers.add_parser("lens", help="run the desktop lens overlay")
    lens.add_argument("--scale", type=int, default=1, help="integer display scale")
    lens.add_argument("--opacity", type=float, default=1.0, help="window opacity from 0.1 to 1.0")
    lens.add_argument("--border", action=argparse.BooleanOptionalAction, default=True, help="show lens border")
    lens.add_argument("--click-through", action="store_true", help="allow clicks to pass through the lens")
    lens.add_argument("--level", choices=["normal", "floating", "screensaver"], default="floating", help="macOS window level")
    lens.add_argument("--panel", action=argparse.BooleanOptionalAction, default=True, help="show hardware dev panel")
    lens.add_argument("--duration", type=float, help="optional runtime in seconds, useful for smoke tests")
    lens.add_argument(
        "--backend",
        choices=["native", "tk", "auto"],
        default="native" if sys.platform == "darwin" else "auto",
        help="overlay backend; macOS defaults to native",
    )

    args = parser.parse_args()

    if args.command == "demo":
        emulator = asyncio.run(run_demo(args.snapshot))
        if args.json_log:
            print(json.dumps([entry.__dict__ for entry in emulator.event_log], indent=2))
        if args.event_log:
            emulator.export_event_log(args.event_log)
        if args.trace:
            emulator.export_protocol_trace(args.trace)
        if args.session:
            emulator.export_session(args.session)
        return

    if args.command == "lens":
        emulator = asyncio.run(run_demo())
        if args.backend == "native":
            run_native_macos_lens(
                emulator,
                scale=args.scale,
                duration=args.duration,
                opacity=args.opacity,
                border=args.border,
                click_through=args.click_through,
                level=args.level,
                panel=args.panel,
            )
            return

        try:
            from .overlay import FrameLensOverlay

            FrameLensOverlay(emulator, scale=args.scale).run()
        except Exception as exc:
            if args.backend == "tk":
                raise
            print(f"Tk lens unavailable, falling back to native macOS lens: {exc}")
            run_native_macos_lens(
                emulator,
                scale=args.scale,
                duration=args.duration,
                opacity=args.opacity,
                border=args.border,
                click_through=args.click_through,
                level=args.level,
                panel=args.panel,
            )


def run_native_macos_lens(
    emulator: FrameEmulator,
    scale: int = 1,
    duration: float | None = None,
    opacity: float = 1.0,
    border: bool = True,
    click_through: bool = False,
    level: str = "floating",
    panel: bool = True,
) -> None:
    """Launch the Swift/AppKit lens used when Tk is unavailable on macOS."""
    tool_path = Path(__file__).resolve().parents[2] / "tools" / "FrameLensOverlay.swift"
    if not tool_path.exists():
        raise RuntimeError(f"Native lens tool is missing: {tool_path}")

    with tempfile.TemporaryDirectory(prefix="frame-emulator-") as temp_dir:
        snapshot_path = Path(temp_dir) / "frame.ppm"
        command_path = Path(temp_dir) / "commands.txt"
        command_path.touch()
        save_snapshot_atomic(emulator, snapshot_path)
        command = [
            "swift",
            str(tool_path),
            str(snapshot_path),
            str(command_path),
            str(max(1, scale)),
            str(duration if duration is not None else 0),
            str(max(0.1, min(1.0, opacity))),
            "1" if border else "0",
            "1" if click_through else "0",
            level,
            "1" if panel else "0",
        ]

        print("Launching native Frame lens. Close the window or press Ctrl-C in this terminal to stop it.")
        process = subprocess.Popen(command)
        start = time.monotonic()
        command_offset = 0
        try:
            while process.poll() is None:
                command_offset = process_dev_panel_commands(emulator, command_path, command_offset)
                save_snapshot_atomic(emulator, snapshot_path)
                if duration is not None and time.monotonic() - start >= duration + 0.5:
                    break
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()


def save_snapshot_atomic(emulator: FrameEmulator, path: Path) -> None:
    tmp_path = path.with_suffix(".tmp.ppm")
    emulator.save_snapshot(str(tmp_path))
    tmp_path.replace(path)


def process_dev_panel_commands(emulator: FrameEmulator, path: Path, offset: int) -> int:
    if not path.exists():
        return offset

    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        commands = [line.strip() for line in handle if line.strip()]
        new_offset = handle.tell()

    for command in commands:
        apply_dev_panel_command(emulator, command)

    return new_offset


def apply_dev_panel_command(emulator: FrameEmulator, command: str) -> None:
    direction = emulator.sensors.imu_direction
    roll = direction["roll"]
    pitch = direction["pitch"]
    heading = direction["heading"]
    step = 10.0

    if command == "tap":
        emulator.inject_tap(1)
    elif command == "double_tap":
        emulator.inject_tap(2)
    elif command == "sleep":
        emulator.sensors.asleep = True
        emulator.log("panel", "sleep")
    elif command == "wake":
        emulator.sensors.asleep = False
        emulator.log("panel", "wake")
    elif command == "break_lua":
        emulator.break_signal()
    elif command == "reset_lua":
        emulator.reset()
    elif command == "disconnect":
        emulator.disconnect()
    elif command == "reconnect":
        emulator.connect()
    elif command == "pitch_up":
        emulator.set_imu(roll=roll, pitch=pitch + step, heading=heading)
    elif command == "pitch_down":
        emulator.set_imu(roll=roll, pitch=pitch - step, heading=heading)
    elif command == "roll_left":
        emulator.set_imu(roll=roll - step, pitch=pitch, heading=heading)
    elif command == "roll_right":
        emulator.set_imu(roll=roll + step, pitch=pitch, heading=heading)
    elif command == "heading_left":
        emulator.set_imu(roll=roll, pitch=pitch, heading=(heading - step) % 360)
    elif command == "heading_right":
        emulator.set_imu(roll=roll, pitch=pitch, heading=(heading + step) % 360)
    elif command == "reset_pose":
        emulator.set_imu()
    elif command == "shake":
        emulator.set_motion_source(
            StaticMotionSource(
                MotionReading(
                    roll=roll,
                    pitch=pitch,
                    heading=heading,
                    accelerometer=(2.0, -2.0, 0.2),
                    compass=(0.0, 1.0, 0.0),
                )
            )
        )
        emulator.log("panel", "shake")
    elif command == "still":
        emulator.set_motion_source(StaticMotionSource(MotionReading(roll=roll, pitch=pitch, heading=heading)))
        emulator.log("panel", "still")
    else:
        emulator.log("panel", "unknown-command", {"command": command})


if __name__ == "__main__":
    main()
