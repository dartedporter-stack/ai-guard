import base64
import io
import wave

import requests

from config import TEXT_MODEL
from guard.analyzer import get_credentials


PCM_SAMPLE_RATE = 16_000
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH = 2
MAX_AUDIO_SECONDS = 60
MIN_PCM_BYTES = PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH // 10

TRANSCRIPTION_PROMPT = """
Точно расшифруй речь из аудиозаписи.

Правила:
- верни только произнесённый текст без комментариев;
- не придумывай отсутствующие слова;
- сохрани язык речи (русский или казахский);
- если речь неразборчива, пометь только неразборчивый фрагмент как [неразборчиво].
""".strip()


def pcm16_to_wav(
    audio_bytes: bytes,
    sample_rate: int = PCM_SAMPLE_RATE,
) -> bytes:
    """Wrap mono PCM16 bytes in a WAV container for Gemini."""
    if not 8_000 <= sample_rate <= 96_000:
        raise ValueError("Неподдерживаемая частота аудио")

    min_pcm_bytes = sample_rate * PCM_SAMPLE_WIDTH // 10
    max_pcm_bytes = (
        sample_rate
        * PCM_CHANNELS
        * PCM_SAMPLE_WIDTH
        * MAX_AUDIO_SECONDS
    )

    if len(audio_bytes) < min_pcm_bytes:
        raise ValueError("Запись слишком короткая")

    if len(audio_bytes) > max_pcm_bytes:
        raise ValueError("Запись не должна быть длиннее 60 секунд")

    if len(audio_bytes) % PCM_SAMPLE_WIDTH:
        raise ValueError("Аудиозапись повреждена")

    output = io.BytesIO()

    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(PCM_CHANNELS)
        wav_file.setsampwidth(PCM_SAMPLE_WIDTH)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_bytes)

    return output.getvalue()


def transcribe_pcm16(
    audio_bytes: bytes,
    sample_rate: int = PCM_SAMPLE_RATE,
) -> str:
    """Transcribe a short PCM16 recording without saving it to disk."""
    wav_bytes = pcm16_to_wav(audio_bytes, sample_rate)
    credentials = get_credentials()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{TEXT_MODEL}:generateContent"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": TRANSCRIPTION_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": "audio/wav",
                            "data": base64.b64encode(wav_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ]
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=90,
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini не смог расшифровать аудио ({response.status_code})"
        )

    try:
        transcript = (
            response.json()["candidates"][0]["content"]["parts"][0]["text"]
        ).strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise RuntimeError("Gemini вернул некорректную расшифровку") from error

    if not transcript:
        raise RuntimeError("В аудиозаписи не удалось распознать речь")

    return transcript
