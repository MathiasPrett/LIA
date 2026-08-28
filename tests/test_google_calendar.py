import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from google.auth.exceptions import RefreshError

from lia.integrations import google_calendar
from lia.integrations.google_calendar import CalendarEvent, CalendarNotConnected, fetch_events, load_credentials

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
