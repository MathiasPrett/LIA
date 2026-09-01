import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]

# Categorías inventadas para colorear eventos automáticamente. IDs según la paleta
# fija de Google Calendar (Colors.get(), siempre la misma para todas las cuentas):
# 1 Lavender, 2 Sage, 3 Grape, 4 Flamingo, 5 Banana, 6 Tangerine, 7 Peacock,
# 8 Graphite, 9 Blueberry, 10 Basil, 11 Tomato.
CATEGORY_COLORS: dict[str, str] = {
    "academico": "7",  # Peacock — clases, certámenes, entregas
    "personal": "2",  # Sage — trámites, tiempo propio
    "social": "6",  # Tangerine — juntas, salidas, eventos con otras personas
    "salud": "11",  # Tomato — citas médicas, deporte
    "viajes": "9",  # Blueberry — vuelos, viajes
}


def color_id_for_category(categoria: str | None) -> str | None:
    if categoria is None:
        return None
    return CATEGORY_COLORS.get(categoria)


class CalendarNotConnected(Exception):
    """No existe token.json todavía: falta correr el flujo de OAuth una vez."""


@dataclass
class CalendarEvent:
    id: str
    calendar_id: str
    summary: str
    start: dt.datetime | dt.date
    end: dt.datetime | dt.date
    all_day: bool
    location: str | None = None
    description: str | None = None
    attendees_count: int = 0


def load_credentials(token_path: Path) -> Credentials:
    if not token_path.exists():
        raise CalendarNotConnected(
            f"No se encontró {token_path}. Ejecuta `uv run python scripts/google_auth.py` primero."
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise CalendarNotConnected(
                "El acceso a Google Calendar expiró o fue revocado. Ejecuta "
                "`uv run python scripts/google_auth.py` de nuevo para reconectarlo."
            ) from exc
        try:
            token_path.write_text(creds.to_json())
        except OSError:
            # El token ya está refrescado en memoria y sirve igual; si el archivo está
            # montado de solo lectura (como en Docker, a propósito), simplemente no
            # queda cacheado en disco y se vuelve a refrescar en la próxima llamada.
            logger.warning("No se pudo guardar el token refrescado en %s (¿solo lectura?)", token_path)

    return creds


def build_service(creds: Credentials) -> Resource:
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_event(raw: dict, calendar_id: str) -> CalendarEvent:
    start_raw = raw["start"]
    end_raw = raw["end"]
    all_day = "date" in start_raw

    if all_day:
        start = dt.date.fromisoformat(start_raw["date"])
        end = dt.date.fromisoformat(end_raw["date"])
    else:
        start = dt.datetime.fromisoformat(start_raw["dateTime"])
        end = dt.datetime.fromisoformat(end_raw["dateTime"])

    return CalendarEvent(
        id=raw["id"],
        calendar_id=calendar_id,
        summary=raw.get("summary", "(sin título)"),
        start=start,
        end=end,
        all_day=all_day,
        location=raw.get("location"),
        description=raw.get("description"),
        attendees_count=len(raw.get("attendees") or []),
    )


def list_events(
    service: Resource,
    calendar_id: str,
    time_min: dt.datetime,
    time_max: dt.datetime,
    timezone: str,
) -> list[CalendarEvent]:
    tz = ZoneInfo(timezone)
    if time_min.tzinfo is None:
        time_min = time_min.replace(tzinfo=tz)
    if time_max.tzinfo is None:
        time_max = time_max.replace(tzinfo=tz)

    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return [_parse_event(item, calendar_id) for item in response.get("items", [])]


def _sort_key(event: CalendarEvent) -> dt.datetime:
    if isinstance(event.start, dt.datetime):
        return event.start
    return dt.datetime.combine(event.start, dt.time.min, tzinfo=dt.timezone.utc)


def create_event(
    service: Resource,
    calendar_id: str,
    summary: str,
    start: dt.datetime,
    end: dt.datetime,
    timezone: str,
    location: str | None = None,
    description: str | None = None,
    color_id: str | None = None,
) -> CalendarEvent:
    body = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if color_id:
        body["colorId"] = color_id

    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return _parse_event(created, calendar_id)


def insert_event(
    token_path: Path,
    calendar_id: str,
    summary: str,
    start: dt.datetime,
    end: dt.datetime,
    timezone: str,
    location: str | None = None,
    description: str | None = None,
    color_id: str | None = None,
) -> CalendarEvent:
    """Atajo síncrono equivalente a `fetch_events` pero para crear un evento."""
    creds = load_credentials(token_path)
    service = build_service(creds)
    return create_event(service, calendar_id, summary, start, end, timezone, location, description, color_id)


def create_birthday_event(service: Resource, summary: str, date: dt.date) -> CalendarEvent:
    """Crea un evento de tipo 'birthday': todo el día, se repite cada año, siempre en
    el calendario 'primary' (restricción de la API de Google, no se puede elegir otro)."""
    end_date = date + dt.timedelta(days=1)
    recurrence = (
        "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1"
        if date.month == 2 and date.day == 29
        else "RRULE:FREQ=YEARLY"
    )
    body = {
        "summary": summary,
        "eventType": "birthday",
        "start": {"date": date.isoformat()},
        "end": {"date": end_date.isoformat()},
        "recurrence": [recurrence],
        "visibility": "private",
        "transparency": "transparent",
        "birthdayProperties": {"type": "birthday"},
    }
    created = service.events().insert(calendarId="primary", body=body).execute()
    return _parse_event(created, "primary")


def insert_birthday(token_path: Path, summary: str, date: dt.date) -> CalendarEvent:
    """Atajo síncrono equivalente a `insert_event` pero para un cumpleaños."""
    creds = load_credentials(token_path)
    service = build_service(creds)
    return create_birthday_event(service, summary, date)


def fetch_events(
    token_path: Path,
    time_min: dt.datetime,
    time_max: dt.datetime,
    timezone: str,
    calendar_ids: list[str] | None = None,
) -> list[CalendarEvent]:
    """Atajo síncrono: credenciales + servicio + listado en uno o más calendarios.

    Junta y ordena cronológicamente los eventos de todos los `calendar_ids`
    (por ejemplo el calendario personal y uno compartido). Pensado para
    llamarse vía `asyncio.to_thread` desde el bot (el cliente de Google es
    bloqueante).
    """
    creds = load_credentials(token_path)
    service = build_service(creds)

    events: list[CalendarEvent] = []
    for calendar_id in calendar_ids or ["primary"]:
        events.extend(list_events(service, calendar_id, time_min, time_max, timezone))

    return sorted(events, key=_sort_key)
