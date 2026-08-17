from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from guard.analyzer import analyze_text
from guard.risk_engine import (
    FACTOR_NAMES,
    action_safety,
    calculate_fraud_risk,
    context_label,
    intent_label,
    risk_level,
)


app = FastAPI(
    title="AI GUARD API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
    ),
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class AnalyzeRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()

        if not text:
            raise ValueError("Текст не должен быть пустым")

        return text


class RiskFactor(BaseModel):
    code: str
    name: str
    weight: int


class AnalyzeResponse(BaseModel):
    risk_score: int
    risk_level: str
    action_safety: str
    category: str
    intent: str
    context: str
    factors: list[RiskFactor]
    red_flags: list[str]
    actions: list[str]
    conclusion: str


@app.post(
    "/analyze",
    response_model=AnalyzeResponse,
)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    analysis = analyze_text(request.text)
    score, calculated_factors = calculate_fraud_risk(analysis)

    factors = [
        RiskFactor(
            code=code,
            name=FACTOR_NAMES[code],
            weight=weight,
        )
        for code, weight in calculated_factors
    ]

    return AnalyzeResponse(
        risk_score=score,
        risk_level=risk_level(score),
        action_safety=action_safety(analysis, score),
        category=analysis.category,
        intent=intent_label(analysis),
        context=context_label(analysis),
        factors=factors,
        red_flags=analysis.red_flags,
        actions=analysis.actions,
        conclusion=analysis.conclusion,
    )
