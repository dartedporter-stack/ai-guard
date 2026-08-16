from pydantic import BaseModel


class GuardAnalysis(BaseModel):
    """
    Структурированный результат анализа Gemini.
    """

    # ========================================================
    # CONTEXT
    # ========================================================

    category: str

    initiated_by_user: bool
    unknown_caller: bool

    # ========================================================
    # INTENT
    # ========================================================

    user_intent: str

    # ========================================================
    # GENERAL FRAUD SIGNALS
    # ========================================================

    sms_code_request: bool
    money_request: bool
    personal_data_request: bool
    suspicious_link: bool
    urgency_pressure: bool
    bank_impersonation: bool
    fake_support: bool
    fake_prize: bool
    guaranteed_profit: bool
    suspicious_deal: bool

    # ========================================================
    # SPECIALIZED SCHEMES
    # ========================================================

    fake_job: bool
    rental_scam: bool
    no_inspection: bool
    remote_seller: bool
    advance_payment: bool

    # ========================================================
    # ACTION SAFETY
    # ========================================================

    regulated_or_illicit_document_offer: bool
    harmful_or_unsafe_action: bool

    # ========================================================
    # HUMAN-READABLE RESULT
    # ========================================================

    red_flags: list[str]
    actions: list[str]
    conclusion: str