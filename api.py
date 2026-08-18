from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from guard.analyzer import analyze_text
from guard.history_store import HistoryStore
from guard.news_store import load_news
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

history_store = HistoryStore()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$"
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
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


class HistoryRecord(BaseModel):
    id: int
    created_at: str
    input_text: str
    risk_score: int
    risk_level: str
    category: str
    red_flags: list[str]
    actions: list[str]
    conclusion: str


class NewsArticle(BaseModel):
    id: int
    title: str
    summary: str
    published_at: str
    category: str
    source_name: str
    source_url: str | None
    image_url: str | None
    is_demo: bool
    content: str


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

    result = AnalyzeResponse(
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

    history_store.save(
        input_text=request.text,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        category=result.category,
        red_flags=result.red_flags,
        actions=result.actions,
        conclusion=result.conclusion,
    )

    return result


@app.get(
    "/history",
    response_model=list[HistoryRecord],
)
def history() -> list[HistoryRecord]:
    return [
        HistoryRecord.model_validate(record)
        for record in history_store.list_recent()
    ]


@app.get(
    "/news",
    response_model=list[NewsArticle],
)
def news() -> list[NewsArticle]:
    return [
        NewsArticle.model_validate(article)
        for article in load_news()
    ]
