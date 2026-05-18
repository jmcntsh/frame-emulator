from __future__ import annotations

from dataclasses import asdict, dataclass, field
import base64
import json
import re
import time
from typing import Callable

from .display import FrameDisplay
from .sources import (
    CameraSource,
    MicrophoneSource,
    MotionReading,
    MotionSource,
    StaticMotionSource,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
)


@dataclass
class EventLogEntry:
    timestamp: float
    category: str
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class MessageAccumulator:
    expected_size: int
    payload: bytearray = field(default_factory=bytearray)


@dataclass
class SensorState:
    battery_level: int = 87
    charging: bool = False
    asleep: bool = False
    utc: int = 1_700_000_000
    timezone: str = "0:00"
    imu_direction: dict[str, float] = field(default_factory=lambda: MotionReading().direction())
    imu_raw: dict[str, dict[str, float]] = field(default_factory=lambda: MotionReading().raw())
    camera_resolution: int = 512
    camera_quality: str = "VERY_HIGH"
    camera_image: bytes = b"\xff\xd8\xff\xe0EMULATED_FRAME_PHOTO\xff\xd9"
    microphone_sample_rate: int = 8000
    microphone_bit_depth: int = 8
    microphone_buffer: bytes = b""


@dataclass
class FrameAppRuntime:
    name: str = "frame_app"
    libraries: set[str] = field(default_factory=set)
    started: bool = False

    def register_upload(self, path: str) -> None:
        normalized = path.removesuffix(".lua").removesuffix(".min")
        if normalized in {"data", "plain_text", "sprite", "sprite_coords", "tap", "imu", "camera", "audio", "battery", "code"}:
            self.libraries.add(normalized)

    def capabilities(self) -> set[str]:
        return set(self.libraries)


class FrameEmulator:
    """Virtual Frame device with Frame-like Lua, BLE, and display boundaries."""

    def __init__(
        self,
        mtu_size: int = 247,
        camera_source: CameraSource | None = None,
        microphone_source: MicrophoneSource | None = None,
        motion_source: MotionSource | None = None,
    ) -> None:
        self.mtu_size = mtu_size
        self.display = FrameDisplay()
        self.files: dict[str, str] = {}
        self.file_handles: dict[str, dict[str, str]] = {}
        self.connected = False
        self.running_app: str | None = None
        self.sensors = SensorState()
        self.camera_source: CameraSource = camera_source or SyntheticCameraSource()
        self.microphone_source: MicrophoneSource = microphone_source or SyntheticMicrophoneSource()
        self.motion_source: MotionSource = motion_source or StaticMotionSource()
        self._sync_sources_to_state()
        self.app_runtime = FrameAppRuntime()
        self.message_accumulators: dict[int, MessageAccumulator] = {}
        self.print_handler: Callable[[str], None] | None = None
        self.data_handler: Callable[[bytes], None] | None = None
        self.event_log: list[EventLogEntry] = []
        self.protocol_trace: list[EventLogEntry] = []

    @property
    def max_lua_payload(self) -> int:
        return self.mtu_size - 3

    @property
    def max_data_payload(self) -> int:
        return self.mtu_size - 4

    def connect(self) -> str:
        self._sync_sources_to_state()
        self.connected = True
        self.log("ble", "connect", {"mtu": self.mtu_size})
        return "EM:UL:AT:ED:00:01"

    def disconnect(self) -> None:
        self.connected = False
        self.log("ble", "disconnect")

    def reset(self) -> None:
        self.running_app = None
        self.app_runtime.started = False
        self.file_handles.clear()
        self.message_accumulators.clear()
        self.display.clear_draw_buffer()
        self.log("lua", "reset")

    def break_signal(self) -> None:
        self.running_app = None
        self.app_runtime.started = False
        self.display.text(" ", 1, 1)
        self.display.show()
        self.log("lua", "break")

    def run_lua(self, source: str) -> str | None:
        if len(source.encode()) > self.max_lua_payload:
            raise ValueError("payload length is too large")

        self.log("lua", "eval", {"source": source})
        self.trace("tx-lua", "eval", {"size": len(source.encode()), "source": source})
        output: str | None = None

        if source.startswith("require("):
            app_name = self._first_quoted_string(source) or "frame_app"
            self.running_app = app_name
            self.app_runtime.name = app_name
            self.app_runtime.started = True
            self.display.text("Frame App Started", 1, 1)
            self.display.show()
            output = "Frame app is running"
            self._emit_print(output)
            return output

        self._handle_file_open(source)
        self._handle_file_write(source)
        self._handle_file_close(source)
        self._handle_file_remove(source)
        self._handle_display_calls(source)
        self._handle_palette_calls(source)
        self._handle_sensor_calls(source)

        if "frame.battery_level()" in source and "collectgarbage" in source:
            output = f"{self.sensors.battery_level} / 24.0"
        elif "frame.battery_level()" in source:
            output = str(self.sensors.battery_level)
        elif "frame.bluetooth.max_length()" in source:
            output = str(self.max_data_payload)
        elif "frame.imu.direction()" in source:
            self._sync_motion_source()
            d = self.sensors.imu_direction
            output = f"roll={d['roll']},pitch={d['pitch']},heading={d['heading']}"
        elif "frame.imu.raw()" in source:
            self._sync_motion_source()
            output = json.dumps(self.sensors.imu_raw, separators=(",", ":"))
        elif "frame.time.utc()" in source:
            output = str(self.sensors.utc)
        else:
            output = self._extract_print(source)

        if output is not None:
            self._emit_print(output)
        return output

    def receive_data(self, data: bytes | memoryview) -> bytes:
        packet = bytes(data)
        if len(packet) > self.max_data_payload:
            raise ValueError("payload length is too large")
        self.trace("tx-data", "packet", {"size": len(packet), "msg_code": packet[0] if packet else None})
        if not packet:
            return b"\x01"

        msg_code = packet[0]
        if len(packet) >= 3 and msg_code not in self.message_accumulators:
            expected_size = (packet[1] << 8) | packet[2]
            accumulator = MessageAccumulator(expected_size=expected_size)
            accumulator.payload.extend(packet[3:])
            self.message_accumulators[msg_code] = accumulator
        elif msg_code in self.message_accumulators:
            accumulator = self.message_accumulators[msg_code]
            accumulator.payload.extend(packet[1:])
        else:
            self.log("message", "orphan-packet", {"msg_code": msg_code, "size": len(packet)})
            return b"\x01"

        accumulator = self.message_accumulators[msg_code]
        if len(accumulator.payload) >= accumulator.expected_size:
            payload = bytes(accumulator.payload[: accumulator.expected_size])
            del self.message_accumulators[msg_code]
            self._handle_complete_message(msg_code, payload)

        return b"\x01"

    def inject_tap(self, count: int = 1) -> None:
        payload = bytes([0x10, count & 0xFF])
        self.log("sensor", "tap", {"count": count})
        self._emit_data(payload)

    def set_battery(self, level: int) -> None:
        self.sensors.battery_level = max(1, min(100, int(level)))
        self.log("sensor", "battery", {"level": self.sensors.battery_level})

    def set_imu(self, roll: float = 0.0, pitch: float = 0.0, heading: float = 0.0) -> None:
        self.set_motion_source(StaticMotionSource(MotionReading(roll=roll, pitch=pitch, heading=heading)))
        self.log("sensor", "imu", self.sensors.imu_direction.copy())

    def set_camera_image(self, data: bytes) -> None:
        self.set_camera_source(SyntheticCameraSource(data))
        self.log("sensor", "camera-image", {"size": len(data)})

    def set_microphone_tone(self, seconds: float = 1.0, frequency: float = 440.0) -> None:
        self.set_microphone_source(SyntheticMicrophoneSource(frequency=frequency))
        self.sensors.microphone_buffer = self.microphone_source.read(seconds)
        self.log("sensor", "microphone-tone", {"seconds": seconds, "frequency": frequency})

    def set_camera_source(self, source: CameraSource) -> None:
        self.camera_source = source
        self.sensors.camera_image = source.capture(self.sensors.camera_resolution, self.sensors.camera_quality)
        self.log("source", "camera", {"type": type(source).__name__})

    def set_microphone_source(self, source: MicrophoneSource) -> None:
        self.microphone_source = source
        self.sensors.microphone_sample_rate = source.sample_rate
        self.sensors.microphone_bit_depth = source.bit_depth
        self.sensors.microphone_buffer = source.read(1.0)
        self.log("source", "microphone", {"type": type(source).__name__})

    def set_motion_source(self, source: MotionSource) -> None:
        self.motion_source = source
        self._sync_motion_source()
        self.log("source", "motion", {"type": type(source).__name__})

    def save_snapshot(self, path: str) -> None:
        with open(path, "wb") as handle:
            handle.write(self.display.snapshot_ppm())
        self.log("display", "snapshot", {"path": path})

    def export_event_log(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([asdict(entry) for entry in self.event_log], handle, indent=2)

    def export_protocol_trace(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([asdict(entry) for entry in self.protocol_trace], handle, indent=2)

    def export_session(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "events": [asdict(entry) for entry in self.event_log],
                    "protocol": [asdict(entry) for entry in self.protocol_trace],
                    "sensors": self._jsonable_sensors(),
                    "files": self.files,
                    "display_fingerprint": self.display.fingerprint(),
                },
                handle,
                indent=2,
            )

    def log(self, category: str, message: str, data: dict | None = None) -> None:
        self.event_log.append(EventLogEntry(time.time(), category, message, data or {}))

    def trace(self, category: str, message: str, data: dict | None = None) -> None:
        self.protocol_trace.append(EventLogEntry(time.time(), category, message, data or {}))

    def _sync_sources_to_state(self) -> None:
        self.sensors.camera_image = self.camera_source.capture(self.sensors.camera_resolution, self.sensors.camera_quality)
        self.sensors.microphone_sample_rate = self.microphone_source.sample_rate
        self.sensors.microphone_bit_depth = self.microphone_source.bit_depth
        self.sensors.microphone_buffer = self.microphone_source.read(1.0)
        self._sync_motion_source()

    def _sync_motion_source(self) -> None:
        reading = self.motion_source.read()
        self.sensors.imu_direction = reading.direction()
        self.sensors.imu_raw = reading.raw()

    def _jsonable_sensors(self) -> dict:
        sensors = asdict(self.sensors)
        sensors["camera_image"] = base64.b64encode(self.sensors.camera_image).decode("ascii")
        sensors["microphone_buffer"] = base64.b64encode(self.sensors.microphone_buffer).decode("ascii")
        return sensors

    def _handle_complete_message(self, msg_code: int, payload: bytes) -> None:
        self.log("message", "complete", {"msg_code": msg_code, "size": len(payload)})
        self.trace("rx-message", "complete", {"msg_code": msg_code, "size": len(payload)})
        if msg_code == 0x0A:
            self._draw_plain_text_payload(payload)
        elif msg_code == 0x20:
            self._draw_sprite_payload(payload)
        elif msg_code in (0x0B, 0x0C, 0x0D):
            self._handle_camera_request(msg_code, payload)
        elif msg_code in (0x0E, 0x0F):
            self._handle_audio_request(msg_code, payload)
        elif msg_code == 0x12:
            self._emit_imu()

    def _draw_plain_text_payload(self, payload: bytes) -> None:
        if len(payload) < 6:
            return
        x = int.from_bytes(payload[0:2], "big")
        y = int.from_bytes(payload[2:4], "big")
        color = payload[4] & 0x0F
        spacing = payload[5]
        text = payload[6:].decode("utf-8", errors="replace")

        line_y = y
        for line in text.splitlines() or [text]:
            if line:
                self.display.text(line, x, line_y, color=color, spacing=spacing)
            line_y += 60
        self.display.show()
        self.log("display", "plain-text", {"text": text, "x": x, "y": y})

    def _draw_sprite_payload(self, payload: bytes) -> None:
        if len(payload) < 7:
            return
        width = int.from_bytes(payload[0:2], "big")
        height = int.from_bytes(payload[2:4], "big")
        compressed = payload[4]
        bpp = payload[5]
        num_colors = payload[6]
        palette_size = num_colors * 3
        palette_data = payload[7 : 7 + palette_size]
        pixel_data = payload[7 + palette_size :]
        if compressed:
            self.log("display", "sprite-compressed-unsupported", {"width": width, "height": height})
            return

        for index in range(min(num_colors, 16)):
            base = index * 3
            self.display.assign_color(index, palette_data[base], palette_data[base + 1], palette_data[base + 2])

        self.display.bitmap(1, 1, width, 2**bpp, 0, pixel_data)
        self.display.show()
        self.log("display", "sprite", {"width": width, "height": height, "bpp": bpp})

    def _handle_camera_request(self, msg_code: int, payload: bytes) -> None:
        del payload
        self.sensors.camera_image = self.camera_source.capture(self.sensors.camera_resolution, self.sensors.camera_quality)
        response_code = msg_code
        data = bytes([response_code]) + self.sensors.camera_image
        self.log("sensor", "camera-response", {"msg_code": msg_code, "size": len(data)})
        self._emit_data(data)

    def _handle_audio_request(self, msg_code: int, payload: bytes) -> None:
        del payload
        self.sensors.microphone_buffer = self.microphone_source.read(1.0)
        data = bytes([msg_code]) + self.sensors.microphone_buffer
        self.log("sensor", "audio-response", {"msg_code": msg_code, "size": len(data)})
        self._emit_data(data)

    def _emit_imu(self) -> None:
        self._sync_motion_source()
        d = self.sensors.imu_direction
        payload = json.dumps(d, separators=(",", ":")).encode("utf-8")
        self._emit_data(bytes([0x12]) + payload)

    def _handle_display_calls(self, source: str) -> None:
        for match in re.finditer(r"frame\.display\.text\((.*?)\)", source):
            args = self._split_args(match.group(1))
            if not args:
                continue
            text = self._unquote(args[0])
            x = self._to_int(args[1], 1) if len(args) > 1 else 1
            y = self._to_int(args[2], 1) if len(args) > 2 else 1
            self.display.text(text, x, y)
            self.log("display", "text", {"text": text, "x": x, "y": y})

        if "frame.display.show()" in source:
            self.display.show()
            self.log("display", "show")

        for match in re.finditer(r"frame\.display\.bitmap\((.*?)\)", source):
            args = self._split_args(match.group(1))
            if len(args) >= 6:
                self.display.bitmap(
                    self._to_int(args[0], 1),
                    self._to_int(args[1], 1),
                    self._to_int(args[2], 1),
                    self._to_int(args[3], 2),
                    self._to_int(args[4], 0),
                    self._lua_bytes(args[5]),
                )
                self.log("display", "bitmap-lua", {"width": self._to_int(args[2], 1)})

        for match in re.finditer(r"frame\.display\.draw_rect\((.*?)\)", source):
            args = self._split_args(match.group(1))
            if len(args) >= 5:
                self.display.rect(
                    self._to_int(args[0], 1) - 1,
                    self._to_int(args[1], 1) - 1,
                    self._to_int(args[2], 1),
                    self._to_int(args[3], 1),
                    self._to_int(args[4], 1),
                    filled=True,
                )

    def _handle_palette_calls(self, source: str) -> None:
        for match in re.finditer(r"frame\.display\.assign_color\((.*?)\)", source):
            args = self._split_args(match.group(1))
            if len(args) >= 4:
                self.display.assign_color(self._unquote(args[0]), self._to_int(args[1]), self._to_int(args[2]), self._to_int(args[3]))
                self.log("display", "assign-color", {"color": args[0]})

        for match in re.finditer(r"frame\.display\.assign_color_ycbcr\((.*?)\)", source):
            args = self._split_args(match.group(1))
            if len(args) >= 4:
                self.display.assign_color_ycbcr(
                    self._unquote(args[0]), self._to_int(args[1]), self._to_int(args[2]), self._to_int(args[3])
                )
                self.log("display", "assign-color-ycbcr", {"color": args[0]})

        brightness = re.search(r"frame\.display\.set_brightness\((-?\d+)\)", source)
        if brightness:
            self.display.brightness = self._to_int(brightness.group(1), 0)
            self.log("display", "brightness", {"brightness": self.display.brightness})

    def _handle_sensor_calls(self, source: str) -> None:
        utc_set = re.search(r"frame\.time\.utc\((\d+)\)", source)
        if utc_set:
            self.sensors.utc = self._to_int(utc_set.group(1), self.sensors.utc)
            self.log("sensor", "time-utc", {"utc": self.sensors.utc})

        zone_set = re.search(r"frame\.time\.zone\(['\"]([^'\"]+)['\"]\)", source)
        if zone_set:
            self.sensors.timezone = zone_set.group(1)
            self.log("sensor", "time-zone", {"timezone": self.sensors.timezone})

        if "frame.sleep()" in source or re.search(r"frame\.sleep\((.*?)\)", source):
            self.sensors.asleep = True
            self.log("sensor", "sleep")

        camera_capture = re.search(r"frame\.camera\.capture", source)
        if camera_capture:
            self.log("sensor", "camera-capture", {"size": len(self.sensors.camera_image)})

        mic_start = re.search(r"frame\.microphone\.start", source)
        if mic_start and not self.sensors.microphone_buffer:
            self.set_microphone_tone(seconds=1.0)

        if "frame.microphone.stop()" in source:
            self.log("sensor", "microphone-stop")

    def _handle_file_open(self, source: str) -> None:
        match = re.search(r"(\w+)=frame\.file\.open\(['\"]([^'\"]+)['\"],['\"]([^'\"]+)['\"]\)", source)
        if not match:
            return
        var_name, path, mode = match.groups()
        if mode in ("w", "write"):
            self.files[path] = ""
        elif mode in ("a", "append"):
            self.files.setdefault(path, "")
        self.file_handles[var_name] = {"path": path, "mode": mode}
        self.log("file", "open", {"path": path, "mode": mode})

    def _handle_file_write(self, source: str) -> None:
        match = re.search(r"(\w+):write\(\"(.*)\"\)", source)
        if not match:
            return
        var_name, escaped = match.groups()
        handle = self.file_handles.get(var_name)
        if not handle:
            return
        data = bytes(escaped, "utf-8").decode("unicode_escape")
        path = handle["path"]
        self.files[path] = self.files.get(path, "") + data
        self.log("file", "write", {"path": path, "size": len(data)})

    def _handle_file_close(self, source: str) -> None:
        match = re.search(r"(\w+):close\(\)", source)
        if match:
            self.file_handles.pop(match.group(1), None)
            self.log("file", "close")

    def _handle_file_remove(self, source: str) -> None:
        match = re.search(r"frame\.file\.remove\(['\"]([^'\"]+)['\"]\)", source)
        if match:
            self.files.pop(match.group(1), None)
            self.log("file", "remove", {"path": match.group(1)})

    def _extract_print(self, source: str) -> str | None:
        match = re.search(r"print\((.*?)\)", source)
        if not match:
            return None
        expr = match.group(1).strip()
        if expr == "nil":
            return ""
        if expr in ("0", "1"):
            return expr
        if quoted := self._first_quoted_string(expr):
            return quoted
        if re.fullmatch(r"\d+\s*\+\s*\d+", expr):
            left, right = (int(part.strip()) for part in expr.split("+"))
            return str(left + right)
        return expr

    def _emit_print(self, value: str) -> None:
        self.log("stdout", "print", {"value": value})
        self.trace("rx-print", "print", {"value": value})
        if self.print_handler is not None:
            self.print_handler(value)

    def _emit_data(self, value: bytes) -> None:
        self.log("data", "send", {"size": len(value)})
        self.trace("rx-data", "send", {"size": len(value), "msg_code": value[0] if value else None})
        if self.data_handler is not None:
            self.data_handler(value)

    @staticmethod
    def _first_quoted_string(source: str) -> str | None:
        match = re.search(r"['\"]((?:\\.|[^'\"])*)['\"]", source)
        return bytes(match.group(1), "utf-8").decode("unicode_escape") if match else None

    @staticmethod
    def _unquote(source: str) -> str:
        source = source.strip()
        if len(source) >= 2 and source[0] in "'\"" and source[-1] == source[0]:
            return bytes(source[1:-1], "utf-8").decode("unicode_escape")
        return source

    @classmethod
    def _lua_bytes(cls, source: str) -> bytes:
        return cls._unquote(source).encode("latin1", errors="ignore")

    @staticmethod
    def _split_args(source: str) -> list[str]:
        args: list[str] = []
        current: list[str] = []
        quote: str | None = None
        escaped = False
        for char in source:
            if escaped:
                current.append(char)
                escaped = False
                continue
            if char == "\\":
                current.append(char)
                escaped = True
                continue
            if quote:
                current.append(char)
                if char == quote:
                    quote = None
                continue
            if char in "'\"":
                quote = char
                current.append(char)
                continue
            if char == ",":
                args.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            args.append("".join(current).strip())
        return args

    @staticmethod
    def _to_int(value: str, default: int = 0) -> int:
        try:
            return int(str(value).strip())
        except ValueError:
            return default
