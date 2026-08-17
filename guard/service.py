import re

from guard.analyzer import analyze_text
from guard.risk_engine import calculate_fraud_risk
from guard.formatter import format_guard_result


URL_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\bhttps?://[^\s<>]+"
    r"|\bwww\.[^\s<>]+"
    r"|(?<![@\w])"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}"
    r"(?:/[^\s<>]*)?"
    r")"
)


def contains_url(text: str) -> bool:
    """
    Локально определяет наличие URL без сетевых запросов.
    """

    return bool(URL_PATTERN.search(text))


def analyze_and_format(
    text: str,
    has_url: bool = False,
) -> str:
    """
    Единая точка входа для GUARD.

    Неважно, пришёл текст из Telegram,
    транскрипция голосового или текст из Live API —
    всё проходит через один и тот же core.
    """

    analysis = analyze_text(text)

    has_url = has_url or contains_url(text)

    score, _ = calculate_fraud_risk(
        analysis
    )

    return format_guard_result(
        analysis=analysis,
        fraud_score=score,
        has_url=has_url,
    )
