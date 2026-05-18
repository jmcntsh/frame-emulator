from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol


@dataclass(frozen=True)
class MotionReading:
    roll: float = 0.0
    pitch: float = 0.0
    heading: float = 0.0
    accelerometer: tuple[float, float, float] = (0.0, 0.0, 1.0)
    compass: tuple[float, float, float] = (0.0, 1.0, 0.0)

    def direction(self) -> dict[str, float]:
        return {"roll": self.roll, "pitch": self.pitch, "heading": self.heading}

    def raw(self) -> dict[str, dict[str, float]]:
        ax, ay, az = self.accelerometer
        cx, cy, cz = self.compass
        return {
            "accelerometer": {"x": ax, "y": ay, "z": az},
            "compass": {"x": cx, "y": cy, "z": cz},
        }


class CameraSource(Protocol):
    def capture(self, resolution: int = 512, quality: str = "VERY_HIGH") -> bytes:
        """Return JPEG bytes for a Frame camera capture."""


class MicrophoneSource(Protocol):
    sample_rate: int
    bit_depth: int

    def read(self, seconds: float = 1.0) -> bytes:
        """Return PCM-like audio bytes for a Frame microphone read."""


class MotionSource(Protocol):
    def read(self) -> MotionReading:
        """Return the current Frame IMU/motion reading."""


@dataclass
class SyntheticCameraSource:
    image: bytes = b"\xff\xd8\xff\xe0EMULATED_FRAME_PHOTO\xff\xd9"

    def capture(self, resolution: int = 512, quality: str = "VERY_HIGH") -> bytes:
        del resolution, quality
        return self.image


@dataclass
class SyntheticMicrophoneSource:
    sample_rate: int = 8000
    bit_depth: int = 8
    frequency: float = 440.0

    def read(self, seconds: float = 1.0) -> bytes:
        count = max(0, int(seconds * self.sample_rate))
        samples = bytearray()
        for index in range(count):
            sample = int(127 + 64 * math.sin((2 * math.pi * self.frequency * index) / self.sample_rate))
            samples.append(sample & 0xFF)
        return bytes(samples)


@dataclass
class StaticMotionSource:
    reading: MotionReading = MotionReading()

    def read(self) -> MotionReading:
        return self.reading
