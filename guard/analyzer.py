import requests

from config import GEMINI_API_KEY, TEXT_MODEL
from guard.models import GuardAnalysis
from guard.prompts import GUARD_PROMPT


def analyze_text(user_text: str) -> GuardAnalysis:
    """
    Отправляет текст в Gemini через серверный API-ключ
    и возвращает структурированный GuardAnalysis.

    Risk score здесь НЕ рассчитывается.
    Его считает risk_engine.py.
    """

    if not user_text or not user_text.strip():
        raise ValueError("Пустой текст для анализа")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY не найден")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{TEXT_MODEL}:generateContent"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": GUARD_PROMPT
                    },
                    {
                        "text": "СИТУАЦИЯ ПОЛЬЗОВАТЕЛЯ:"
                    },
                    {
                        "text": user_text.strip()
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": GuardAnalysis.model_json_schema(),
        },
    }

    response = requests.post(
        url,
        headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini API error "
            f"{response.status_code}: {response.text}"
        )

    data = response.json()

    try:
        text = (
            data["candidates"][0]
            ["content"]
            ["parts"][0]
            ["text"]
        )

        return GuardAnalysis.model_validate_json(text)

    except Exception as exc:
        raise RuntimeError(
            "Gemini вернул некорректный структурированный ответ"
        ) from exc
