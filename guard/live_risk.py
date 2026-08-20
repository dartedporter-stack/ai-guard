import re

from guard.models import GuardAnalysis
from guard.risk_engine import FACTOR_NAMES, calculate_fraud_risk


SIGNAL_PATTERNS = {
    "sms_code_request": (
        r"\b(?:sms|смс|otp)\b.{0,35}\b(?:код|code)\b|"
        r"\bкод\b.{0,35}\b(?:sms|смс|подтвержден)|"
        r"бір реттік код|растау коды"
    ),
    "money_request": (
        r"перевед|отправ.{0,20}(?:деньг|средств)|оплат|предоплат|комисси|"
        r"ақша.{0,20}аудар|төлем|алдын ала төле"
    ),
    "personal_data_request": (
        r"номер.{0,15}карт|cvv|cvc|pin|пин.?код|парол|паспорт|\bиин\b|\bжсн\b|"
        r"карта нөмір|құпия сөз"
    ),
    "suspicious_link": r"https?://|ссылк|перейдите.{0,20}сайт|сілтем",
    "urgency_pressure": (
        r"срочно|немедленно|прямо сейчас|не кладите трубку|тороп|"
        r"шұғыл|дереу|дәл қазір|телефонды қойма"
    ),
    "bank_impersonation": (
        r"из банка|сотрудник.{0,15}банк|служб[аы].{0,15}безопасност|"
        r"банк қызметкер|банктің қауіпсіздік"
    ),
    "fake_support": (
        r"техподдержк|служб[аы].{0,15}поддержк|қолдау қызмет"
    ),
    "fake_prize": r"выиграл|выигрыш|лотере|приз|ұтыс|сыйлық ұт",
    "guaranteed_profit": (
        r"гарантирован.{0,20}прибыл|без риска|кепілдендірілген табыс"
    ),
    "suspicious_deal": r"слишком выгод|только сегодня|арзан баға",
    "advance_payment": r"предоплат|аванс|алдын ала төле",
}


def analyze_live_transcript(transcript: str) -> GuardAnalysis:
    """Fast deterministic warning pass over an AI-generated transcript."""
    normalized = " ".join(transcript.lower().split())
    signals = {
        name: bool(re.search(pattern, normalized, flags=re.IGNORECASE))
        for name, pattern in SIGNAL_PATTERNS.items()
    }
    red_flags = [
        FACTOR_NAMES[name]
        for name, active in signals.items()
        if active and name in FACTOR_NAMES
    ]
    category = "Общий разговор"

    if signals["bank_impersonation"] or signals["sms_code_request"]:
        category = "Телефонное мошенничество"
    elif signals["money_request"] or signals["advance_payment"]:
        category = "Подозрительный денежный запрос"
    elif signals["fake_prize"]:
        category = "Подозрительный выигрыш"

    provisional = GuardAnalysis(
        category=category,
        initiated_by_user=False,
        unknown_caller=True,
        user_intent="OBSERVATION",
        sms_code_request=signals["sms_code_request"],
        money_request=signals["money_request"],
        personal_data_request=signals["personal_data_request"],
        suspicious_link=signals["suspicious_link"],
        urgency_pressure=signals["urgency_pressure"],
        bank_impersonation=signals["bank_impersonation"],
        fake_support=signals["fake_support"],
        fake_prize=signals["fake_prize"],
        guaranteed_profit=signals["guaranteed_profit"],
        suspicious_deal=signals["suspicious_deal"],
        fake_job=False,
        rental_scam=False,
        no_inspection=False,
        remote_seller=False,
        advance_payment=signals["advance_payment"],
        regulated_or_illicit_document_offer=False,
        harmful_or_unsafe_action=False,
        red_flags=red_flags,
        actions=[],
        conclusion="",
    )
    score, _ = calculate_fraud_risk(provisional)

    if score >= 60:
        actions = [
            "Не называйте коды, пароли и данные карты.",
            "Не переводите деньги и завершите подозрительный разговор.",
        ]
        conclusion = (
            "В разговоре одновременно обнаружены сильные признаки "
            "возможного мошенничества."
        )
    elif score >= 30:
        actions = [
            "Не торопитесь и перепроверьте личность собеседника.",
            "Перезвоните организации по официальному номеру.",
        ]
        conclusion = "Обнаружены признаки, которые требуют проверки."
    else:
        actions = ["Продолжайте разговор с обычной осторожностью."]
        conclusion = "Сильных признаков мошенничества пока не обнаружено."

    return provisional.model_copy(
        update={"actions": actions, "conclusion": conclusion}
    )
