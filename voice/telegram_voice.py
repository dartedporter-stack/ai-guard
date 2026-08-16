import os

from google import genai

from config import GEMINI_API_KEY, TEXT_MODEL


# ============================================================
# GEMINI CLIENT
# ============================================================

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY не найден"
    )

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# TRANSCRIPTION PROMPT
# ============================================================

TRANSCRIPTION_PROMPT = """
Точно расшифруй это голосовое сообщение.

Правила:
- верни только текст речи;
- не добавляй комментарии;
- не придумывай отсутствующие слова;
- сохраняй смысл сказанного;
- сохраняй язык речи;
- если речь на русском, верни русский текст.
"""


# ============================================================
# TRANSCRIBE
# ============================================================

def transcribe_audio_file(
    file_path: str,
) -> str:

    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"Файл не найден: {file_path}"
        )

    uploaded_file = client.files.upload(
        file=file_path
    )

    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=[
            TRANSCRIPTION_PROMPT,
            uploaded_file,
        ],
    )

    text = response.text.strip()

    if not text:
        raise RuntimeError(
            "Gemini не вернул транскрипцию"
        )

    return text