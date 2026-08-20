import os


# ============================================================
# API
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")


# ============================================================
# MODELS
# ============================================================

TEXT_MODEL = "gemini-3.1-flash-lite"
LIVE_MODEL = "gemini-3.1-flash-live-preview"


# ============================================================
# LIMITS
# ============================================================

MAX_MESSAGE_LENGTH = 10_000
MAX_CONTEXT_LENGTH = 4_000


# ============================================================
# RISK THRESHOLDS
# ============================================================

LOW_RISK_MAX = 29
SUSPICIOUS_RISK_MAX = 59
HIGH_RISK_MAX = 79


# ============================================================
# VALIDATION
# ============================================================

def validate_telegram_config():
    """
    Проверяет настройки, необходимые именно Telegram-боту.
    """

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не найден"
        )


def validate_gemini_config():
    """
    Проверяет настройки, необходимые Gemini.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY не найден"
        )


def validate_all_config():
    """
    Полная проверка конфигурации.
    """

    validate_telegram_config()
    validate_gemini_config()
