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
# ============================================================

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600  # 100 ms


# ============================================================
# GUARD
# ============================================================

MIN_ANALYSIS_CHARS = 30
ANALYSIS_COOLDOWN = 4.0
MAX_CONTEXT_CHARS = 4000


# ============================================================
# API
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

Анализируй накопленный текст живого разговора.

Ищи признаки:

sms_code_request:
человека просят сообщить SMS-код, OTP или код подтверждения.

money_request:
человека просят перевести деньги, оплатить комиссию,
предоплату или другую сумму.

bank_impersonation:
собеседник выдаёт себя за банк или сотрудника банка.

urgency_pressure:
человека торопят, пугают, создают срочность
или угрожают потерей денег.

personal_data_request:
просят документы, данные карты, пароль
или другую чувствительную информацию.

suspicious_link:
упоминается подозрительная ссылка или сайт.

fake_support:
собеседник выдаёт себя за поддержку компании,
магазина или сервиса.

fake_prize:
обещают подозрительный приз или выигрыш.

guaranteed_profit:
обещают гарантированную прибыль.

Шкала:

0–29 = низкий риск
30–59 = подозрительный
60–79 = высокий
80–100 = критический.

Само слово "банк" не означает мошенничество.

Но сочетание:
неизвестный контакт
+ банк
+ давление
+ SMS-код
+ угроза потери денег

является очень сильным признаком мошенничества.

Не придумывай факты, которых нет в разговоре.

Все текстовые поля должны быть на русском языке.

warning:
короткое предупреждение.

action:
конкретное безопасное действие.

conclusion:
краткое объяснение.

Никогда не проси пользователя сообщать реальные
SMS-коды, пароли, PIN, CVV или банковские данные.
"""


# ============================================================
# STATE
# ============================================================

audio_queue = queue.Queue()

conversation_context = ""

last_analyzed_context = ""
last_analysis_time = 0.0

# Последний handle от SessionResumptionUpdate.
session_handle = None


# ============================================================
# HELPERS
# ============================================================

def risk_level(score: int) -> str:

    if score >= 80:
        return "🔴 КРИТИЧЕСКИЙ"

    if score >= 60:
        return "🟠 ВЫСОКИЙ"

    if score >= 30:
        return "🟡 ПОДОЗРИТЕЛЬНЫЙ"

    return "🟢 НИЗКИЙ"


def is_reconnect_error(error: Exception) -> bool:

    text = str(error).lower()

    reconnect_markers = (
        "connectionclosed",
        "connection closed",
        "1011",
        "1006",
        "keepalive",
        "ping timeout",
        "websocket",
        "timed out",
        "connection reset",
        "no close frame",
    )

    return any(
        marker in text
        for marker in reconnect_markers
    )


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

    if now - last_analysis_time < ANALYSIS_COOLDOWN:
        return

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
            min(100, result.risk_score)
        )

        level = risk_level(score)

        print(
            f"🧠 GUARD: {score}/100 — {level}"
        )

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

    audio_queue.put(
        bytes(indata)
    )


# ============================================================
# LIVE CONFIG
# ============================================================

def build_live_config(handle=None):

    config = {
        "response_modalities": [
            "AUDIO"
        ],

        "input_audio_transcription": {},

        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Работай как транскрибатор входящей речи. "
                        "Не веди обычный диалог и не задавай вопросы."
                    )
                }
            ]
        },

        # Сжатие контекста для долгих сессий.
        "context_window_compression": {
            "sliding_window": {}
        },

        # Восстановление WebSocket-сессии.
        "session_resumption": {
            "handle": handle
        },
    }

    return config


# ============================================================
# LIVE SESSION
# ============================================================

async def run_live_session():

    global session_handle
    global conversation_context

    config = build_live_config(
        session_handle
    )

    print()
    print(
        "🔌 Подключаюсь к Live API..."
    )

    if session_handle:

        print(
            "♻️ Пытаюсь восстановить предыдущую сессию..."
        )

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=config,
    ) as session:

        print(
            "✅ Live API подключён!"
        )

        # ----------------------------------------------------
        # SEND AUDIO
        # ----------------------------------------------------

        async def send_audio():

            while True:

                chunk = await asyncio.to_thread(
                    audio_queue.get
                )

                try:

                    await session.send_realtime_input(
                        audio={
                            "data": chunk,

                            "mime_type":
                                "audio/pcm;rate=16000",
                        }
                    )

                except Exception as e:

                    print(
                        "⚠️ Не удалось отправить audio:",
                        repr(e)
                    )

                    raise


        # ----------------------------------------------------
        # RECEIVE
        # ----------------------------------------------------

        async def receive_events():

            global conversation_context
            global session_handle

            async for response in session.receive():

                # =================================================
                # SESSION RESUMPTION
                # =================================================

                if response.session_resumption_update:

                    update = (
                        response
                        .session_resumption_update
                    )

                    if (
                        update.resumable
                        and update.new_handle
                    ):

                        session_handle = (
                            update.new_handle
                        )

                        print(
                            "💾 Session resumption handle обновлён."
                        )

                # =================================================
                # SERVER CONTENT
                # =================================================

                if response.server_content is None:
                    continue

                content = response.server_content

                # -------------------------------------------------
                # INPUT TRANSCRIPTION
                # -------------------------------------------------

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
                                flush=True
                            )

                            conversation_context += (
                                " " + clean
                            )

                            if (
                                len(conversation_context)
                                > MAX_CONTEXT_CHARS
                            ):

                                conversation_context = (
                                    conversation_context[
                                        -MAX_CONTEXT_CHARS:
                                    ]
                                )

                            asyncio.create_task(
                                analyze_context(
                                    conversation_context
                                )
                            )

                # -------------------------------------------------
                # GoAway
                # -------------------------------------------------

                if response.go_away:

                    print()
                    print(
                        "⚠️ Сервер сообщил, "
                        "что соединение скоро завершится."
                    )

                    try:

                        print(
                            "⏳ time_left:",
                            response.go_away.time_left
                        )

                    except Exception:
                        pass

                    raise ConnectionError(
                        "Gemini Live GoAway"
                    )


        await asyncio.gather(
            send_audio(),
            receive_events(),
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print(
        "🛡️ AI GUARD LIVE v0.9.5"
    )
    print("=" * 64)

    print(
        "Live model:",
        LIVE_MODEL
    )

    print(
        "Risk model:",
        ANALYSIS_MODEL
    )

    print()
    print(
        "🎙️ Микрофон запускается..."
    )

    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCKSIZE,
        channels=CHANNELS,
        dtype="int16",
        callback=audio_callback,
    )

    stream.start()

    print(
        "✅ Микрофон включён."
    )

    print(
        "🧠 GUARD слушает..."
    )

    print()
    print(
        "Говори свободно."
    )

    print(
        "Если Live API разорвёт соединение, "
        "GUARD автоматически попробует подключиться снова."
    )

    print()
    print(
        "Ctrl+C — остановить."
    )

    reconnect_delay = 1.0

    try:

        while True:

            try:

                await run_live_session()

                # Если сессия завершилась без ошибки,
                # дадим небольшую паузу.
                print(
                    "ℹ️ Live-сессия завершилась."
                )

                await asyncio.sleep(
                    reconnect_delay
                )

            except asyncio.CancelledError:

                raise

            except Exception as e:

                print()
                print(
                    "⚠️ Live-сессия прервана:"
                )

                print(
                    repr(e)
                )

                if not is_reconnect_error(e):

                    print(
                        "🔄 Всё равно попробуем "
                        "переподключиться."
                    )

                print(
                    f"🔄 Reconnect через "
                    f"{reconnect_delay:.1f} сек..."
                )

                await asyncio.sleep(
                    reconnect_delay
                )

                # Экспоненциальная задержка,
                # максимум 8 секунд.
                reconnect_delay = min(
                    reconnect_delay * 2,
                    8.0
                )

                print(
                    "♻️ Переподключение..."
                )

            else:

                reconnect_delay = 1.0

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