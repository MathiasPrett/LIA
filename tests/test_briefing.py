import datetime as dt
from zoneinfo import ZoneInfo

from lia.integrations.canvas import CanvasAssignment
from lia.integrations.google_calendar import CalendarEvent
from lia.services.briefing import format_daily_briefing, format_weekly_briefing

TZ = ZoneInfo("America/Santiago")


def test_daily_briefing_no_events():
    text = format_daily_briefing([], dt.date(2026, 8, 27))
    assert "No tienes eventos" in text
    assert "jueves 27 de agosto" in text


def test_daily_briefing_timed_event():
    event = CalendarEvent(
        id="evt-1",
        calendar_id="primary",
        summary="Reunión con Javi",
        start=dt.datetime(2026, 8, 27, 14, 0, tzinfo=TZ),
        end=dt.datetime(2026, 8, 27, 15, 0, tzinfo=TZ),
        all_day=False,
        location="Oficina",
    )
    text = format_daily_briefing([event], dt.date(2026, 8, 27))
    assert "14:00–15:00 — Reunión con Javi (Oficina)" in text


def test_daily_briefing_all_day_event():
    event = CalendarEvent(
        id="evt-2",
        calendar_id="primary",
        summary="Feriado",
        start=dt.date(2026, 8, 27),
        end=dt.date(2026, 8, 28),
        all_day=True,
    )
    text = format_daily_briefing([event], dt.date(2026, 8, 27))
    assert "Todo el día — Feriado" in text


def test_daily_briefing_event_crossing_midnight():
    event = CalendarEvent(
        id="evt-3",
        calendar_id="primary",
        summary="Vuelo nocturno",
        start=dt.datetime(2026, 8, 27, 23, 30, tzinfo=TZ),
        end=dt.datetime(2026, 8, 28, 6, 0, tzinfo=TZ),
        all_day=False,
    )
    text = format_daily_briefing([event], dt.date(2026, 8, 27))
    assert "23:30–06:00 — Vuelo nocturno" in text


def test_weekly_briefing_groups_by_day():
    events = [
        CalendarEvent(
            id="evt-4",
            calendar_id="primary",
            summary="Lunes temprano",
            start=dt.datetime(2026, 8, 24, 9, 0, tzinfo=TZ),
            end=dt.datetime(2026, 8, 24, 10, 0, tzinfo=TZ),
            all_day=False,
        ),
        CalendarEvent(
            id="evt-5",
            calendar_id="primary",
            summary="Miércoles",
            start=dt.datetime(2026, 8, 26, 12, 0, tzinfo=TZ),
            end=dt.datetime(2026, 8, 26, 13, 0, tzinfo=TZ),
            all_day=False,
        ),
    ]
    text = format_weekly_briefing(events, dt.date(2026, 8, 24))
    assert "Lunes 24" in text
    assert "Miércoles 26" in text
    assert text.index("Lunes 24") < text.index("Miércoles 26")


def test_weekly_briefing_no_events():
    text = format_weekly_briefing([], dt.date(2026, 8, 24))
    assert "No tienes eventos ni entregas agendadas esta semana" in text


def test_daily_briefing_includes_canvas_assignment_due_today():
    # 02:30 UTC del 27-ago es 26-ago 22:30 en America/Santiago (UTC-4):
    # sin la conversión de zona horaria, esto se filtraría al día equivocado.
    assignment = CanvasAssignment(
        name="Tarea 3",
        course_name="Diseño Detallado de Software",
        due_at=dt.datetime(2026, 8, 27, 2, 30, tzinfo=dt.timezone.utc),
        html_url=None,
    )
    text = format_daily_briefing(
        [], dt.date(2026, 8, 26), pending_assignments=[assignment], timezone="America/Santiago"
    )
    assert "Entregas de Canvas para hoy" in text
    assert "Tarea 3" in text
    assert "22:30" in text


def test_daily_briefing_excludes_canvas_assignment_due_other_day():
    assignment = CanvasAssignment(
        name="Tarea 4",
        course_name=None,
        due_at=dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.timezone.utc),
        html_url=None,
    )
    text = format_daily_briefing(
        [], dt.date(2026, 8, 27), pending_assignments=[assignment], timezone="America/Santiago"
    )
    assert "Entregas de Canvas" not in text


def test_weekly_briefing_places_assignment_on_its_due_day():
    assignment = CanvasAssignment(
        name="Proyecto final",
        course_name="Redes",
        due_at=dt.datetime(2026, 8, 26, 15, 0, tzinfo=dt.timezone.utc),  # 11:00 en Santiago
        html_url=None,
    )
    text = format_weekly_briefing(
        [], dt.date(2026, 8, 24), pending_assignments=[assignment], timezone="America/Santiago"
    )
    assert "Miércoles 26" in text
    assert "Proyecto final" in text
    assert text.index("Miércoles 26") < text.index("Proyecto final")


def test_weekly_briefing_excludes_assignment_due_outside_the_week():
    assignment = CanvasAssignment(
        name="Tarea de otra semana",
        course_name=None,
        due_at=dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc),
        html_url=None,
    )
    text = format_weekly_briefing(
        [], dt.date(2026, 8, 24), pending_assignments=[assignment], timezone="America/Santiago"
    )
    assert "Tarea de otra semana" not in text
