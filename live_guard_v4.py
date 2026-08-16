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

MIN_ANALYSIS_CHARS = 35
ANALYSIS_INTERVAL = 3.0

# Только свежая речь, а не весь разговор.
MAX_FRESH_TEXT = 1200

# Небольшой контекст последних фрагментов.
MAX_CONTEXT = 1800

# Сколько reconnect подряд допускаем перед сбросом handle.
MAX_RESUME_FAILURES = 2


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
# STRUCTURED RISK RESULT
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
Ты — AI GUARD, realtime-анализатор мошенничества.

Тебе передаётся НОВЫЙ ФРАГМЕНТ живого разговора.

Главное правило:
оценивай прежде всего НОВУЮ речь.
Старый контекст может помочь понять смысл,
но старые подозрительные фразы не должны сами по себе
делать новую безобидную фразу опасной.

Ищи:

sms_code_request:
человека просят сообщить SMS-код, OTP или код подтверждения.

money_request:
просят перевести деньги, оплатить комиссию,
предоплату или другую сумму.

bank_impersonation:
собеседник выдаёт себя за банк или сотрудника банка.

urgency_pressure:
человека торопят, пугают, создают срочность
или угрожают.

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

0–29 = низкий
30–59 = подозрительный
60–79 = высокий
80–100 = критический.

ВАЖНО:

Само слово "банк" не означает мошенничество.

Само слово "SMS" не означает мошенничество.

Например:

"Мне позвонили из банка"
→ низкий или умеренный риск.

Но:

"Мне позвонили из банка и потребовали срочно назвать код SMS,
иначе я потеряю деньги"
→ очень высокий риск.

Не переноси высокий риск со старого фрагмента,
если в новом фрагменте нет соответствующих признаков.

Все текстовые поля должны быть на русском языке.

warning:
короткое предупреждение, если оно необходимо.

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

# Новые фрагменты, которые ещё не анализировались.
pending_text = ""

# Короткий контекст для отображения/понимания.
recent_context = ""

last_analysis_time = 0.0

session_handle = None

resume_failures = 0


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
# ANALYZE ONLY FRESH TEXT
# ============================================================

async def analyze_fresh_text(text: str):

    global last_analysis_time

    text = text.strip()

    if len(text) < MIN_ANALYSIS_CHARS:
        return

    now = time.monotonic()

    if now - last_analysis_time < ANALYSIS_INTERVAL:
        return

    last_analysis_time = now

    # Берём только свежий фрагмент.
    fresh_text = text[-MAX_FRESH_TEXT:]

    # Короткий контекст можно показать модели,
    # но оцениваться должна свежая речь.
    context_for_model = recent_context[-600:]

    try:

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=ANALYSIS_MODEL,
            contents=[
                GUARD_PROMPT,
                "ПОСЛЕДНИЙ ФРАГМЕНТ РЕЧИ:",
                fresh_text,
                "КРАТКИЙ КОНТЕКСТ ДО ЭТОГО:",
                context_for_model,
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

        # Показываем полный alert только при высоком риске.
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

        "context_window_compression": {
            "sliding_window": {}
        },

        "session_resumption": {
            "handle": handle
        },

        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Распознавай входящую речь. "
                        "Не веди обычный диалог. "
                        "Не задавай пользователю вопросы."
                    )
                }
            ]
        },
    }

    return config


# ============================================================
# LIVE SESSION
# ============================================================

async def run_session():

    global session_handle
    global pending_text
    global recent_context
    global resume_failures

    print()
    print(
        "🔌 Подключаюсь к Gemini Live..."
    )

    if session_handle:

        print(
            "♻️ Использую сохранённый session handle."
        )

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=build_live_config(
            session_handle
        ),
    ) as session:

        print(
            "✅ Live API подключён!"
        )

        resume_failures = 0

        # ----------------------------------------------------
        # SEND AUDIO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # RECEIVE
        # ----------------------------------------------------

        async def receive_events():

            global session_handle
            global pending_text
            global recent_context

            async for response in session.receive():

                # =================================================
                # SESSION RESUMPTION UPDATE
                # =================================================

                if response.session_resumption_update:

                    update = (
                        response
                        .session_resumption_update
                    )

                    if (
                        update.resumable
                        and update.new_handle
                        and update.new_handle
                        != session_handle
                    ):

                        session_handle = (
                            update.new_handle
                        )

                        print(
                            "💾 Session resumption обновлён ✅"
                        )

                # =================================================
                # GO AWAY
                # =================================================

                if response.go_away:

                    print()
                    print(
                        "⚠️ Сервер предупредил "
                        "о скором завершении соединения."
                    )

                    raise ConnectionError(
                        "Gemini Live GoAway"
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

                    if not text:
                        continue

                    clean = text.strip()

                    if not clean:
                        continue

                    print(
                        f"👤 Ты: {clean}",
                        flush=True
                    )

                    # Только новые слова.
                    pending_text += (
                        " " + clean
                    )

                    # Короткий recent context.
                    recent_context += (
                        " " + clean
                    )

                    if len(recent_context) > MAX_CONTEXT:
                        recent_context = (
                            recent_context[
                                -MAX_CONTEXT:
                            ]
                        )

                    # -------------------------------------------------
                    # ANALYSIS
                    # -------------------------------------------------

                    if len(pending_text) >= MIN_ANALYSIS_CHARS:

                        snapshot = pending_text

                        # ВАЖНО:
                        # сбрасываем pending сразу,
                        # чтобы следующая речь считалась новой.
                        pending_text = ""

                        asyncio.create_task(
                            analyze_fresh_text(
                                snapshot
                            )
                        )

                # output_transcription намеренно не используем.

        await asyncio.gather(
            send_audio(),
            receive_events(),
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    global session_handle
    global resume_failures

    print()
    print(
        "🛡️ AI GUARD LIVE v0.9.6"
    )

    print(
        "=" * 64
    )

    print(
        "Live:",
        LIVE_MODEL
    )

    print(
        "Risk:",
        ANALYSIS_MODEL
    )

    print()
    print(
        "🎙️ Запускаю микрофон..."
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
        "Если соединение упадёт, программа попробует восстановиться."
    )

    print()
    print(
        "Ctrl+C — остановить."
    )

    reconnect_delay = 1.0

    try:

        while True:

            try:

                await run_session()

                print(
                    "ℹ️ Live-сессия завершилась."
                )

                await asyncio.sleep(
                    reconnect_delay
                )

                reconnect_delay = 1.0

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

                resume_failures += 1

                # ---------------------------------------------
                # Если несколько раз подряд не удаётся
                # восстановить состояние, начинаем чистую сессию.
                # ---------------------------------------------

                if resume_failures >= MAX_RESUME_FAILURES:

                    print()
                    print(
                        "🧹 Сбрасываю старый "
                        "session resumption handle."
                    )

                    session_handle = None
                    resume_failures = 0

                print(
                    f"🔄 Переподключение через "
                    f"{reconnect_delay:.1f} сек..."
                )

                await asyncio.sleep(
                    reconnect_delay
                )

                reconnect_delay = min(
                    reconnect_delay * 2,
                    8.0
                )

                print(
                    "♻️ Переподключаюсь..."
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