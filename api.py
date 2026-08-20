from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from starlette.concurrency import run_in_threadpool

from guard.analyzer import analyze_text
from guard.audio import (
    MAX_AUDIO_SECONDS,
    PCM_CHANNELS,
    PCM_SAMPLE_WIDTH,
    transcribe_pcm16,
)
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
    allow_headers=["Content-Type", "Authorization"],
)


def bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    scheme, _, token = (authorization or "").partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется вход в аккаунт",
        )

    try:
        history_store.verify_user(token)
    except PermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return token


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
    transcript: str | None = None


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


def analyze_and_save(
    text: str,
    access_token: str,
    transcript: str | None = None,
) -> AnalyzeResponse:
    analysis = analyze_text(text)
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
        transcript=transcript,
    )

    try:
        history_store.save(
            access_token=access_token,
            input_text=text,
            risk_score=result.risk_score,
            risk_level=result.risk_level,
            category=result.category,
            red_flags=result.red_flags,
            actions=result.actions,
            conclusion=result.conclusion,
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return result


@app.post(
    "/analyze",
    response_model=AnalyzeResponse,
)
def analyze(
    request: AnalyzeRequest,
    access_token: Annotated[str, Depends(bearer_token)],
) -> AnalyzeResponse:
    return analyze_and_save(request.text, access_token)


@app.post(
    "/analyze/audio",
    response_model=AnalyzeResponse,
)
async def analyze_audio(
    request: Request,
    access_token: Annotated[str, Depends(bearer_token)],
) -> AnalyzeResponse:
    content_type = request.headers.get("content-type", "")

    if not content_type.lower().startswith("audio/pcm"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Ожидается моно-аудио PCM16",
        )

    sample_rate = 16_000

    for parameter in content_type.split(";")[1:]:
        name, separator, value = parameter.strip().partition("=")

        if separator and name.lower() == "rate":
            try:
                sample_rate = int(value)
            except ValueError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Некорректная частота аудио",
                ) from error

    if not 8_000 <= sample_rate <= 96_000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неподдерживаемая частота аудио",
        )

    max_content_length = (
        sample_rate
        * PCM_CHANNELS
        * PCM_SAMPLE_WIDTH
        * MAX_AUDIO_SECONDS
    )
    content_length = request.headers.get("content-length")

    if content_length:
        try:
            if int(content_length) > max_content_length:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Запись не должна быть длиннее 60 секунд",
                )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некорректный размер аудио",
            ) from error

    audio_bytes = await request.body()

    try:
        transcript = await run_in_threadpool(
            transcribe_pcm16,
            audio_bytes,
            sample_rate,
        )
        return await run_in_threadpool(
            analyze_and_save,
            transcript,
            access_token,
            transcript,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


@app.get(
    "/history",
    response_model=list[HistoryRecord],
)
def history(
    access_token: Annotated[str, Depends(bearer_token)],
) -> list[HistoryRecord]:
    try:
        records = history_store.list_recent(access_token=access_token)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return [HistoryRecord.model_validate(record) for record in records]


@app.get(
    "/news",
    response_model=list[NewsArticle],
)
def news() -> list[NewsArticle]:
    return [
        NewsArticle.model_validate(article)
        for article in load_news()
    ]
