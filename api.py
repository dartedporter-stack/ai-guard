import hashlib
import hmac
import threading
import time
import uuid
from dataclasses import dataclass
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
from guard.live_risk import analyze_live_transcript
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
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Protection-Session",
    ],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Lightweight readiness check for the mobile app and cloud host."""
    return {"status": "ok"}


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


class ProtectionStartResponse(BaseModel):
    session_id: str


class ProtectionSessionRequest(BaseModel):
    session_id: str


@dataclass
class ProtectionSession:
    owner_digest: str
    transcript: str = ""
    updated_at: float = 0.0


protection_sessions: dict[str, ProtectionSession] = {}
protection_sessions_lock = threading.Lock()
PROTECTION_SESSION_TTL_SECONDS = 15 * 60


def build_analysis_response(
    analysis,
    transcript: str | None = None,
) -> AnalyzeResponse:
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
        transcript=transcript,
    )


def save_analysis_result(
    text: str,
    access_token: str,
    result: AnalyzeResponse,
) -> None:
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


def analyze_and_save(
    text: str,
    access_token: str,
    transcript: str | None = None,
) -> AnalyzeResponse:
    analysis = analyze_text(text)
    result = build_analysis_response(analysis, transcript)
    save_analysis_result(text, access_token, result)

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


def token_digest(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def clean_expired_protection_sessions(now: float) -> None:
    expired = [
        session_id
        for session_id, session in protection_sessions.items()
        if now - session.updated_at > PROTECTION_SESSION_TTL_SECONDS
    ]

    for session_id in expired:
        protection_sessions.pop(session_id, None)


def get_protection_session(
    session_id: str,
    access_token: str,
) -> ProtectionSession:
    session = protection_sessions.get(session_id)

    if session is None or not hmac.compare_digest(
        session.owner_digest,
        token_digest(access_token),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сессия защиты не найдена",
        )

    return session


def pcm_sample_rate(content_type: str) -> int:
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

    return sample_rate


async def read_pcm_audio(request: Request) -> tuple[bytes, int]:
    sample_rate = pcm_sample_rate(request.headers.get("content-type", ""))
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

    if len(audio_bytes) > max_content_length:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Запись не должна быть длиннее 60 секунд",
        )

    return audio_bytes, sample_rate


@app.post(
    "/analyze/audio",
    response_model=AnalyzeResponse,
)
async def analyze_audio(
    request: Request,
    access_token: Annotated[str, Depends(bearer_token)],
) -> AnalyzeResponse:
    audio_bytes, sample_rate = await read_pcm_audio(request)

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


@app.post(
    "/protect/start",
    response_model=ProtectionStartResponse,
)
def start_protection(
    access_token: Annotated[str, Depends(bearer_token)],
) -> ProtectionStartResponse:
    now = time.monotonic()
    session_id = uuid.uuid4().hex

    with protection_sessions_lock:
        clean_expired_protection_sessions(now)
        protection_sessions[session_id] = ProtectionSession(
            owner_digest=token_digest(access_token),
            updated_at=now,
        )

    return ProtectionStartResponse(session_id=session_id)


@app.post(
    "/protect/audio",
    response_model=AnalyzeResponse,
)
async def protect_audio(
    request: Request,
    access_token: Annotated[str, Depends(bearer_token)],
    session_id: Annotated[
        str | None,
        Header(alias="X-Protection-Session"),
    ] = None,
) -> AnalyzeResponse:
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не указана сессия защиты",
        )

    with protection_sessions_lock:
        get_protection_session(session_id, access_token)

    audio_bytes, sample_rate = await read_pcm_audio(request)

    try:
        transcript_part = await run_in_threadpool(
            transcribe_pcm16,
            audio_bytes,
            sample_rate,
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

    with protection_sessions_lock:
        session = get_protection_session(session_id, access_token)
        session.transcript = (
            f"{session.transcript} {transcript_part}".strip()[-6_000:]
        )
        session.updated_at = time.monotonic()
        transcript = session.transcript

    live_analysis = analyze_live_transcript(transcript)
    return build_analysis_response(live_analysis, transcript)


@app.post(
    "/protect/stop",
    response_model=AnalyzeResponse,
)
async def stop_protection(
    request: ProtectionSessionRequest,
    access_token: Annotated[str, Depends(bearer_token)],
) -> AnalyzeResponse:
    with protection_sessions_lock:
        session = get_protection_session(request.session_id, access_token)
        transcript = session.transcript

    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Речь не была распознана",
        )

    result = await run_in_threadpool(
        analyze_and_save,
        transcript,
        access_token,
        transcript,
    )

    with protection_sessions_lock:
        protection_sessions.pop(request.session_id, None)

    return result


@app.post(
    "/protect/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cancel_protection(
    request: ProtectionSessionRequest,
    access_token: Annotated[str, Depends(bearer_token)],
) -> None:
    with protection_sessions_lock:
        get_protection_session(request.session_id, access_token)
        protection_sessions.pop(request.session_id, None)


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
