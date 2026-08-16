import asyncio

from voice.live import run_live_voice


if __name__ == "__main__":
    asyncio.run(
        run_live_voice()
    )