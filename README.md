# Frame Emulator

Desktop and headless emulator for Brilliant Labs Frame apps.

## Compatibility Target

The MVP targets the current Brilliant Labs SDK model documented at
`docs.brilliant.xyz/frame/frame-sdk/`:

- Python `frame-ble` 1.1.1
- Python `frame-msg` 5.2.1
- The Bluetooth/Lua/message behavior used by `frame_examples_python`

The goal is API-accurate emulation at the developer boundary: app code should
be able to target an emulated Frame instead of physical hardware.

## Current Capabilities

- Headless virtual Frame state.
- 640x400 display model with draw buffer and visible buffer.
- Lua command handling for display, palette, battery, IMU, time, files,
  `require`, break, reset, and app-start acknowledgements.
- Message handling for plain text, sprites, camera/photo, audio, IMU, and tap
  flows used by current examples.
- Python-compatible `FrameBleEmulator` and `FrameMsgEmulator` classes.
- Event logs, protocol traces, session export, snapshots, and display
  fingerprints for SDK debugging.
- Native macOS desktop lens with scale, opacity, border, window-level, and
  click-through controls.
- Source interfaces for future hardware/environment integration:
  `CameraSource`, `MicrophoneSource`, and `MotionSource`. Defaults remain
  synthetic/static, so no real screen capture or system mic access is enabled
  yet.

## Example

```python
import asyncio

from frame_emulator import FrameMsgEmulator, TxPlainText

async def main():
    frame = FrameMsgEmulator()
    await frame.connect()
    await frame.print_short_text("Loading...")
    await frame.upload_stdlua_libs(["data", "plain_text"])
    await frame.upload_frame_app(contents="-- plain text app")
    await frame.start_frame_app()
    await frame.send_message(0x0A, TxPlainText("hello\nFrame").pack())
    frame.save_snapshot("frame.ppm")
    await frame.disconnect()

asyncio.run(main())
```

Run the demo:

```sh
PYTHONPATH=src python3 -m frame_emulator.cli demo --snapshot frame.ppm --trace trace.json --session session.json
```

Run the desktop lens:

```sh
PYTHONPATH=src python3 -m frame_emulator.cli lens --scale 1 --opacity 1 --border --level floating
```

The native macOS lens opens a hardware dev panel by default. It includes only
Frame-level controls: tap, double tap, head pose changes, still/shake motion,
sleep/wake, Lua break/reset, and simulated disconnect/reconnect. It does not
include app-specific actions such as taking a photo.

Run the lens in click-through mode:

```sh
PYTHONPATH=src python3 -m frame_emulator.cli lens --click-through --no-border --opacity 0.85 --level screensaver
```

Hide the hardware panel:

```sh
PYTHONPATH=src python3 -m frame_emulator.cli lens --no-panel
```

Run validation:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
```
