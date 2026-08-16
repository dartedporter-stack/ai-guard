from google import genai

from config import GEMINI_API_KEY, TEXT_MODEL
from guard.models import GuardAnalysis
from guard.prompts import GUARD_PROMPT


if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не найден")


client = genai.Client(
    api_key=GEMINI_API_KEY
)


def analyze_text(user_text: str) -> GuardAnalysis:
    """
    Отправляет текст в Gemini и возвращает
    структурированный GuardAnalysis.

    Risk score здесь НЕ рассчитывается.
    Его считает risk_engine.py.
    """

    if not user_text or not user_text.strip():
        raise ValueError("Пустой текст для анализа")

    response = client.models.generate_content(
        model=TEXT_MODEL,
        contents=[
            GUARD_PROMPT,
            "СИТУАЦИЯ ПОЛЬЗОВАТЕЛЯ:",
            user_text.strip(),
        ],
        config={
            "response_mime_type": "application/json",
            "response_json_schema": GuardAnalysis.model_json_schema(),
        },
    )

    try:
        return GuardAnalysis.model_validate_json(
            response.text
        )
    except Exception as exc:
        raise RuntimeError(
            "Gemini вернул некорректный структурированный ответ"
        ) from exc