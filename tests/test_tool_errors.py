from googleapiclient.errors import HttpError

from lia.bot.handlers import describe_tool_error
from lia.integrations.google_calendar import CalendarNotConnected


class _FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "Error"


def _http_error(status: int) -> HttpError:
    return HttpError(_FakeResp(status), b'{"error": {"message": "boom"}}')


def test_404_tells_the_user_the_event_is_gone_and_to_ask_again():
    mensaje = describe_tool_error(_http_error(404))
    assert "ya no está en el calendario" in mensaje
    assert "de nuevo" in mensaje


def test_403_mentions_read_only_or_missing_api():
    mensaje = describe_tool_error(_http_error(403))
    assert "solo lectura" in mensaje


def test_401_mentions_expired_access():
    assert "expirado" in describe_tool_error(_http_error(401))


def test_calendar_not_connected_passes_its_own_message_through():
    exc = CalendarNotConnected("No se encontró token.json. Ejecuta el script de OAuth.")
    assert describe_tool_error(exc) == str(exc)


def test_unknown_error_falls_back_to_generic_message():
    assert describe_tool_error(ValueError("cualquier cosa")) == (
        "hubo un error inesperado al aplicar el cambio."
    )
