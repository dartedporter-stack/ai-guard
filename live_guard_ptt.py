import asyncio
import os
import queue
import sys
import termios
import threading
import tty

import sounddevice as sd

from google import genai
from pydantic import BaseModel


# ============================================================
# MODELS
# ============================================================

LIVE_MODEL = "gemini-3.1-flash-live-preview"
ANALYSIS_MODEL = "gemini-3.1-flash-lite"


# ============================================================
# AUDIO
# ============================================================

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600  # 100 ms


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
# GUARD PROMPT
# ============================================================

GUARD_PROMPT = """
Ты — AI GUARD, анализатор мошенничества.

Проанализируй текст разговора.

Ищи:

1. Запрос SMS-кода, OTP или кода подтверждения.
2. Требование перевода денег, комиссии или предоплаты.
3. Представление сотрудником банка.
4. Давление, угрозы и срочность.
5. Запрос персональных или банковских данных.
6. Подозрительные ссылки.
7. Поддельную службу поддержки.
8. Подозрительные призы.
9. Обещание гарантированной прибыли.

Шкала:
0–29 — низкий риск
30–59 — подозрительный
60–79 — высокий
80–100 — критический.

Одно упоминание банка само по себе НЕ означает мошенничество.

Но комбинация:
банк + давление + SMS-код + угроза потери денег
является очень сильным признаком мошенничества.

Не придумывай отсутствующие факты.

Все текстовые поля пиши на русском.

warning:
короткое предупреждение.

action:
конкретное безопасное действие.

conclusion:
краткое объяснение.

Никогда не проси реальные SMS-коды,
пароли, PIN, CVV или банковские данные.
"""


# ============================================================
# TERMINAL KEY READER
# ============================================================

class KeyReader:
    """
    Читает отдельные клавиши из Terminal без необходимости
    устанавливать дополнительные библиотеки.

    SPACE = начать/закончить запись
    Q = выход
    """

    def __init__(self):
        self.old_settings = None
        self.running = True
        self.queue = queue.Queue()
        self.thread = None

    def start(self):
        self.old_settings = termios.tcgetattr(sys.stdin)

        tty.setcbreak(sys.stdin.fileno())

        self.thread = threading.Thread(
            target=self._read,
            daemon=True,
        )

        self.thread.start()

    def _read(self):
        while self.running:
            char = sys.stdin.read(1)

            if char == " ":
                self.queue.put("SPACE")

            elif char.lower() == "q":
                self.queue.put("QUIT")
                self.running = False

    def get_key(self):
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self.running = False

        if self.old_settings is not None:
            termios.tcsetattr(
                sys.stdin,
                termios.TCSADRAIN,
                self.old_settings,
            )


# ============================================================
# RISK ENGINE
# ============================================================

async def analyze_text(text: str):

    text = text.strip()

    if not text:
        print("⚠️ Пустая фраза.")
        return

    try:

        response = await asyncio.to_thread(
            client.models.generate_content,

            model=ANALYSIS_MODEL,

            contents=[
                GUARD_PROMPT,
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

        score = max(
            0,
            min(100, result.risk_score)
        )

        if score >= 80:
            level = "🔴 КРИТИЧЕСКИЙ"
        elif score >= 60:
            level = "🟠 ВЫСОКИЙ"
        elif score >= 30:
            level = "🟡 ПОДОЗРИТЕЛЬНЫЙ"
        else:
            level = "🟢 НИЗКИЙ"

        print()
        print("=" * 64)
        print(f"🚨 РИСК: {score}/100")
        print(f"УРОВЕНЬ: {level}")
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
        print("=" * 64)
        print()

    except Exception as e:
        print()
        print("⚠️ Ошибка Risk Engine:")
        print(repr(e))
        print()


# ============================================================
# ONE LIVE TURN
# ============================================================

async def record_one_turn():

    audio_queue = queue.Queue()

    recording = threading.Event()
    recording.set()

    audio_done = asyncio.Event()
    transcript_done = asyncio.Event()

    transcript_parts = []

    def audio_callback(indata, frames, time_info, status):

        if status:
            print(
                f"\n🎙️ Audio status: {status}",
                file=sys.stderr,
            )

        if recording.is_set():
            audio_queue.put(bytes(indata))

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Только распознавай входящую речь. "
                        "Не веди диалог и не отвечай пользователю."
                    )
                }
            ]
        },
    }

    # НОВАЯ сессия на каждую фразу.
    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=config,
    ) as session:

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            channels=CHANNELS,
            dtype="int16",
            callback=audio_callback,
        )

        stream.start()

        async def send_audio():

            try:

                while recording.is_set():

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
                        audio={
                            "data": chunk,
                            "mime_type": "audio/pcm;rate=16000",
                        }
                    )

            finally:

                audio_done.set()

        async def receive_transcript():

            try:

                async for response in session.receive():

                    if response.server_content is None:
                        continue

                    content = response.server_content

                    if content.input_transcription:

                        text = (
                            content
                            .input_transcription
                            .text
                        )

                        if text:

                            clean = text.strip()

                            if clean:

                                print(
                                    f"👤 Ты: {clean}",
                                    flush=True,
                                )

                                transcript_parts.append(
                                    clean
                                )

                    # После завершения server turn
                    # можем завершить получение.
                    if content.turn_complete:

                        break

            finally:

                transcript_done.set()

        sender = asyncio.create_task(
            send_audio()
        )

        receiver = asyncio.create_task(
            receive_transcript()
        )

        # Ожидаем клавишу SPACE для остановки.
        while True:

            key = await asyncio.to_thread(
                key_reader.get_key
            )

            if key == "SPACE":

                recording.clear()

                await session.send_realtime_input(
                    activity_end={}
                )

                break

            if key == "QUIT":

                recording.clear()

                await sender
                return None

            await asyncio.sleep(0.03)

        await sender

        # Даем Live API немного времени
        # закончить транскрипцию.
        try:

            await asyncio.wait_for(
                receiver,
                timeout=5.0,
            )

        except asyncio.TimeoutError:

            receiver.cancel()

        stream.stop()
        stream.close()

    return " ".join(transcript_parts)


# ============================================================
# MAIN
# ============================================================

async def main():

    global key_reader

    key_reader = KeyReader()
    key_reader.start()

    try:

        print()
        print("🛡️ AI GUARD PUSH-TO-TALK")
        print("=" * 64)
        print()
        print("SPACE → начать говорить")
        print("SPACE → закончить фразу")
        print("Q → выйти")
        print()
        print("✅ Готов.")
        print()

        while True:

            # Ждём начало нового turn
            while True:

                key = await asyncio.to_thread(
                    key_reader.get_key
                )

                if key == "QUIT":
                    return

                if key == "SPACE":
                    break

                await asyncio.sleep(0.03)

            print()
            print("🎙️ ▶️ ГОВОРИ...")
            print()

            text = await record_one_turn()

            if text is None:
                return

            print()
            print("🎙️ ⏹️ ФРАЗА ЗАКОНЧЕНА")

            if not text.strip():
                print("⚠️ Транскрипция пустая.")
                continue

            print()
            print("🧠 GUARD анализирует...")
            print()

            await analyze_text(text)

            print()
            print("✅ Готов к следующей фразе.")
            print("SPACE → новая фраза")
            print("Q → выйти")
            print()

    finally:

        key_reader.stop()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print("🛑 Остановлено.")