import requests

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import TEXT_MODEL
from guard.models import GuardAnalysis
from guard.prompts import GUARD_PROMPT


SCOPES = [
    "https://www.googleapis.com/auth/generative-language.retriever"
]

PROJECT_ID = "gen-lang-client-0229154451"


def get_credentials():
    creds = Credentials.from_authorized_user_file(
        "token.json",
        SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        with open("token.json", "w") as token_file:
            token_file.write(creds.to_json())

    return creds


def analyze_text(user_text: str) -> GuardAnalysis:
    """
    Отправляет текст в Gemini через OAuth
    и возвращает структурированный GuardAnalysis.

    Risk score здесь НЕ рассчитывается.
    Его считает risk_engine.py.
    """

    if not user_text or not user_text.strip():
        raise ValueError("Пустой текст для анализа")

    creds = get_credentials()

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{TEXT_MODEL}:generateContent"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": GUARD_PROMPT},
                    {"text": "СИТУАЦИЯ ПОЛЬЗОВАТЕЛЯ:"},
                    {"text": user_text.strip()},
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
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
            "x-goog-user-project": PROJECT_ID,
        },
        json=payload,
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini OAuth error {response.status_code}: {response.text}"
        )

    data = response.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return GuardAnalysis.model_validate_json(text)
    except Exception as exc:
        raise RuntimeError(
            "Gemini вернул некорректный структурированный ответ"
        ) from exc