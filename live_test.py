import asyncio
import os

from google import genai


MODEL = "gemini-3.1-flash-live-preview"


async def main():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не найден")

    client = genai.Client(api_key=api_key)

    # Для Gemini 3.1 Flash Live используем AUDIO.
    # Текстовую расшифровку ответа включаем отдельно.
    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
    }

    print("🛡️ GUARD Live Test")
    print("Подключаюсь к Gemini Live API...")

    try:
        async with client.aio.live.connect(
            model=MODEL,
            config=config,
        ) as session:

            print("✅ Live API подключён!")
            print("📡 WebSocket-сессия установлена.")
            print()

            # Пока отправляем текст, чтобы проверить сам Live API.
            await session.send_realtime_input(
                text="Ответь коротко: Live GUARD работает."
            )

            print("📨 Тестовый запрос отправлен.")
            print("⏳ Жду ответ...")
            print()

            async for response in session.receive():

                if response.server_content is None:
                    continue

                content = response.server_content

                # Расшифровка ответа Gemini
                if content.output_transcription:
                    text = content.output_transcription.text

                    if text:
                        print("🤖 Gemini:", text)

                # Когда ход Gemini завершён
                if content.turn_complete:
                    print()
                    print("✅ Ответ получен.")
                    break

    except Exception as e:
        print()
        print("❌ Ошибка Live API:")
        print(repr(e))


if __name__ == "__main__":
    asyncio.run(main())