import hashlib

from sqlalchemy.orm import Session

from lia.db import SeenItem
from lia.integrations.canvas import CanvasActivityItem

_KIND_LABELS = {
    "Announcement": "📢 Aviso nuevo",
    "Conversation": "✉️ Mensaje nuevo",
    "DiscussionTopic": "💬 Discusión nueva",
    "Submission": "✅ Calificación nueva",
}


def _content_hash(item: CanvasActivityItem) -> str:
    return hashlib.sha256(item.title.encode()).hexdigest()[:16]


def format_activity_notification(item: CanvasActivityItem) -> str:
    label = _KIND_LABELS.get(item.kind, "🔔 Novedad en Canvas")
    course = f" — {item.course_name}" if item.course_name else ""
    text = f"{label}{course}\n{item.title}"
    if item.html_url:
        text += f"\n{item.html_url}"
    return text


def find_new_items(session: Session, items: list[CanvasActivityItem]) -> list[CanvasActivityItem]:
    """Filtra los ítems que no están en `seen_items` y los registra como vistos.

    En la primera corrida (sin historial de Canvas todavía) marca todo como
    visto pero no devuelve nada, para no bombardear al usuario con meses de
    actividad vieja apenas se conecta la integración.
    """
    is_first_run = session.query(SeenItem).filter_by(source="canvas").first() is None

    new_items = []
    for item in items:
        already_seen = (
            session.query(SeenItem).filter_by(source="canvas", external_id=item.key).first()
        )
        if already_seen:
            continue

        session.add(SeenItem(source="canvas", external_id=item.key, content_hash=_content_hash(item)))
        if not is_first_run:
            new_items.append(item)

    session.commit()
    return new_items
