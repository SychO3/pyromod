import asyncio


def ensure_default_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError as exc:
        if "There is no current event loop" not in str(exc):
            raise

        asyncio.set_event_loop(asyncio.new_event_loop())
