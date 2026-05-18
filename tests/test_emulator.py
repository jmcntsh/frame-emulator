import asyncio
import json
import tempfile
from pathlib import Path
import unittest

from frame_emulator import (
    FrameBleEmulator,
    FrameEmulator,
    FrameMsgEmulator,
    MotionReading,
    StaticMotionSource,
    TxPlainText,
    TxSprite,
)
from frame_emulator.cli import apply_dev_panel_command, process_dev_panel_commands


class FakeCameraSource:
    def __init__(self):
        self.calls = 0

    def capture(self, resolution=512, quality="VERY_HIGH"):
        self.calls += 1
        return f"JPEG:{resolution}:{quality}:{self.calls}".encode()


class FakeMicrophoneSource:
    sample_rate = 16000
    bit_depth = 8

    def read(self, seconds=1.0):
        return b"MIC" + str(seconds).encode()


class EmulatorTests(unittest.TestCase):
    def test_frame_ble_hello_world_updates_visible_buffer(self):
        asyncio.run(self._frame_ble_hello_world_updates_visible_buffer())

    async def _frame_ble_hello_world_updates_visible_buffer(self):
        frame = FrameBleEmulator()
        await frame.connect()

        response = await frame.send_lua(
            "frame.display.text('Hello, Frame!', 1, 1);frame.display.show();print(0)",
            await_print=True,
        )

        self.assertEqual(response, "0")
        self.assertNotEqual(frame.emulator.display.visible_buffer, frame.emulator.display._blank_buffer())

    def test_frame_msg_plain_text_flow_uses_current_message_protocol(self):
        asyncio.run(self._frame_msg_plain_text_flow_uses_current_message_protocol())

    async def _frame_msg_plain_text_flow_uses_current_message_protocol(self):
        frame = FrameMsgEmulator()
        await frame.connect()
        await frame.upload_stdlua_libs(["data", "plain_text"])
        await frame.upload_frame_app(contents="-- plain text test app")

        response = await frame.start_frame_app()
        await frame.send_message(0x0A, TxPlainText("red\norange", palette_offset=3).pack())

        self.assertEqual(response, "Frame app is running")
        self.assertTrue(any(entry.category == "message" and entry.message == "complete" for entry in frame.emulator.event_log))
        self.assertTrue(any(entry.category == "display" and entry.message == "plain-text" for entry in frame.emulator.event_log))

    def test_sprite_message_renders_snapshot_bytes(self):
        asyncio.run(self._sprite_message_renders_snapshot_bytes())

    async def _sprite_message_renders_snapshot_bytes(self):
        frame = FrameMsgEmulator()
        await frame.connect()
        palette = bytes([0, 0, 0, 255, 255, 255])
        pixels = bytes([0, 1, 1, 0] * 16)

        await frame.send_message(0x20, TxSprite(8, 8, 2, palette, pixels).pack())

        snapshot = frame.emulator.display.snapshot_ppm()
        self.assertTrue(snapshot.startswith(b"P6\n640 400\n255\n"))
        self.assertTrue(any(entry.category == "display" and entry.message == "sprite" for entry in frame.emulator.event_log))

    def test_tap_injection_reaches_registered_data_handler(self):
        asyncio.run(self._tap_injection_reaches_registered_data_handler())

    async def _tap_injection_reaches_registered_data_handler(self):
        received = []
        frame = FrameMsgEmulator()
        await frame.connect()
        frame.register_data_response_handler(object(), [0x10], lambda data: received.append(data))

        frame.emulator.inject_tap(2)
        await asyncio.sleep(0)

        self.assertEqual(received, [bytes([0x10, 2])])

    def test_display_fingerprint_and_bounds_are_deterministic(self):
        emulator = FrameEmulator()
        emulator.display.text("FRAME", 1, 1, color="GREEN")
        emulator.display.show()

        self.assertEqual(len(emulator.display.fingerprint()), 64)
        self.assertEqual(emulator.display.non_void_bounds(), (0, 0, 90, 20))

    def test_brightness_changes_snapshot_without_mutating_state(self):
        emulator = FrameEmulator()
        emulator.display.text("A", 1, 1, color="WHITE")
        emulator.display.show()

        normal = emulator.display.snapshot_ppm(brightness=0)
        dim = emulator.display.snapshot_ppm(brightness=-2)

        self.assertNotEqual(normal, dim)
        self.assertEqual(emulator.display.brightness, 0)

    def test_protocol_trace_and_session_export(self):
        asyncio.run(self._protocol_trace_and_session_export())

    async def _protocol_trace_and_session_export(self):
        frame = FrameMsgEmulator()
        await frame.connect()
        await frame.upload_stdlua_libs(["data", "plain_text", "sprite"])
        await frame.start_frame_app()
        await frame.send_message(0x0A, TxPlainText("trace").pack())

        with tempfile.TemporaryDirectory() as temp_dir:
            trace_path = Path(temp_dir) / "trace.json"
            session_path = Path(temp_dir) / "session.json"
            frame.export_protocol_trace(str(trace_path))
            frame.export_session(str(session_path))

            trace = json.loads(trace_path.read_text())
            session = json.loads(session_path.read_text())

        self.assertTrue(any(entry["category"] == "tx-message" for entry in trace))
        self.assertEqual(session["display_fingerprint"], frame.emulator.display.fingerprint())
        self.assertIn("plain_text", frame.app_capabilities)

    def test_sensor_hooks_emit_camera_audio_and_imu(self):
        asyncio.run(self._sensor_hooks_emit_camera_audio_and_imu())

    async def _sensor_hooks_emit_camera_audio_and_imu(self):
        received = []
        frame = FrameMsgEmulator()
        await frame.connect()
        frame.register_data_response_handler("camera", [0x0D], lambda data: received.append(data))
        frame.register_data_response_handler("imu", [0x12], lambda data: received.append(data))
        frame.set_camera_image(b"\xff\xd8test\xff\xd9")
        frame.set_imu(roll=1.0, pitch=2.0, heading=3.0)

        await frame.send_message(0x0D, b"")
        await frame.send_message(0x12, b"")
        await asyncio.sleep(0)

        self.assertTrue(any(data.startswith(bytes([0x0D, 0xFF, 0xD8])) for data in received))
        self.assertTrue(any(data.startswith(bytes([0x12])) and b"heading" in data for data in received))

    def test_source_abstractions_can_be_injected_without_real_capture(self):
        asyncio.run(self._source_abstractions_can_be_injected_without_real_capture())

    async def _source_abstractions_can_be_injected_without_real_capture(self):
        received = []
        camera = FakeCameraSource()
        mic = FakeMicrophoneSource()
        motion = StaticMotionSource(MotionReading(roll=4.0, pitch=5.0, heading=6.0))
        emulator = FrameEmulator(camera_source=camera, microphone_source=mic, motion_source=motion)
        frame = FrameMsgEmulator(emulator)
        await frame.connect()
        frame.register_data_response_handler("camera", [0x0D], lambda data: received.append(data))
        frame.register_data_response_handler("audio", [0x0E], lambda data: received.append(data))
        frame.register_data_response_handler("imu", [0x12], lambda data: received.append(data))

        await frame.send_message(0x0D, b"")
        await frame.send_message(0x0E, b"")
        await frame.send_message(0x12, b"")
        await asyncio.sleep(0)

        self.assertGreaterEqual(camera.calls, 2)
        self.assertTrue(any(data.startswith(b"\x0dJPEG:512:VERY_HIGH") for data in received))
        self.assertTrue(any(data.startswith(b"\x0eMIC") for data in received))
        self.assertTrue(any(data.startswith(b"\x12") and b'"roll":4.0' in data for data in received))

    def test_dev_panel_commands_drive_hardware_state(self):
        received = []
        emulator = FrameEmulator()
        emulator.data_handler = lambda data: received.append(data)

        apply_dev_panel_command(emulator, "tap")
        apply_dev_panel_command(emulator, "double_tap")
        apply_dev_panel_command(emulator, "pitch_up")
        apply_dev_panel_command(emulator, "roll_left")
        apply_dev_panel_command(emulator, "heading_right")
        apply_dev_panel_command(emulator, "sleep")
        apply_dev_panel_command(emulator, "wake")

        self.assertEqual(received[:2], [b"\x10\x01", b"\x10\x02"])
        self.assertEqual(emulator.sensors.imu_direction["pitch"], 10.0)
        self.assertEqual(emulator.sensors.imu_direction["roll"], -10.0)
        self.assertEqual(emulator.sensors.imu_direction["heading"], 10.0)
        self.assertFalse(emulator.sensors.asleep)

    def test_dev_panel_tap_after_async_setup_has_no_running_loop(self):
        received = []
        frame = FrameMsgEmulator()

        async def setup():
            await frame.connect()
            frame.register_data_response_handler("tap", [0x10], lambda data: received.append(data))

        asyncio.run(setup())

        apply_dev_panel_command(frame.emulator, "tap")

        self.assertEqual(received, [b"\x10\x01"])

    def test_dev_panel_command_file_is_incrementally_processed(self):
        emulator = FrameEmulator()
        with tempfile.TemporaryDirectory() as temp_dir:
            command_path = Path(temp_dir) / "commands.txt"
            command_path.write_text("pitch_down\nreset_pose\n", encoding="utf-8")
            offset = process_dev_panel_commands(emulator, command_path, 0)
            command_path.write_text(command_path.read_text(encoding="utf-8") + "heading_left\n", encoding="utf-8")
            process_dev_panel_commands(emulator, command_path, offset)

        self.assertEqual(emulator.sensors.imu_direction, {"roll": 0.0, "pitch": 0.0, "heading": 350.0})


if __name__ == "__main__":
    unittest.main()
