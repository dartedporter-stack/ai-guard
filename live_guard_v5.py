import asyncio
import os
import queue
import select
import sys
import termios
import threading
import tty

import sounddevice as sd

from google import genai
from google.genai import types
from pydantic import BaseModel


# ============================================================
# SETTINGS
# ============================================================

LIVE_MODEL = "gemini-3.1-flash-live-preview"
ANALYSIS_MODEL = "gemini-3.1-flash-lite"

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600


# ============================================================
# API
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не найден")

client = genai.Client(api_key=GEMINI_API_KEY)


# ============================================================
# STRUCTURED RESULT
# ============================================================

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


# ============================================================
# PROMPT
# ============================================================

GUARD_PROMPT = """
Ты — AI GUARD, анализатор мошенничества.

Анализируй только текущий фрагмент речи.

Ищи:

sms_code_request:
человека просят сообщить SMS-код, OTP или код подтверждения.

money_request:
просят перевести деньги, оплатить комиссию,
предоплату или другую сумму.

bank_impersonation:
собеседник представляется банком или сотрудником банка.

urgency_pressure:
человека торопят, пугают, создают срочность
или угрожают.

personal_data_request:
просят документы, данные карты, пароль
или другую чувствительную информацию.

suspicious_link:
упоминается подозрительная ссылка или сайт.

fake_support:
собеседник представляется поддержкой компании,
магазина или сервиса.

fake_prize:
обещают подозрительный приз или выигрыш.

guaranteed_profit:
обещают гарантированную прибыль.

Шкала:
0–29 = низкий
30–59 = подозрительный
60–79 = высокий
80–100 = критический.

Одно слово "банк" НЕ означает мошенничество.
Одно слово "SMS" НЕ означает мошенничество.

Комбинация банка, давления, угрозы потери денег
и запроса SMS-кода является сильным признаком мошенничества.

Не используй старые фразы.
Не придумывай отсутствующие факты.

Все текстовые поля на русском языке.

warning — короткое предупреждение.
action — безопасное действие.
conclusion — краткое объяснение.

Никогда не проси реальные SMS-коды,
пароли, PIN, CVV или банковские данные.
"""


# ============================================================
# RISK
# ============================================================

def risk_level(score: int):
    if score >= 80:
        return "🔴 КРИТИЧЕСКИЙ"
    if score >= 60:
        return "🟠 ВЫСОКИЙ"
    if score >= 30:
        return "🟡 ПОДОЗРИТЕЛЬНЫЙ"
    return "🟢 НИЗКИЙ"


async def analyze_text(text: str):

    text = text.strip()

    if not text:
        print("⚠️ Речь не распознана.")
        return

    try:
        print("\n🧠 GUARD анализирует...")

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=ANALYSIS_MODEL,
            contents=[
                GUARD_PROMPT,
                "ТЕКУЩИЙ ФРАГМЕНТ:",
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
        print(f"🚨 РИСК: {score}/100")
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
        print("\n⚠️ Ошибка Risk Engine:")
        print(repr(e))


# ============================================================
# KEYBOARD
# ============================================================

class Keyboard:
    def __init__(self):
        self.old_settings = None

    def start(self):
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    def stop(self):
        if self.old_settings is not None:
            termios.tcsetattr(
                sys.stdin,
                termios.TCSADRAIN,
                self.old_settings,
            )

    def read_key(self):
        ready, _, _ = select.select(
            [sys.stdin],
            [],
            [],
            0,
        )

        if not ready:
            return None

        return sys.stdin.read(1).lower()


# ============================================================
# ONE PHRASE
# ============================================================

async def record_phrase():

    audio_queue = queue.Queue()
    transcript = []

    recording = True

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": True
            }
        },
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Только распознавай входящую речь. "
                        "Не веди диалог."
                    )
                }
            ]
        },
    }

    print("\n🔌 Новая Live-сессия...")

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=config,
    ) as session:

        print("✅ Live API подключён.")

        def callback(indata, frames, time_info, status):

            if status:
                print(
                    "\n🎙️ Audio status:",
                    status,
                )

            if recording:
                audio_queue.put(bytes(indata))

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
        )

        stream.start()

        # Начало пользовательского turn.
        await session.send_realtime_input(
            activity_start=types.ActivityStart()
        )

        print("🎙️ ГОВОРИ...")
        print("Нажми S, когда закончишь.")

        async def send_audio():

            while recording:

                try:
                    chunk = await asyncio.wait_for(
                        asyncio.to_thread(
                            audio_queue.get
                        ),
                        timeout=0.2,
                    )
                except asyncio.TimeoutError:
                    continue

                await session.send_realtime_input(
                    audio=types.Blob(
                        data=chunk,
                        mime_type="audio/pcm;rate=16000",
                    )
                )

        async def receive_transcript():

            try:
                async for response in session.receive():

                    if response.server_content is None:
                        continue

                    content = response.server_content

                    if content.input_transcription:

                        text = content.input_transcription.text

                        if text:
                            clean = text.strip()

                            if clean:
                                print(
                                    f"\n👤 Ты: {clean}",
                                    flush=True
                                )

                                transcript.append(
                                    clean
                                )

                    if content.turn_complete:
                        break

            except Exception as e:
                print(
                    "\n⚠️ Ошибка транскрипции:",
                    repr(e)
                )

        sender = asyncio.create_task(
            send_audio()
        )

        receiver = asyncio.create_task(
            receive_transcript()
        )

        keyboard = Keyboard()

        try:
            keyboard.start()

            while True:

                key = keyboard.read_key()

                if key == "s":
                    break

                if key == "q":

                    recording = False

                    sender.cancel()
                    receiver.cancel()

                    return None, True

                await asyncio.sleep(0.03)

        finally:
            keyboard.stop()

        recording = False

        print("\n⏹️ Остановка записи...")

        # При manual VAD используем activityEnd.
        await session.send_realtime_input(
            activity_end=types.ActivityEnd()
        )

        # Даём sender закончить.
        try:
            await asyncio.wait_for(
                sender,
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            sender.cancel()

        # Ждём финальную транскрипцию.
        try:
            await asyncio.wait_for(
                receiver,
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            receiver.cancel()

        stream.stop()
        stream.close()

    return " ".join(transcript).strip(), False


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print("=" * 60)
    print("🛡️ AI GUARD LIVE v0.10.1")
    print("=" * 60)
    print()
    print("R → начать фразу")
    print("S → закончить фразу")
    print("Q → выйти")
    print()

    keyboard = Keyboard()
    keyboard.start()

    try:

        while True:

            print(
                "▶️ Нажми R..."
            )

            # Ждём R или Q.
            while True:

                key = keyboard.read_key()

                if key == "q":
                    return

                if key == "r":
                    break

                await asyncio.sleep(0.03)

            # Keyboard temporarily остаётся активным.
            text, should_quit = await record_phrase()

            if should_quit:
                return

            if not text:
                print(
                    "\n⚠️ Транскрипция пустая."
                )
                continue

            print()
            print("📝 ТРАНСКРИПЦИЯ:")
            print(text)

            await analyze_text(text)

            print()
            print(
                "✅ Готов к следующему фрагменту."
            )
            print()

    finally:

        keyboard.stop()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 AI GUARD остановлен.")