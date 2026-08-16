from guard.analyzer import analyze_text
from guard.risk_engine import calculate_fraud_risk
from guard.formatter import format_guard_result


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

    score, _ = calculate_fraud_risk(
        analysis
    )

    return format_guard_result(
        analysis=analysis,
        fraud_score=score,
        has_url=has_url,
    )