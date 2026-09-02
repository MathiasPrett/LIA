import httpx
from google.genai.errors import APIError
from googleapiclient.errors import HttpError

from lia.bot.handlers import describe_error
from lia.integrations.google_calendar import CalendarNotConnected


class _FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "Not Found"


def _http_error(status: int) -> HttpError:
    return HttpError(_FakeResp(status), b'{"error": {"message": "boom"}}')


def _gemini_error(code: int, message: str, status: str) -> APIError:
    return APIError(code, {"error": {"code": code, "message": message, "status": status}})


# --- Gemini (lo que más se vio en producción) ---


def test_gemini_503_explains_it_is_google_side_and_shows_code_and_message():
    mensaje = describe_error(
        _gemini_error(503, "This model is currently experiencing high demand.", "UNAVAILABLE")
    )
    assert "saturado" in mensaje
    assert "no de tu cuenta ni del plan" in mensaje
    assert "Gemini 503 UNAVAILABLE" in mensaje  # el código pedido
    assert "high demand" in mensaje  # el mensaje real de Google


def test_gemini_429_mentions_quota_and_shows_the_code():
    mensaje = describe_error(_gemini_error(429, "Quota exceeded.", "RESOURCE_EXHAUSTED"))
    assert "cuota" in mensaje
    assert "Gemini 429" in mensaje


def test_gemini_429_for_depleted_credits_says_to_top_up_instead_of_quota():
    # Caso real: se agotó el prepago y todo fallaba con el mismo texto genérico.
    mensaje = describe_error(
        _gemini_error(
            429,
            "Your prepayment credits are depleted. Please go to AI Studio at "
            "https://ai.studio/projects to manage your project and billing.",
            "RESOURCE_EXHAUSTED",
        )
    )
    assert "crédito prepagado" in mensaje
    assert "recargues" in mensaje
    assert "Gemini 429" in mensaje


# --- Red / DNS: el otro fallo que el mensaje genérico ocultaba ---


def test_dns_failure_is_reported_as_network_not_as_gemini():
    mensaje = describe_error(httpx.ConnectError("[Errno -3] Temporary failure in name resolution"))
    assert "Raspberry" in mensaje
    assert "no es Gemini" in mensaje
    assert "ConnectError" in mensaje
    assert "name resolution" in mensaje


# --- Google Calendar / Tasks ---


def test_404_tells_the_user_the_event_is_gone_and_shows_the_code():
    mensaje = describe_error(_http_error(404))
    assert "ya no está en el calendario" in mensaje
    assert "Google API 404" in mensaje


def test_403_mentions_read_only_or_missing_api():
    assert "solo lectura" in describe_error(_http_error(403))


def test_401_mentions_expired_access():
    assert "expirado" in describe_error(_http_error(401))


def test_calendar_not_connected_passes_its_own_message_through():
    exc = CalendarNotConnected("No se encontró token.json. Ejecuta el script de OAuth.")
    assert describe_error(exc) == str(exc)


# --- Fallback ---


def test_unknown_error_still_shows_type_and_message():
    mensaje = describe_error(ValueError("cualquier cosa"))
    assert "ValueError" in mensaje
    assert "cualquier cosa" in mensaje


def test_very_long_detail_is_truncated_so_telegram_does_not_choke():
    mensaje = describe_error(ValueError("x" * 5000))
    assert "…" in mensaje
    assert len(mensaje) < 700
