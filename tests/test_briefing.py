import datetime as dt
from zoneinfo import ZoneInfo

from lia.integrations.canvas import CanvasAssignment
from lia.integrations.google_calendar import CalendarEvent
from lia.integrations.google_tasks import TaskItem
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


def test_weekly_briefing_adds_spending_line_and_flags_exceeded_budgets():
    spending = {
        "total": 200000,
        "total_consumo": 180000,
        "por_categoria": [],
        "presupuestos": [
            {"categoria": "fiesta", "limite": 30000, "gastado": 34000, "supera": True},
            {"categoria": "comida", "limite": 100000, "gastado": 50000, "supera": False},
        ],
    }
    text = format_weekly_briefing([], dt.date(2026, 8, 24), spending_summary=spending)

    assert "$180.000" in text  # usa el total de consumo, no el que incluye ahorro
    assert "fiesta" in text and "$34.000" in text
    assert "comida" not in text  # la que va dentro del tope no se menciona


def test_weekly_briefing_without_spending_summary_is_unchanged():
    text = format_weekly_briefing([], dt.date(2026, 8, 24))
    assert "💸" not in text


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


# --- Google Tasks en los briefings ---


def _task(title, due):
    return TaskItem(id=title, title=title, notes=None, due=due)


def test_daily_briefing_muestra_las_tareas_que_vencen_hoy_y_las_atrasadas():
    tareas = [
        _task("Vence hoy", dt.date(2026, 9, 5)),
        _task("Quedó atrasada", dt.date(2026, 9, 3)),
        _task("Vence después", dt.date(2026, 9, 20)),
    ]
    text = format_daily_briefing([], dt.date(2026, 9, 5), google_tasks=tareas)

    assert "Vence hoy" in text
    assert "Quedó atrasada" in text and "(atrasada)" in text
    assert "Vence después" not in text


def test_daily_briefing_omite_las_tareas_sin_fecha():
    # No tienen fecha de vencimiento, así que no pertenecen al resumen de la mañana.
    text = format_daily_briefing([], dt.date(2026, 9, 5), google_tasks=[_task("Sin fecha", None)])
    assert "Sin fecha" not in text


def test_weekly_briefing_ubica_la_tarea_en_su_dia():
    text = format_weekly_briefing(
        [], dt.date(2026, 8, 24), google_tasks=[_task("Entregar informe", dt.date(2026, 8, 26))]
    )
    assert "Miércoles 26" in text
    assert "Entregar informe" in text


def test_briefings_sin_tareas_quedan_igual_que_antes():
    assert "Tareas pendientes" not in format_daily_briefing([], dt.date(2026, 9, 5))
    assert "✅" not in format_weekly_briefing([], dt.date(2026, 8, 24))
