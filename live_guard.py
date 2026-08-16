import asyncio
import os
import queue
import threading
import sys

import sounddevice as sd
from google import genai
from google.genai import types
from pydantic import BaseModel


LIVE_MODEL = "gemini-3.1-flash-live-preview"
ANALYSIS_MODEL = "gemini-3.1-flash-lite"

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не найден")

client = genai.Client(api_key=GEMINI_API_KEY)


class GuardAnalysis(BaseModel):
    risk_score: int
    category: str

    sms_code_request: bool
    money_request: bool
    bank_impersonation: bool
    urgency_pressure: bool
    personal_data_request: bool
    suspicious_link: bool
    fake_support: bool
    fake_prize: bool
    guaranteed_profit: bool

    warning: str
    action: str
    conclusion: str


PROMPT = """
Ты — AI GUARD.

Проанализируй текст разговора на признаки мошенничества.

Ищи:
- запрос SMS-кода;
- запрос денег;
- представление сотрудником банка;
- давление или срочность;
- запрос персональных данных;
- подозрительные ссылки;
- поддельную поддержку;
- подозрительные призы;
- гарантированную прибыль.

0–29 = низкий риск
30–59 = подозрительный
60–79 = высокий
80–100 = критический.

Само упоминание банка не означает мошенничество.

Все ответы на русском языке.
Не придумывай отсутствующие факты.

warning — короткое предупреждение.
action — конкретное безопасное действие.
conclusion — краткое объяснение.
"""


def risk_level(score):
    if score >= 80:
        return "🔴 КРИТИЧЕСКИЙ"
    if score >= 60:
        return "🟠 ВЫСОКИЙ"
    if score >= 30:
        return "🟡 ПОДОЗРИТЕЛЬНЫЙ"
    return "🟢 НИЗКИЙ"


async def analyze_text(text):

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=ANALYSIS_MODEL,
            contents=[
                PROMPT,
                "ФРАГМЕНТ РАЗГОВОРА:",
                text,
            ],
            config={
                "response_mime_type": "application/json",
                "response_json_schema":
                    GuardAnalysis.model_json_schema(),
            },
        )

        result = GuardAnalysis.model_validate_json(
            response.text
        )

        score = max(0, min(100, result.risk_score))

        print()
        print("=" * 60)
        print(f"🧠 РИСК: {score}/100")
        print(f"УРОВЕНЬ: {risk_level(score)}")
        print(f"📂 КАТЕГОРИЯ: {result.category}")
        print()
        print("⚠️ ПРЕДУПРЕЖДЕНИЕ:")
        print(result.warning)
        print()
        print("🛡️ ДЕЙСТВИЕ:")
        print(result.action)
        print()
        print("💡 ВЫВОД:")
        print(result.conclusion)
        print("=" * 60)
        print()

    except Exception as e:
        print("⚠️ Ошибка Risk Engine:", repr(e))


async def main():

    audio_queue = queue.Queue()

    print()
    print("🛡️ AI GUARD MANUAL LIVE")
    print("=" * 60)
    print("Пробел = начать/закончить фразу")
    print("Q = выйти")
    print()

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": True
            }
        }
    }

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=config,
    ) as session:

        print("✅ Live API подключён!")

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            channels=CHANNELS,
            dtype="int16",
            callback=lambda indata, frames, time, status:
                audio_queue.put(bytes(indata)),
        )

        stream.start()

        speaking = False
        collected_text = ""

        async def send_audio():

            while True:

                chunk = await asyncio.to_thread(
                    audio_queue.get
                )

                if speaking:

                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=chunk,
                            mime_type="audio/pcm;rate=16000",
                        )
                    )

        async def receive_transcript():

            nonlocal collected_text

            async for response in session.receive():

                if not response.server_content:
                    continue

                content = response.server_content

                if content.input_transcription:

                    text = content.input_transcription.text

                    if text:

                        text = text.strip()

                        if text:

                            print(
                                f"👤 Ты: {text}",
                                flush=True
                            )

                            collected_text += (
                                " " + text
                            )

        async def keyboard_control():

            nonlocal speaking
            nonlocal collected_text

            print()
            print("🎙️ Нажми ПРОБЕЛ и говори.")
            print("После речи снова нажми ПРОБЕЛ.")
            print()

            loop = asyncio.get_running_loop()

            def read_input():

                while True:

                    command = input("> ")

                    if command.lower() == "q":
                        return "quit"

                    return "toggle"

            while True:

                command = await asyncio.to_thread(
                    read_input
                )

                if command == "quit":
                    break

                if not speaking:

                    speaking = True
                    collected_text = ""

                    print("🎙️ ▶️ ГОВОРИ")

                    await session.send_realtime_input(
                        activity_start=types.ActivityStart()
                    )

                else:

                    speaking = False

                    print("🎙️ ⏹️ ФРАЗА ЗАКОНЧЕНА")

                    await session.send_realtime_input(
                        activity_end=types.ActivityEnd()
                    )

                    await asyncio.sleep(0.5)

                    if collected_text.strip():

                        snapshot = collected_text.strip()

                        print()
                        print("🧠 Анализирую...")
                        print()

                        await analyze_text(snapshot)

                        collected_text = ""

        try:

            await asyncio.gather(
                send_audio(),
                receive_transcript(),
                keyboard_control(),
            )

        finally:

            stream.stop()
            stream.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Остановлено.")