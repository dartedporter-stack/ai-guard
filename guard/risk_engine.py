from guard.models import GuardAnalysis
from config import (
    LOW_RISK_MAX,
    SUSPICIOUS_RISK_MAX,
    HIGH_RISK_MAX,
)


# ============================================================
# BASE WEIGHTS
# ============================================================

BASE_WEIGHTS = {
    "sms_code_request": 30,
    "money_request": 25,
    "personal_data_request": 20,
    "suspicious_link": 20,
    "urgency_pressure": 15,
    "bank_impersonation": 20,
    "fake_support": 15,
    "fake_prize": 25,
    "guaranteed_profit": 20,
    "suspicious_deal": 15,

    "fake_job": 25,
    "rental_scam": 25,
    "no_inspection": 15,
    "remote_seller": 10,
    "advance_payment": 25,

    # Особый случай — вес зависит от намерения.
    "regulated_or_illicit_document_offer": 0,

    "harmful_or_unsafe_action": 25,
}


# ============================================================
# HUMAN-READABLE FACTOR NAMES
# ============================================================

FACTOR_NAMES = {
    "sms_code_request":
        "Запрос SMS-кода",

    "money_request":
        "Требование денег или предоплаты",

    "personal_data_request":
        "Запрос персональных данных",

    "suspicious_link":
        "Подозрительная ссылка",

    "urgency_pressure":
        "Давление или срочность",

    "bank_impersonation":
        "Представление сотрудником банка",

    "fake_support":
        "Поддельная служба поддержки",

    "fake_prize":
        "Подозрительный приз или выигрыш",

    "guaranteed_profit":
        "Обещание гарантированной прибыли",

    "suspicious_deal":
        "Подозрительные условия сделки",

    "fake_job":
        "Признаки мошенничества при трудоустройстве",

    "rental_scam":
        "Признаки мошенничества с недвижимостью",

    "no_inspection":
        "Невозможность проверить объект лично",

    "remote_seller":
        "Продавец или арендодатель находится далеко",

    "advance_payment":
        "Требование предоплаты",

    "regulated_or_illicit_document_offer":
        "Предложение получить регулируемый документ в обход процедуры",

    "harmful_or_unsafe_action":
        "Потенциально опасное действие",
}


# ============================================================
# INTENT NAMES
# ============================================================

INTENT_NAMES = {
    "OBSERVATION":
        "Наблюдение",

    "CONSIDERATION":
        "Рассматривает вариант",

    "INTENT":
        "Собирается действовать",

    "ACTION":
        "Действие уже совершено",
}


# ============================================================
# RISK LEVEL
# ============================================================

def risk_level(score: int) -> str:

    if score > HIGH_RISK_MAX:
        return "🔴 КРИТИЧЕСКИЙ"

    if score > SUSPICIOUS_RISK_MAX:
        return "🟠 ВЫСОКИЙ"

    if score > LOW_RISK_MAX:
        return "🟡 ПОДОЗРИТЕЛЬНЫЙ"

    return "🟢 НИЗКИЙ"


# ============================================================
# FRAUD RISK CALCULATION
# ============================================================

def calculate_fraud_risk(
    analysis: GuardAnalysis,
) -> tuple[int, list[tuple[str, int]]]:

    score = 0
    factors = []

    # --------------------------------------------------------
    # REGULATED DOCUMENTS
    # --------------------------------------------------------
    #
    # Здесь не используем обычный вес.
    # Балл зависит от намерения пользователя.
    #

    if analysis.regulated_or_illicit_document_offer:

        if analysis.user_intent == "OBSERVATION":
            document_score = 60

        elif analysis.user_intent == "CONSIDERATION":
            document_score = 70

        elif analysis.user_intent == "INTENT":
            document_score = 90

        elif analysis.user_intent == "ACTION":
            document_score = 100

        else:
            document_score = 70

        score = max(
            score,
            document_score,
        )

        factors.append(
            (
                "regulated_or_illicit_document_offer",
                document_score,
            )
        )

        # Предложение документа + деньги
        if analysis.money_request:
            score += 10

            factors.append(
                (
                    "money_request",
                    10,
                )
            )

    # --------------------------------------------------------
    # GENERAL FACTORS
    # --------------------------------------------------------

    for name, weight in BASE_WEIGHTS.items():

        if name == "regulated_or_illicit_document_offer":
            continue

        if getattr(analysis, name):

            score += weight

            factors.append(
                (
                    name,
                    weight,
                )
            )

    # --------------------------------------------------------
    # BANK CONTEXT
    # --------------------------------------------------------

    if analysis.initiated_by_user:

        if analysis.sms_code_request:
            score -= 15

        if analysis.bank_impersonation:
            score -= 10

    # --------------------------------------------------------
    # UNKNOWN CONTACT + SMS
    # --------------------------------------------------------

    if (
        analysis.unknown_caller
        and analysis.sms_code_request
    ):

        score += 20

    # --------------------------------------------------------
    # UNKNOWN CONTACT + BANK + SMS
    # --------------------------------------------------------

    if (
        analysis.unknown_caller
        and analysis.bank_impersonation
        and analysis.sms_code_request
    ):

        score += 15

    # --------------------------------------------------------
    # FAKE JOB + MONEY
    # --------------------------------------------------------

    if (
        analysis.fake_job
        and analysis.money_request
    ):

        score += 20

    # --------------------------------------------------------
    # FAKE PRIZE + MONEY
    # --------------------------------------------------------

    if (
        analysis.fake_prize
        and analysis.money_request
    ):

        score += 20

    # --------------------------------------------------------
    # RENTAL SCAM
    # --------------------------------------------------------

    if (
        analysis.rental_scam
        and analysis.advance_payment
        and analysis.no_inspection
    ):

        score += 20

    # --------------------------------------------------------
    # REMOTE SELLER + ADVANCE PAYMENT
    # --------------------------------------------------------

    if (
        analysis.remote_seller
        and analysis.advance_payment
    ):

        score += 10

    # --------------------------------------------------------
    # MONEY + PRESSURE
    # --------------------------------------------------------

    if (
        analysis.money_request
        and analysis.urgency_pressure
    ):

        score += 10

    # --------------------------------------------------------
    # LIMIT 0–100
    # --------------------------------------------------------

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    return score, factors


# ============================================================
# ACTION SAFETY
# ============================================================

def action_safety(
    analysis: GuardAnalysis,
    fraud_score: int,
) -> str:

    if analysis.regulated_or_illicit_document_offer:

        return (
            "🚫 НЕ СОВЕРШАЙТЕ ДЕЙСТВИЕ "
            "В ОБХОД ОФИЦИАЛЬНОЙ ПРОЦЕДУРЫ"
        )

    if analysis.harmful_or_unsafe_action:

        return "🚫 НЕ СОВЕРШАЙТЕ"

    if analysis.user_intent == "ACTION" and fraud_score >= 60:

        return "🚨 НЕМЕДЛЕННО ПРЕКРАТИТЕ"

    if fraud_score >= 80:

        return "🛑 НЕ ДЕЙСТВУЙТЕ"

    if fraud_score >= 60:

        return "⚠️ ОСТАНОВИТЕСЬ И ПРОВЕРЬТЕ"

    if fraud_score >= 30:

        return "🔎 ПРОВЕРЬТЕ ПЕРЕД ДЕЙСТВИЕМ"

    if analysis.user_intent == "CONSIDERATION":

        return "🔎 ПРОВЕРЬТЕ ПЕРЕД ДЕЙСТВИЕМ"

    return (
        "✅ МОЖНО ПРОДОЛЖАТЬ "
        "С ОБЫЧНОЙ ОСТОРОЖНОСТЬЮ"
    )


# ============================================================
# CONTEXT LABEL
# ============================================================

def context_label(
    analysis: GuardAnalysis,
) -> str:

    if analysis.initiated_by_user:

        return "👤 Контакт инициирован вами"

    return "📞 Контакт инициирован другой стороной"


# ============================================================
# INTENT LABEL
# ============================================================

def intent_label(
    analysis: GuardAnalysis,
) -> str:

    return INTENT_NAMES.get(
        analysis.user_intent,
        "Не удалось определить",
    )


# ============================================================
# FACTOR TEXT
# ============================================================

def format_factors(
    factors: list[tuple[str, int]],
) -> str:

    if not factors:

        return (
            "• Существенных факторов риска "
            "не обнаружено"
        )

    return "\n".join(
        f"• +{weight} — {FACTOR_NAMES[name]}"
        for name, weight in factors
    )