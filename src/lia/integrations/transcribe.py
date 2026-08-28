import httpx

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class TranscriptionError(Exception):
    """Error al transcribir audio con Groq Whisper."""


async def transcribe_audio(audio_bytes: bytes, api_key: str, model: str = "whisper-large-v3-turbo") -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                GROQ_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
                data={"model": model, "language": "es"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"No se pudo transcribir el audio: {exc}") from exc

    return response.json()["text"]
