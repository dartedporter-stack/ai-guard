import asyncio
import os
import queue
import sys
import time

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
# Берём тот же формат, который уже работал в mic_test.py
# ============================================================

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600


# ============================================================
# GUARD SETTINGS
# ============================================================

MIN_ANALYSIS_CHARS = 30
ANALYSIS_COOLDOWN = 4.0
MAX_CONTEXT_CHARS = 4000


# ============================================================
# API KEY
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не найден")


client = genai.Client(
    api_key=GEMINI_API_KEY
)


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
Ты — AI GUARD, realtime-анализатор мошенничества.

Тебе передаётся накопленный текст живого разговора.

Анализируй весь контекст.

Ищи признаки:

sms_code_request:
человека просят сообщить SMS-код, OTP
или код подтверждения.

money_request:
человека просят перевести деньги,
оплатить комиссию, предоплату
или другую сумму.

bank_impersonation:
собеседник выдаёт себя за банк
или сотрудника банка.

urgency_pressure:
человека торопят, пугают,
создают срочность или угрожают.

personal_data_request:
просят паспортные данные,
данные карты, пароль или другую
чувствительную информацию.

suspicious_link:
упоминается подозрительная ссылка
или неизвестный сайт.

fake_support:
собеседник выдаёт себя за поддержку
компании, магазина или сервиса.

fake_prize:
обещают подозрительный приз
или выигрыш.

guaranteed_profit:
обещают гарантированную прибыль.

Шкала:

0–29 = низкий риск
30–59 = подозрительный
60–79 = высокий
80–100 = критический.

ВАЖНО:

Само слово "банк" не означает мошенничество.

Само слово "SMS" не означает мошенничество.

Но сочетание:

неизвестный контакт
+ банк
+ давление
+ запрос SMS-кода
+ угроза потери денег

является очень сильным признаком мошенничества.

Не придумывай факты, которых нет в разговоре.

Все текстовые поля должны быть на русском языке.

warning:
короткое предупреждение.

action:
конкретное безопасное действие.

conclusion:
кратко объясни причину оценки.

Если риск низкий, не пугай человека.

Никогда не проси пользователя сообщать
реальные SMS-коды, пароли, PIN, CVV
или банковские данные.
"""


# ============================================================
# STATE
# ============================================================

audio_queue = queue.Queue()

conversation_context = ""

last_analyzed_context = ""
last_analysis_time = 0.0


# ============================================================
# RISK LEVEL
# ============================================================

def risk_level(score: int):

    if score >= 80:
        return "🔴 КРИТИЧЕСКИЙ"

    if score >= 60:
        return "🟠 ВЫСОКИЙ"

    if score >= 30:
        return "🟡 ПОДОЗРИТЕЛЬНЫЙ"

    return "🟢 НИЗКИЙ"


# ============================================================
# RISK ENGINE
# ============================================================

async def analyze_context(text: str):

    global last_analyzed_context
    global last_analysis_time

    text = text.strip()

    if len(text) < MIN_ANALYSIS_CHARS:
        return

    now = time.monotonic()

    # Не отправляем запросы слишком часто
    if now - last_analysis_time < ANALYSIS_COOLDOWN:
        return

    # Не анализируем одинаковый контекст
    if text == last_analyzed_context:
        return

    last_analyzed_context = text
    last_analysis_time = now

    try:

        response = await asyncio.to_thread(
            client.models.generate_content,

            model=ANALYSIS_MODEL,

            contents=[
                GUARD_PROMPT,
                "НАКОПЛЕННЫЙ КОНТЕКСТ РАЗГОВОРА:",
                text,
            ],

            config={
                "response_mime_type":
                    "application/json",

                "response_json_schema":
                    GuardAnalysis.model_json_schema(),
            },
        )

        result = GuardAnalysis.model_validate_json(
            response.text
        )

        score = max(
            0,
            min(
                100,
                result.risk_score
            )
        )

        level = risk_level(score)

        print()
        print(
            f"🧠 GUARD: {score}/100 — {level}"
        )

        # Нормальный разговор просто показываем
        if score < 60:
            return

        print()
        print("=" * 64)
        print("🚨🚨🚨 GUARD ALERT 🚨🚨🚨")
        print("=" * 64)

        print(
            f"🚨 РИСК: {score}/100"
        )

        print(
            f"УРОВЕНЬ: {level}"
        )

        print(
            f"📂 КАТЕГОРИЯ: {result.category}"
        )

        print()

        print(
            "⚠️ ПРЕДУПРЕЖДЕНИЕ:"
        )

        print(
            result.warning
        )

        print()

        print(
            "🛡️ ДЕЙСТВИЕ:"
        )

        print(
            result.action
        )

        print()

        print(
            "💡 ВЫВОД:"
        )

        print(
            result.conclusion
        )

        print("=" * 64)
        print()

    except Exception as e:

        print(
            "⚠️ Ошибка Risk Engine:",
            repr(e)
        )


# ============================================================
# MICROPHONE CALLBACK
# ============================================================

def audio_callback(
    indata,
    frames,
    time_info,
    status
):

    if status:

        print(
            "🎙️ Audio status:",
            status,
            file=sys.stderr
        )

    # Копируем bytes — точно как в нашем рабочем mic_test.
    audio_queue.put(
        bytes(indata)
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    global conversation_context

    print()
    print("🛡️ AI GUARD LIVE v2")
    print("=" * 64)

    print(
        f"Live model: {LIVE_MODEL}"
    )

    print(
        f"Risk model: {ANALYSIS_MODEL}"
    )

    print()
    print(
        "Подключаюсь к Gemini Live API..."
    )

    # Никакого ручного VAD.
    # Используем ту же базовую конфигурацию,
    # которая уже успешно работала в mic_test.py.
    config = {
        "response_modalities": [
            "AUDIO"
        ],

        "input_audio_transcription": {},

        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Ты работаешь как транскрибатор. "
                        "Распознавай входящую речь. "
                        "Не отвечай пользователю по существу. "
                        "Не задавай вопросов и не веди диалог."
                    )
                }
            ]
        },
    }

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=config,
    ) as session:

        print(
            "✅ Live API подключён!"
        )

        # ====================================================
        # MICROPHONE
        # ====================================================

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            channels=CHANNELS,
            dtype="int16",
            callback=audio_callback,
        )

        stream.start()

        print(
            "🎙️ Микрофон включён."
        )

        print()
        print(
            "🧠 GUARD слушает..."
        )

        print(
            "Говори свободно — как в обычном разговоре."
        )

        print()
        print(
            "Тестовая фраза:"
        )

        print(
            "«Мне позвонили якобы из банка "
            "и попросили назвать код из SMS»"
        )

        print()
        print(
            "Для остановки: Ctrl+C"
        )

        print()

        # ====================================================
        # SEND AUDIO
        # ====================================================

        async def send_audio():

            while True:

                chunk = await asyncio.to_thread(
                    audio_queue.get
                )

                await session.send_realtime_input(
                    audio={
                        "data": chunk,
                        "mime_type":
                            "audio/pcm;rate=16000",
                    }
                )

        # ====================================================
        # RECEIVE EVENTS
        # ====================================================

        async def receive_events():

            global conversation_context

            async for response in session.receive():

                if response.server_content is None:
                    continue

                content = response.server_content

                # ------------------------------------------------
                # ТОЛЬКО INPUT TRANSCRIPTION
                # ------------------------------------------------

                if content.input_transcription:

                    text = (
                        content
                        .input_transcription
                        .text
                    )

                    if not text:
                        continue

                    clean = text.strip()

                    if not clean:
                        continue

                    print(
                        f"👤 Ты: {clean}",
                        flush=True
                    )

                    # Добавляем в общий контекст
                    conversation_context += (
                        " " + clean
                    )

                    # Оставляем последние 4000 символов
                    if (
                        len(conversation_context)
                        > MAX_CONTEXT_CHARS
                    ):

                        conversation_context = (
                            conversation_context[
                                -MAX_CONTEXT_CHARS:
                            ]
                        )

                    # ------------------------------------------------
                    # Risk Engine работает отдельно от Live API
                    # ------------------------------------------------

                    asyncio.create_task(
                        analyze_context(
                            conversation_context
                        )
                    )

                # ------------------------------------------------
                # output_transcription НАМ НЕ НУЖЕН
                # ------------------------------------------------

        try:

            await asyncio.gather(
                send_audio(),
                receive_events(),
            )

        finally:

            stream.stop()
            stream.close()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "🛑 AI GUARD LIVE остановлен."
        )