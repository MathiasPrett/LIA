import datetime as dt
from zoneinfo import ZoneInfo

from lia.integrations.canvas import CanvasAssignment
from lia.integrations.google_calendar import CalendarEvent

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _format_event_line(event: CalendarEvent) -> str:
    if event.all_day:
        line = f"• Todo el día — {event.summary}"
    else:
        start_h = event.start.strftime("%H:%M")
        end_h = event.end.strftime("%H:%M")
        line = f"• {start_h}–{end_h} — {event.summary}"

    if event.location:
        line += f" ({event.location})"

    return line


def _format_assignment_line(assignment: CanvasAssignment, tz: ZoneInfo) -> str:
    line = f"📚 {assignment.name}"
    if assignment.course_name:
        line += f" ({assignment.course_name})"
    if assignment.due_at:
        line += f" — vence {assignment.due_at.astimezone(tz).strftime('%H:%M')}"
    return line


def format_daily_briefing(
    events: list[CalendarEvent],
    date: dt.date,
    pending_assignments: list[CanvasAssignment] | None = None,
    timezone: str = "UTC",
) -> str:
    dia = _DIAS[date.weekday()]
    header = f"Buenos días. Hoy es {dia} {date.day} de {_MESES[date.month - 1]}."

    text = header + (
        "\n\nAgenda de hoy:\n" + "\n".join(_format_event_line(e) for e in events)
        if events
        else "\n\nNo tienes eventos agendados para hoy."
    )

    tz = ZoneInfo(timezone)
    due_today = [
        a
        for a in (pending_assignments or [])
        if a.due_at and a.due_at.astimezone(tz).date() == date
    ]
    if due_today:
        lines = "\n".join(_format_assignment_line(a, tz) for a in due_today)
        text += f"\n\nEntregas de Canvas para hoy:\n{lines}"

    return text


def format_weekly_briefing(
    events: list[CalendarEvent],
    week_start: dt.date,
    pending_assignments: list[CanvasAssignment] | None = None,
    timezone: str = "UTC",
) -> str:
    week_end = week_start + dt.timedelta(days=6)
    header = (
        f"Resumen semanal: {week_start.day} de {_MESES[week_start.month - 1]} "
        f"al {week_end.day} de {_MESES[week_end.month - 1]}."
    )

    by_day: dict[dt.date, list[str]] = {}
    for event in events:
        day = event.start if isinstance(event.start, dt.date) and not isinstance(
            event.start, dt.datetime
        ) else event.start.date()
        by_day.setdefault(day, []).append(_format_event_line(event))

    tz = ZoneInfo(timezone)
    for assignment in pending_assignments or []:
        if not assignment.due_at:
            continue
        day = assignment.due_at.astimezone(tz).date()
        if week_start <= day <= week_end:
            by_day.setdefault(day, []).append(_format_assignment_line(assignment, tz))

    if not by_day:
        return f"{header}\n\nNo tienes eventos ni entregas agendadas esta semana."

    blocks = []
    for day in sorted(by_day):
        dia = _DIAS[day.weekday()]
        day_lines = "\n".join(by_day[day])
        blocks.append(f"{dia.capitalize()} {day.day}:\n{day_lines}")

    return f"{header}\n\n" + "\n\n".join(blocks)
