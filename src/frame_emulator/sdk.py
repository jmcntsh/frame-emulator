from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import struct
from typing import Callable, Final

from .core import FrameEmulator


class FrameBleEmulator:
    """`frame-ble`-shaped adapter backed by a local `FrameEmulator`."""

    def __init__(self, emulator: FrameEmulator | None = None) -> None:
        self.emulator = emulator or FrameEmulator()
        self._user_data_response_handler: Callable[[bytes], None] | None = None
        self._user_disconnect_handler: Callable[[], None] | None = None
        self._user_print_response_handler: Callable[[str], None] | None = None
        self.address = "EM:UL:AT:ED:00:01"

    async def connect(
        self,
        name: str | None = None,
        timeout: int = 10,
        print_response_handler: Callable[[str], None] | None = lambda _: None,
        data_response_handler: Callable[[bytes], None] | None = lambda _: None,
        disconnect_handler: Callable[[], None] | None = lambda: None,
    ) -> str:
        del name, timeout
        self._user_print_response_handler = print_response_handler
        self._user_data_response_handler = data_response_handler
        self._user_disconnect_handler = disconnect_handler
        self.emulator.print_handler = self._handle_print_response
        self.emulator.data_handler = self._handle_data_response
        self.address = self.emulator.connect()
        return self.address

    async def disconnect(self) -> None:
        self.emulator.disconnect()
        if self._user_disconnect_handler:
            self._user_disconnect_handler()

    def is_connected(self) -> bool:
        return self.emulator.connected

    def max_lua_payload(self) -> int:
        return self.emulator.max_lua_payload

    def max_data_payload(self) -> int:
        return self.emulator.max_data_payload

    async def send_lua(self, string: str, show_me: bool = False, await_print: bool = False) -> str | None:
        if show_me:
            print(string)
        response = self.emulator.run_lua(string)
        if await_print:
            return response or ""
        return None

    async def send_data(self, data: bytes | bytearray | memoryview, show_me: bool = False, await_data: bool = False) -> bytes | None:
        packet = bytes(data)
        if show_me:
            print(packet)
        response = self.emulator.receive_data(packet)
        if await_data:
            return response
        return None

    async def send_reset_signal(self, show_me: bool = False) -> None:
        if show_me:
            print(b"\x04")
        self.emulator.reset()
        await asyncio.sleep(0)

    async def send_break_signal(self, show_me: bool = False) -> None:
        if show_me:
            print(b"\x03")
        self.emulator.break_signal()
        await asyncio.sleep(0)

    async def upload_file_from_string(self, content: str, frame_file_path: str = "main.lua") -> None:
        self.emulator.files[frame_file_path] = content.replace("\r", "")
        self.emulator.app_runtime.register_upload(frame_file_path)
        self.emulator.log("file", "upload-string", {"path": frame_file_path, "size": len(content)})
        await asyncio.sleep(0)

    async def upload_file(self, local_file_path: str, frame_file_path: str = "main.lua") -> None:
        if not os.path.exists(local_file_path):
            raise FileNotFoundError(f"Local file not found: {local_file_path}")
        with open(local_file_path, "r", encoding="utf-8") as handle:
            await self.upload_file_from_string(handle.read(), frame_file_path)

    async def send_message(self, msg_code: int, payload: bytes, show_me: bool = False) -> None:
        header_size: Final = 3
        subsequent_header_size: Final = 1
        max_total_size: Final = 65535

        if not 0 <= msg_code <= 255:
            raise ValueError(f"Message code must be 0-255, got {msg_code}")
        if len(payload) > max_total_size:
            raise ValueError(f"Payload size {len(payload)} exceeds maximum {max_total_size} bytes")
        self.emulator.trace("tx-message", "start", {"msg_code": msg_code, "size": len(payload)})

        max_first_chunk = self.max_data_payload() - header_size
        max_chunk_size = self.max_data_payload() - subsequent_header_size

        first_chunk_size = min(max_first_chunk, len(payload))
        first = bytearray([msg_code, len(payload) >> 8, len(payload) & 0xFF])
        first.extend(payload[:first_chunk_size])
        await self.send_data(first, show_me=show_me, await_data=True)

        sent = first_chunk_size
        while sent < len(payload):
            chunk_size = min(max_chunk_size, len(payload) - sent)
            chunk = bytearray([msg_code])
            chunk.extend(payload[sent : sent + chunk_size])
            await self.send_data(chunk, show_me=show_me, await_data=True)
            sent += chunk_size
        self.emulator.trace("tx-message", "end", {"msg_code": msg_code, "size": len(payload)})

    def inject_tap(self, count: int = 1) -> None:
        self.emulator.inject_tap(count)

    def set_battery(self, level: int) -> None:
        self.emulator.set_battery(level)

    def set_imu(self, roll: float = 0.0, pitch: float = 0.0, heading: float = 0.0) -> None:
        self.emulator.set_imu(roll, pitch, heading)

    def set_camera_image(self, data: bytes) -> None:
        self.emulator.set_camera_image(data)

    def set_microphone_tone(self, seconds: float = 1.0, frequency: float = 440.0) -> None:
        self.emulator.set_microphone_tone(seconds, frequency)

    def _handle_print_response(self, value: str) -> None:
        handler = self._user_print_response_handler
        if handler:
            result = handler(value)
            self._dispatch_handler_result(result)

    def _handle_data_response(self, value: bytes) -> None:
        handler = self._user_data_response_handler
        if handler:
            result = handler(value)
            self._dispatch_handler_result(result)

    @staticmethod
    def _dispatch_handler_result(result) -> None:
        if not asyncio.iscoroutine(result):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(result)
        else:
            loop.create_task(result)


class FrameMsgEmulator:
    """`frame-msg`-shaped adapter for app-level emulator testing."""

    def __init__(self, emulator: FrameEmulator | None = None) -> None:
        self.ble = FrameBleEmulator(emulator)
        self.data_response_handlers: dict[int, list[tuple[object, Callable[[bytes], None]]]] = {}

    @property
    def emulator(self) -> FrameEmulator:
        return self.ble.emulator

    async def connect(self, initialize: bool = True) -> bool:
        await self.ble.connect(data_response_handler=self._handle_data_response)
        if initialize:
            await self.ble.send_break_signal()
            await self.ble.send_reset_signal()
            await self.ble.send_break_signal()
        return True

    async def disconnect(self) -> None:
        if self.ble.is_connected():
            await self.ble.disconnect()

    def is_connected(self) -> bool:
        return self.ble.is_connected()

    async def print_short_text(self, text: str = "") -> None:
        sanitized = text.replace("'", "\\'").replace("\n", "")
        await self.ble.send_lua(f"frame.display.text('{sanitized}',1,1);frame.display.show();print(0)", await_print=True)

    async def upload_stdlua_libs(self, lib_names: list[str] | None = None, minified: bool = True) -> None:
        suffix = ".min" if minified else ""
        for lib_name in lib_names or ["data"]:
            await self.ble.upload_file_from_string(f"-- emulated {lib_name}{suffix}.lua", f"{lib_name}{suffix}.lua")

    async def upload_frame_app(
        self,
        local_filename: str | None = None,
        frame_filename: str = "frame_app.lua",
        contents: str | None = None,
    ) -> None:
        if contents is not None:
            await self.ble.upload_file_from_string(contents, frame_filename)
        elif local_filename is not None:
            await self.ble.upload_file(local_filename, frame_filename)
        else:
            await self.ble.upload_file_from_string("-- emulated frame app", frame_filename)

    async def start_frame_app(self, frame_app_name: str = "frame_app", await_print: bool = True) -> str | None:
        return await self.ble.send_lua(f"require('{frame_app_name}')", await_print=await_print)

    async def stop_frame_app(self, reset: bool = True) -> None:
        await self.ble.send_break_signal()
        if reset:
            await self.ble.send_reset_signal()

    def attach_print_response_handler(self, handler: Callable[[str], None] = print) -> None:
        self.ble._user_print_response_handler = handler

    def detach_print_response_handler(self) -> None:
        self.ble._user_print_response_handler = None

    async def send_message(self, msg_code: int, payload: bytes, show_me: bool = False) -> None:
        await self.ble.send_message(msg_code, payload, show_me)

    def register_data_response_handler(self, subscriber: object, msg_codes: list[int], handler: Callable[[bytes], None]) -> None:
        for code in msg_codes:
            self.data_response_handlers.setdefault(code, []).append((subscriber, handler))

    def unregister_data_response_handler(self, subscriber: object) -> None:
        for code in list(self.data_response_handlers.keys()):
            self.data_response_handlers[code] = [
                (sub, handler) for sub, handler in self.data_response_handlers[code] if sub != subscriber
            ]
            if not self.data_response_handlers[code]:
                del self.data_response_handlers[code]

    def save_snapshot(self, path: str) -> None:
        self.emulator.save_snapshot(path)

    @property
    def app_capabilities(self) -> set[str]:
        return self.emulator.app_runtime.capabilities()

    def inject_tap(self, count: int = 1) -> None:
        self.emulator.inject_tap(count)

    def set_battery(self, level: int) -> None:
        self.emulator.set_battery(level)

    def set_imu(self, roll: float = 0.0, pitch: float = 0.0, heading: float = 0.0) -> None:
        self.emulator.set_imu(roll, pitch, heading)

    def set_camera_image(self, data: bytes) -> None:
        self.emulator.set_camera_image(data)

    def set_microphone_tone(self, seconds: float = 1.0, frequency: float = 440.0) -> None:
        self.emulator.set_microphone_tone(seconds, frequency)

    def export_event_log(self, path: str) -> None:
        self.emulator.export_event_log(path)

    def export_protocol_trace(self, path: str) -> None:
        self.emulator.export_protocol_trace(path)

    def export_session(self, path: str) -> None:
        self.emulator.export_session(path)

    async def _handle_data_response(self, data: bytes) -> None:
        if data:
            msg_code = data[0]
            for _, handler in self.data_response_handlers.get(msg_code, []):
                handler(data)

    def __getattr__(self, name: str):
        return getattr(self.ble, name)


@dataclass
class TxPlainText:
    text: str
    x: int = 1
    y: int = 1
    palette_offset: int = 1
    spacing: int = 4

    def pack(self) -> bytes:
        return struct.pack(">HHBB", self.x, self.y, self.palette_offset & 0x0F, self.spacing & 0xFF) + self.text.encode("utf-8")


@dataclass
class TxSprite:
    width: int
    height: int
    num_colors: int
    palette_data: bytes
    pixel_data: bytes
    compress: bool = False

    @property
    def bpp(self) -> int:
        if self.num_colors <= 2:
            return 1
        if self.num_colors <= 4:
            return 2
        if self.num_colors <= 16:
            return 4
        raise ValueError("num_colors must be 16 or fewer")

    def pack(self) -> bytes:
        packed_pixels = self._pack_pixels()
        header = struct.pack(">HHBBB", self.width, self.height, int(self.compress), self.bpp, self.num_colors)
        return header + self.palette_data + packed_pixels

    def _pack_pixels(self) -> bytes:
        if self.bpp == 1:
            return self._pack_n_bits(1, 8)
        if self.bpp == 2:
            return self._pack_n_bits(2, 4)
        return self._pack_n_bits(4, 2)

    def _pack_n_bits(self, bits: int, pixels_per_byte: int) -> bytes:
        output = bytearray()
        mask = (1 << bits) - 1
        for offset in range(0, len(self.pixel_data), pixels_per_byte):
            byte = 0
            chunk = self.pixel_data[offset : offset + pixels_per_byte]
            for index, pixel in enumerate(chunk):
                shift = (pixels_per_byte - 1 - index) * bits
                byte |= (pixel & mask) << shift
            output.append(byte)
        return bytes(output)
