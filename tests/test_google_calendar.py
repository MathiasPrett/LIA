import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from google.auth.exceptions import RefreshError

from lia.integrations import google_calendar
from lia.integrations.google_calendar import (
    CalendarEvent,
    CalendarNotConnected,
    color_id_for_category,
    create_birthday_event,
    create_event,
    fetch_events,
    load_credentials,
)

TZ = ZoneInfo("America/Santiago")


def _event(summary: str, hour: int) -> CalendarEvent:
    return CalendarEvent(
        id=f"evt-{summary}-{hour}",
        calendar_id="primary",
        summary=summary,
        start=dt.datetime(2026, 8, 27, hour, 0, tzinfo=TZ),
        end=dt.datetime(2026, 8, 27, hour, 30, tzinfo=TZ),
        all_day=False,
    )


def test_fetch_events_merges_and_sorts_multiple_calendars(monkeypatch):
    per_calendar = {
        "primary": [_event("Personal tarde", 18)],
        "compartido@group.calendar.google.com": [_event("Pareja temprano", 9)],
    }

    monkeypatch.setattr(google_calendar, "load_credentials", lambda token_path: object())
    monkeypatch.setattr(google_calendar, "build_service", lambda creds: object())
    monkeypatch.setattr(
        google_calendar,
        "list_events",
        lambda service, calendar_id, time_min, time_max, timezone: per_calendar[calendar_id],
    )

    events = fetch_events(
        Path("token.json"),
        dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ),
        dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ),
        "America/Santiago",
        calendar_ids=["primary", "compartido@group.calendar.google.com"],
    )

    assert [e.summary for e in events] == ["Pareja temprano", "Personal tarde"]


def test_fetch_events_defaults_to_primary_only(monkeypatch):
    seen_calendar_ids = []

    monkeypatch.setattr(google_calendar, "load_credentials", lambda token_path: object())
    monkeypatch.setattr(google_calendar, "build_service", lambda creds: object())

    def fake_list_events(service, calendar_id, time_min, time_max, timezone):
        seen_calendar_ids.append(calendar_id)
        return []

    monkeypatch.setattr(google_calendar, "list_events", fake_list_events)

    fetch_events(
        Path("token.json"),
        dt.datetime(2026, 8, 27, 0, 0, tzinfo=TZ),
        dt.datetime(2026, 8, 27, 23, 59, tzinfo=TZ),
        "America/Santiago",
    )

    assert seen_calendar_ids == ["primary"]


def test_load_credentials_raises_calendar_not_connected_on_revoked_refresh_token(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    class FakeCreds:
        expired = True
        refresh_token = "some-refresh-token"

        def refresh(self, request):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(
        google_calendar.Credentials, "from_authorized_user_file", lambda path, scopes: FakeCreds()
    )

    with pytest.raises(CalendarNotConnected):
        load_credentials(token_path)


class _FakeInsert:
    def __init__(self, captured: dict, response: dict):
        self._captured = captured
        self._response = response

    def insert(self, calendarId, body):
        self._captured["calendarId"] = calendarId
        self._captured["body"] = body
        return self

    def execute(self):
        return self._response


class _FakeService:
    def __init__(self, captured: dict, response: dict):
        self._events = _FakeInsert(captured, response)

    def events(self):
        return self._events


def test_color_id_for_category_known_and_unknown():
    assert color_id_for_category("academico") == "7"
    assert color_id_for_category("salud") == "11"
    assert color_id_for_category("inventada") is None
    assert color_id_for_category(None) is None


def test_create_event_includes_color_id_when_given():
    captured = {}
    response = {
        "id": "evt-1",
        "summary": "Certamen",
        "start": {"dateTime": "2026-08-29T13:00:00-04:00"},
        "end": {"dateTime": "2026-08-29T14:00:00-04:00"},
    }
    service = _FakeService(captured, response)

    create_event(
        service, "primary", "Certamen",
        dt.datetime(2026, 8, 29, 13, 0, tzinfo=TZ), dt.datetime(2026, 8, 29, 14, 0, tzinfo=TZ),
        "America/Santiago", color_id="7",
    )

    assert captured["body"]["colorId"] == "7"


def test_create_event_omits_color_id_when_not_given():
    captured = {}
    response = {
        "id": "evt-2",
        "summary": "Reunión",
        "start": {"dateTime": "2026-08-29T13:00:00-04:00"},
        "end": {"dateTime": "2026-08-29T14:00:00-04:00"},
    }
    service = _FakeService(captured, response)

    create_event(
        service, "primary", "Reunión",
        dt.datetime(2026, 8, 29, 13, 0, tzinfo=TZ), dt.datetime(2026, 8, 29, 14, 0, tzinfo=TZ),
        "America/Santiago",
    )

    assert "colorId" not in captured["body"]


def test_create_birthday_event_body_and_forced_primary_calendar():
    captured = {}
    response = {
        "id": "evt-bday",
        "summary": "Cumpleaños de Ana",
        "start": {"date": "2026-09-15"},
        "end": {"date": "2026-09-16"},
    }
    service = _FakeService(captured, response)

    create_birthday_event(service, "Cumpleaños de Ana", dt.date(2026, 9, 15))

    assert captured["calendarId"] == "primary"
    body = captured["body"]
    assert body["eventType"] == "birthday"
    assert body["start"] == {"date": "2026-09-15"}
    assert body["end"] == {"date": "2026-09-16"}
    assert body["recurrence"] == ["RRULE:FREQ=YEARLY"]
    assert body["birthdayProperties"] == {"type": "birthday"}
    assert body["visibility"] == "private"
    assert body["transparency"] == "transparent"


def test_create_birthday_event_leap_day_uses_special_recurrence():
    captured = {}
    response = {"id": "evt-bday-feb29", "start": {"date": "2028-02-29"}, "end": {"date": "2028-03-01"}}
    service = _FakeService(captured, response)

    create_birthday_event(service, "Cumpleaños de Leo", dt.date(2028, 2, 29))

    assert captured["body"]["recurrence"] == ["RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1"]
