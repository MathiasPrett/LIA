import datetime as dt
from zoneinfo import ZoneInfo

from lia.config import Settings
from lia.db import make_engine, make_session_factory
from lia.integrations.google_calendar import CalendarEvent
from lia.services.reminders import find_events_needing_reminder, is_important

TZ = ZoneInfo("America/Santiago")


def _settings(**overrides) -> Settings:
    defaults = dict(
        _env_file=None,
        telegram_bot_token="fake",
        owner_user_id=1,
        gemini_api_key="fake",
        canvas_base_url="https://fake.instructure.com",
        canvas_access_token="fake",
        calendar_ids="primary",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _event(
    summary="Reunión",
    duration_minutes=30,
    attendees_count=0,
    all_day=False,
    calendar_id="primary",
    event_id="evt-1",
) -> CalendarEvent:
    start = dt.datetime(2026, 8, 28, 10, 0, tzinfo=TZ)
    if all_day:
        return CalendarEvent(
            id=event_id,
            calendar_id=calendar_id,
            summary=summary,
            start=dt.date(2026, 8, 28),
            end=dt.date(2026, 8, 29),
            all_day=True,
            attendees_count=attendees_count,
        )
    return CalendarEvent(
        id=event_id,
        calendar_id=calendar_id,
        summary=summary,
        start=start,
        end=start + dt.timedelta(minutes=duration_minutes),
        all_day=False,
        attendees_count=attendees_count,
    )


def test_all_day_event_is_never_important():
    settings = _settings(important_min_duration_minutes=1)
    assert is_important(_event(all_day=True), settings) is False


def test_long_event_is_important():
    settings = _settings(important_min_duration_minutes=90)
    assert is_important(_event(duration_minutes=30), settings) is False
    assert is_important(_event(duration_minutes=120), settings) is True


def test_event_with_many_attendees_is_important():
    settings = _settings(important_min_attendees=3)
    assert is_important(_event(attendees_count=2), settings) is False
    assert is_important(_event(attendees_count=3), settings) is True


def test_event_with_keyword_is_important():
    settings = _settings(important_keywords="examen,entrega")
    assert is_important(_event(summary="Reunión de equipo"), settings) is False
    assert is_important(_event(summary="Examen de Redes"), settings) is True


def test_event_on_important_calendar_is_always_important():
    settings = _settings(important_calendar_ids="mym@group.calendar.google.com")
    assert is_important(_event(calendar_id="primary"), settings) is False
    assert is_important(_event(calendar_id="mym@group.calendar.google.com"), settings) is True


def test_short_ordinary_event_is_not_important():
    settings = _settings()
    assert is_important(_event(duration_minutes=30, attendees_count=0), settings) is False


def test_reminder_is_not_sent_twice_for_the_same_event():
    settings = _settings(important_min_duration_minutes=1)  # todo evento cuenta como importante
    engine = make_engine(":memory:")
    session_factory = make_session_factory(engine)
    event = _event(duration_minutes=120)

    with session_factory() as session:
        first_poll = find_events_needing_reminder(session, [event], settings)
    with session_factory() as session:
        second_poll = find_events_needing_reminder(session, [event], settings)

    assert [e.id for e in first_poll] == ["evt-1"]
    assert second_poll == []
