import datetime as dt
from zoneinfo import ZoneInfo

from lia.integrations.google_calendar import CalendarEvent
from lia.services.planner import find_free_slots

TZ = ZoneInfo("America/Santiago")


def _timed_event(event_id: str, start_h: int, start_m: int, end_h: int, end_m: int, day=27) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        calendar_id="primary",
        summary=event_id,
        start=dt.datetime(2026, 8, day, start_h, start_m, tzinfo=TZ),
        end=dt.datetime(2026, 8, day, end_h, end_m, tzinfo=TZ),
        all_day=False,
    )


def _all_day_event(event_id: str, day=27) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        calendar_id="primary",
        summary=event_id,
        start=dt.date(2026, 8, day),
        end=dt.date(2026, 8, day + 1),
        all_day=True,
    )


def test_empty_day_returns_the_whole_working_window():
    range_start = dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ)

    slots = find_free_slots([], range_start, range_end, duration_minutes=60, day_start_hour=8, day_end_hour=22)

    assert slots == [
        (dt.datetime(2026, 8, 27, 8, 0, tzinfo=TZ), dt.datetime(2026, 8, 27, 22, 0, tzinfo=TZ)),
    ]


def test_finds_gap_between_two_events():
    events = [_timed_event("a", 9, 0, 10, 0), _timed_event("b", 12, 0, 13, 0)]
    range_start = dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ)

    slots = find_free_slots(events, range_start, range_end, duration_minutes=60, day_start_hour=8, day_end_hour=22)

    assert (dt.datetime(2026, 8, 27, 10, 0, tzinfo=TZ), dt.datetime(2026, 8, 27, 12, 0, tzinfo=TZ)) in slots
    assert (dt.datetime(2026, 8, 27, 13, 0, tzinfo=TZ), dt.datetime(2026, 8, 27, 22, 0, tzinfo=TZ)) in slots


def test_gap_shorter_than_requested_duration_is_excluded():
    # hueco de 9:00 a 9:30 (30 min) pero se piden bloques de 60 min
    events = [_timed_event("a", 8, 0, 9, 0), _timed_event("b", 9, 30, 22, 0)]
    range_start = dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ)

    slots = find_free_slots(events, range_start, range_end, duration_minutes=60, day_start_hour=8, day_end_hour=22)

    assert slots == []


def test_all_day_event_blocks_the_whole_day():
    events = [_all_day_event("feriado")]
    range_start = dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ)

    slots = find_free_slots(events, range_start, range_end, duration_minutes=30, day_start_hour=8, day_end_hour=22)

    assert slots == []


def test_overlapping_events_are_merged_correctly():
    # 9-11 y 10-12 se solapan; el hueco libre debería empezar recién a las 12
    events = [_timed_event("a", 9, 0, 11, 0), _timed_event("b", 10, 0, 12, 0)]
    range_start = dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ)

    slots = find_free_slots(events, range_start, range_end, duration_minutes=30, day_start_hour=8, day_end_hour=22)

    assert (dt.datetime(2026, 8, 27, 8, 0, tzinfo=TZ), dt.datetime(2026, 8, 27, 9, 0, tzinfo=TZ)) in slots
    assert (dt.datetime(2026, 8, 27, 12, 0, tzinfo=TZ), dt.datetime(2026, 8, 27, 22, 0, tzinfo=TZ)) in slots
    # ningún hueco debería empezar entre las 9 y las 12, porque están ocupadas
    assert not any(9 <= s.hour < 12 for s, _ in slots)


def test_range_starting_mid_day_clips_to_now_not_to_day_start():
    # si "ahora" son las 15:00, no debería proponer un hueco a las 8am (ya pasó)
    range_start = dt.datetime(2026, 8, 27, 15, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ)

    slots = find_free_slots([], range_start, range_end, duration_minutes=60, day_start_hour=8, day_end_hour=22)

    assert slots == [(dt.datetime(2026, 8, 27, 15, 0, tzinfo=TZ), dt.datetime(2026, 8, 27, 22, 0, tzinfo=TZ))]


def test_multi_day_range_returns_slots_for_each_open_day():
    events = [_all_day_event("feriado", day=28)]  # bloquea el 28, no el 27 ni el 29
    range_start = dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    range_end = dt.datetime(2026, 8, 29, 23, 59, tzinfo=TZ)

    slots = find_free_slots(events, range_start, range_end, duration_minutes=60, day_start_hour=8, day_end_hour=22)

    days_with_slots = {s.date() for s, _ in slots}
    assert days_with_slots == {dt.date(2026, 8, 27), dt.date(2026, 8, 29)}
