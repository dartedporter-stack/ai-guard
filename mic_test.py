import asyncio
import os
import queue
import sys

import sounddevice as sd

from google import genai
from google.genai import types


MODEL = "gemini-3.1-flash-live-preview"

SAMPLE_RATE = 16000
CHANNELS = 1

# Размер одного блока микрофона.
# 1600 samples при 16 kHz = 100 ms.
BLOCKSIZE = 1600


async def main():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не найден")

    client = genai.Client(api_key=api_key)

    audio_queue = queue.Queue()

    def audio_callback(indata, frames, time, status):
        if status:
            print("🎙️ Audio status:", status, file=sys.stderr)

        # Копируем bytes, потому что indata переиспользуется sounddevice.
        audio_queue.put(bytes(indata))

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
    }

    print("🛡️ GUARD Mic Test")
    print("Подключаюсь к Gemini Live API...")

    async with client.aio.live.connect(
        model=MODEL,
        config=config,
    ) as session:

        print("✅ Live API подключён!")
        print("🎙️ Включаю микрофон...")
        print()
        print("Говори в микрофон.")
        print("Для остановки нажми Ctrl+C.")
        print()

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            channels=CHANNELS,
            dtype="int16",
            callback=audio_callback,
        )

        stream.start()

        async def send_audio():
            while True:
                chunk = await asyncio.to_thread(
                    audio_queue.get
                )

                await session.send_realtime_input(
                    audio=types.Blob(
                        data=chunk,
                        mime_type="audio/pcm;rate=16000",
                    )
                )

        async def receive_events():
            async for response in session.receive():

                if response.server_content is None:
                    continue

                content = response.server_content

                # Входная речь пользователя,
                # распознанная Gemini.
                if content.input_transcription:

                    text = content.input_transcription.text

                    if text:
                        print(
                            f"👤 Ты: {text}",
                            flush=True,
                        )

                # Транскрипция ответа Gemini,
                # если модель что-то сказала.
                if content.output_transcription:

                    text = content.output_transcription.text

                    if text:
                        print(
                            f"🤖 Gemini: {text}",
                            flush=True,
                        )

        try:
            await asyncio.gather(
                send_audio(),
                receive_events(),
            )

        finally:
            stream.stop()
            stream.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print()
        print("🛑 Mic Test остановлен.")