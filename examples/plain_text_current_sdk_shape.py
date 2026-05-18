import asyncio

from frame_emulator.compat import FrameMsg, TxPlainText


async def main():
    """Current `frame-msg` plain-text example shape, targeting the emulator."""
    frame = FrameMsg()
    try:
        await frame.connect()

        batt_mem = await frame.send_lua(
            'print(frame.battery_level() .. " / " .. collectgarbage("count"))',
            await_print=True,
        )
        print(f"Battery Level/Memory used: {batt_mem}")

        await frame.print_short_text("Loading...")
        await frame.upload_stdlua_libs(lib_names=["data", "plain_text"])
        await frame.upload_frame_app(contents="-- plain text frame app")
        frame.attach_print_response_handler()
        await frame.start_frame_app()

        for display_string in ["red", "orange", "yellow", "red\norange\nyellow", " "]:
            await frame.send_message(0x0A, TxPlainText(display_string).pack())
            await asyncio.sleep(0.01)

        frame.save_snapshot("plain_text_current_sdk_shape.ppm")
        frame.detach_print_response_handler()
        await frame.stop_frame_app()

    finally:
        await frame.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
