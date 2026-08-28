import datetime as dt

from lia.integrations.google_calendar import CalendarEvent


def _event_day(event: CalendarEvent) -> dt.date:
    if event.all_day:
        return event.start  # type: ignore[return-value]  # dt.date cuando all_day
    return event.start.date()


def find_free_slots(
    events: list[CalendarEvent],
    range_start: dt.datetime,
    range_end: dt.datetime,
    duration_minutes: int,
    day_start_hour: int,
    day_end_hour: int,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Huecos libres de al menos `duration_minutes` dentro de la jornada
    [day_start_hour, day_end_hour) de cada día del rango.

    Los eventos de todo el día bloquean el día entero (una simplificación:
    trata por igual un feriado que un evento informativo de un día completo,
    pero evita proponer horarios de estudio en días que probablemente estén
    ocupados).
    """
    tz = range_start.tzinfo
    duration = dt.timedelta(minutes=duration_minutes)

    blocked_days = {_event_day(e) for e in events if e.all_day}

    busy_by_day: dict[dt.date, list[tuple[dt.datetime, dt.datetime]]] = {}
    for event in events:
        if event.all_day:
            continue
        busy_by_day.setdefault(event.start.date(), []).append((event.start, event.end))

    free_slots: list[tuple[dt.datetime, dt.datetime]] = []
    current_day = range_start.date()

    while current_day <= range_end.date():
        if current_day not in blocked_days:
            day_start = max(
                dt.datetime.combine(current_day, dt.time(hour=day_start_hour), tzinfo=tz), range_start
            )
            day_end = min(
                dt.datetime.combine(current_day, dt.time(hour=day_end_hour), tzinfo=tz), range_end
            )

            if day_start < day_end:
                cursor = day_start
                for busy_start, busy_end in sorted(busy_by_day.get(current_day, [])):
                    if busy_start > cursor and busy_start - cursor >= duration:
                        free_slots.append((cursor, busy_start))
                    cursor = max(cursor, busy_end)

                if day_end - cursor >= duration:
                    free_slots.append((cursor, day_end))

        current_day += dt.timedelta(days=1)

    return free_slots
