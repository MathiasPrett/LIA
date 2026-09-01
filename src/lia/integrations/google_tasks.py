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
        body["due"] = dt.datetime.combine(due, dt.time.min, tzinfo=dt.UTC).isoformat()

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
