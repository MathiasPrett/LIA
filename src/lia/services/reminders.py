import datetime as dt

from sqlalchemy.orm import Session

from lia.config import Settings
from lia.db import Reminder, SeenItem
from lia.integrations.google_calendar import CalendarEvent

_SOURCE = "event_reminder"


def is_important(event: CalendarEvent, settings: Settings) -> bool:
    """Heurística de "esto merece un aviso previo": no aplica a eventos de todo
    el día porque no tienen una hora de inicio concreta contra la cual avisar."""
    if event.all_day:
        return False

    if event.calendar_id in settings.important_calendar_id_list:
        return True

    duration_minutes = (event.end - event.start).total_seconds() / 60
    if duration_minutes >= settings.important_min_duration_minutes:
        return True

    if event.attendees_count >= settings.important_min_attendees:
        return True

    title = event.summary.lower()
    return any(keyword in title for keyword in settings.important_keyword_list)


def format_reminder(event: CalendarEvent, lead_minutes: int) -> str:
    start_str = event.start.strftime("%H:%M")
    text = f"⏰ En {lead_minutes} minutos: *{event.summary}* a las {start_str}"
    if event.location:
        text += f"\n📍 {event.location}"
    return text


def find_events_needing_reminder(
    session: Session, events: list[CalendarEvent], settings: Settings
) -> list[CalendarEvent]:
    """Filtra los eventos importantes que todavía no recibieron su recordatorio,
    y los marca como avisados. Reutiliza `seen_items` con `source="event_reminder"`,
    igual que el dedup de Canvas, para nunca avisar dos veces del mismo evento."""
    to_remind = []
    for event in events:
        if not is_important(event, settings):
            continue

        already_sent = (
            session.query(SeenItem).filter_by(source=_SOURCE, external_id=event.id).first()
        )
        if already_sent:
            continue

        session.add(SeenItem(source=_SOURCE, external_id=event.id, content_hash=event.calendar_id))
        to_remind.append(event)

    session.commit()
    return to_remind


# --- Recordatorios ad-hoc (pedidos por lenguaje natural, tabla `reminders`) ---


def format_adhoc_reminder(reminder: Reminder) -> str:
    return f"⏰ Recordatorio: {reminder.text}"


def find_due_reminders(session: Session, now: dt.datetime) -> list[Reminder]:
    """Recordatorios pendientes cuya hora ya llegó. Los marca como enviados
    para no repetirlos en el próximo poll."""
    due = (
        session.query(Reminder)
        .filter(Reminder.status == "pending", Reminder.fire_at <= now)
        .all()
    )
    for reminder in due:
        reminder.status = "sent"
    session.commit()
    return due
