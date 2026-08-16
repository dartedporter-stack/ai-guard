from guard.models import GuardAnalysis
from guard.risk_engine import (
    action_safety,
    context_label,
    format_factors,
    intent_label,
    risk_level,
)


# ============================================================
# CYBER RISK
# ============================================================

def cyber_risk_label(
    has_url: bool,
    suspicious_link: bool,
) -> tuple[str, str]:

    if not has_url:
        return (
            "NONE",
            "✅ Ссылка в сообщении не обнаружена.",
        )

    if suspicious_link:
        return (
            "UNKNOWN",
            "⚠️ Ссылка обнаружена, но её безопасность "
            "пока не проверялась внешним сервисом.",
        )

    return (
        "UNKNOWN",
        "⚠️ Ссылка обнаружена, но её безопасность "
        "пока не проверялась внешним сервисом.",
    )


# ============================================================
# RED FLAGS
# ============================================================

def format_red_flags(
    analysis: GuardAnalysis,
) -> str:

    if not analysis.red_flags:
        return (
            "• Явных признаков мошенничества "
            "не обнаружено"
        )

    return "\n".join(
        f"• {item}"
        for item in analysis.red_flags
    )


# ============================================================
# ACTIONS
# ============================================================

def format_actions(
    analysis: GuardAnalysis,
) -> str:

    if not analysis.actions:
        return (
            "• Специальных действий не требуется"
        )

    return "\n".join(
        f"• {item}"
        for item in analysis.actions
    )


# ============================================================
# FULL RESULT
# ============================================================

def format_guard_result(
    analysis: GuardAnalysis,
    fraud_score: int,
    has_url: bool = False,
) -> str:

    level = risk_level(
        fraud_score
    )

    intent = intent_label(
        analysis
    )

    context = context_label(
        analysis
    )

    action = action_safety(
        analysis,
        fraud_score,
    )

    factors = format_factors(
        []
    )

    # Получаем реальные факторы через повторный импорт,
    # чтобы formatter не содержал собственную Risk Engine.
    from guard.risk_engine import calculate_fraud_risk

    _, calculated_factors = calculate_fraud_risk(
        analysis
    )

    factors = format_factors(
        calculated_factors
    )

    cyber_risk, cyber_text = cyber_risk_label(
        has_url=has_url,
        suspicious_link=analysis.suspicious_link,
    )

    red_flags = format_red_flags(
        analysis
    )

    actions = format_actions(
        analysis
    )

    return (
        f"🚨 *РИСК МОШЕННИЧЕСТВА: "
        f"{fraud_score}/100*\n"
        f"*УРОВЕНЬ: {level}*\n\n"

        f"🌐 *КИБЕР-РИСК: {cyber_risk}*\n"
        f"{cyber_text}\n\n"

        f"⚖️ *БЕЗОПАСНОСТЬ ДЕЙСТВИЯ:*\n"
        f"{action}\n\n"

        f"🎯 *НАМЕРЕНИЕ:*\n"
        f"{intent}\n\n"

        f"📂 *КАТЕГОРИЯ:*\n"
        f"{analysis.category}\n\n"

        f"🧠 *КОНТЕКСТ:*\n"
        f"{context}\n\n"

        f"⚠️ *ФАКТОРЫ РИСКА:*\n"
        f"{factors}\n\n"

        f"🔎 *ЧТО НАСТОРАЖИВАЕТ:*\n"
        f"{red_flags}\n\n"

        f"🛡️ *ЧТО ДЕЛАТЬ:*\n"
        f"{actions}\n\n"

        f"💡 *ПОЧЕМУ ТАКОЙ РИСК:*\n"
        f"{analysis.conclusion}"
    )