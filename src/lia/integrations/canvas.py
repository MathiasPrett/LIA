import datetime as dt
from dataclasses import dataclass

import httpx


class CanvasError(Exception):
    """Error de red o de autenticación al hablar con la API de Canvas."""


@dataclass
class CanvasActivityItem:
    key: str  # dedup key: f"{kind}:{id}"
    kind: str  # "Announcement" | "Conversation" | "DiscussionTopic" | "Submission" | ...
    title: str
    course_name: str | None
    updated_at: dt.datetime
    html_url: str | None


@dataclass
class CanvasAssignment:
    name: str
    course_name: str | None
    due_at: dt.datetime | None
    html_url: str | None


def _make_client(base_url: str, access_token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )


async def fetch_courses(base_url: str, access_token: str) -> dict[int, str]:
    async with _make_client(base_url, access_token) as client:
        try:
            resp = await client.get(
                "/api/v1/courses", params={"enrollment_state": "active", "per_page": 100}
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CanvasError(f"No se pudo conectar a Canvas: {exc}") from exc

        return {c["id"]: c.get("name") or f"Curso {c['id']}" for c in resp.json()}


async def fetch_activity_stream(base_url: str, access_token: str) -> list[dict]:
    async with _make_client(base_url, access_token) as client:
        try:
            resp = await client.get(
                "/api/v1/users/self/activity_stream", params={"per_page": 50}
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CanvasError(f"No se pudo conectar a Canvas: {exc}") from exc

        return resp.json()


async def fetch_todo(base_url: str, access_token: str) -> list[dict]:
    async with _make_client(base_url, access_token) as client:
        try:
            resp = await client.get("/api/v1/users/self/todo", params={"per_page": 50})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CanvasError(f"No se pudo conectar a Canvas: {exc}") from exc

        return resp.json()


def _parse_activity_item(raw: dict, courses: dict[int, str]) -> CanvasActivityItem:
    course_id = raw.get("course_id")
    return CanvasActivityItem(
        key=f"{raw['type']}:{raw['id']}",
        kind=raw["type"],
        title=raw.get("title") or raw.get("message") or "(sin título)",
        course_name=courses.get(course_id) if course_id else None,
        updated_at=dt.datetime.fromisoformat(raw["updated_at"]),
        html_url=raw.get("html_url"),
    )


def _parse_todo_item(raw: dict, courses: dict[int, str]) -> CanvasAssignment | None:
    assignment = raw.get("assignment")
    if not assignment:
        return None

    course_id = assignment.get("course_id") or raw.get("course_id")
    due_at = assignment.get("due_at")
    return CanvasAssignment(
        name=assignment.get("name") or "(sin título)",
        course_name=courses.get(course_id) if course_id else None,
        due_at=dt.datetime.fromisoformat(due_at) if due_at else None,
        html_url=assignment.get("html_url"),
    )


async def fetch_activity_items(base_url: str, access_token: str) -> list[CanvasActivityItem]:
    courses = await fetch_courses(base_url, access_token)
    raw_items = await fetch_activity_stream(base_url, access_token)
    return [_parse_activity_item(raw, courses) for raw in raw_items]


async def fetch_pending_assignments(base_url: str, access_token: str) -> list[CanvasAssignment]:
    courses = await fetch_courses(base_url, access_token)
    raw_items = await fetch_todo(base_url, access_token)
    parsed = (_parse_todo_item(raw, courses) for raw in raw_items)
    return [a for a in parsed if a is not None]
