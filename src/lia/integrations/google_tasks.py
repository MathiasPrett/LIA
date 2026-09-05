import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from googleapiclient.discovery import Resource, build

from lia.integrations.google_calendar import load_credentials


@dataclass
class TaskItem:
    id: str
    title: str
    notes: str | None
    due: dt.date | None


def build_tasks_service(creds) -> Resource:
    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def _parse_task(raw: dict) -> TaskItem:
    due = dt.datetime.fromisoformat(raw["due"]).date() if raw.get("due") else None
    return TaskItem(id=raw["id"], title=raw.get("title", "(sin título)"), notes=raw.get("notes"), due=due)


def create_task(
    service: Resource,
    title: str,
    notes: str | None = None,
    due: dt.date | None = None,
) -> TaskItem:
    body = {"title": title}
    if notes:
        body["notes"] = notes
    if due:
        # La API de Tasks solo guarda la fecha: descarta cualquier hora que se le mande.
        # Se emite exactamente el formato que Google devuelve ('...T00:00:00.000Z') en vez
        # del equivalente con offset '+00:00': ambos son RFC 3339 válidos, pero usar el que
        # la propia API produce evita depender de qué tan tolerante sea su parser.
        body["due"] = f"{due.isoformat()}T00:00:00.000Z"

    created = service.tasks().insert(tasklist="@default", body=body).execute()
    return _parse_task(created)


def insert_task(
    token_path: Path,
    title: str,
    notes: str | None = None,
    due: dt.date | None = None,
) -> TaskItem:
    """Atajo síncrono equivalente a `insert_event` pero para Google Tasks."""
    creds = load_credentials(token_path)
    service = build_tasks_service(creds)
    return create_task(service, title, notes, due)


def list_tasks(
    service: Resource,
    show_completed: bool = False,
    max_results: int = 100,
) -> list[TaskItem]:
    """Lista las tareas de la lista por defecto.

    A propósito NO se usan los filtros `dueMin`/`dueMax` de la API: dejan fuera las
    tareas sin fecha, que son varias de las pendientes reales, y devolverían una
    lista incompleta. Se traen todas y el filtrado por fecha queda a la vista.
    """
    response = (
        service.tasks()
        .list(tasklist="@default", showCompleted=show_completed, maxResults=max_results)
        .execute()
    )
    return [_parse_task(item) for item in response.get("items", [])]


def fetch_tasks(token_path: Path, show_completed: bool = False) -> list[TaskItem]:
    """Atajo síncrono equivalente a `fetch_events` pero para Google Tasks."""
    creds = load_credentials(token_path)
    service = build_tasks_service(creds)
    return list_tasks(service, show_completed)
