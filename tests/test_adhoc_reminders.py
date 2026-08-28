import datetime as dt

from lia.db import Reminder, make_engine, make_session_factory
from lia.services.reminders import find_due_reminders, format_adhoc_reminder


def _session_factory():
    engine = make_engine(":memory:")
    return make_session_factory(engine)


def test_due_reminder_is_returned_and_marked_sent():
    session_factory = _session_factory()
    now = dt.datetime(2026, 8, 28, 12, 0)

    with session_factory() as session:
        session.add(Reminder(text="Llamar al dentista", fire_at=dt.datetime(2026, 8, 28, 11, 0), status="pending"))
        session.commit()

    with session_factory() as session:
        due = find_due_reminders(session, now)
        assert [r.text for r in due] == ["Llamar al dentista"]

    with session_factory() as session:
        reminder = session.query(Reminder).one()
        assert reminder.status == "sent"


def test_future_reminder_is_not_returned():
    session_factory = _session_factory()
    now = dt.datetime(2026, 8, 28, 12, 0)

    with session_factory() as session:
        session.add(Reminder(text="Cosa futura", fire_at=dt.datetime(2026, 8, 28, 13, 0), status="pending"))
        session.commit()

    with session_factory() as session:
        due = find_due_reminders(session, now)

    assert due == []


def test_reminder_is_not_sent_twice():
    session_factory = _session_factory()
    now = dt.datetime(2026, 8, 28, 12, 0)

    with session_factory() as session:
        session.add(Reminder(text="Algo", fire_at=dt.datetime(2026, 8, 28, 11, 0), status="pending"))
        session.commit()

    with session_factory() as session:
        first_poll = find_due_reminders(session, now)
    with session_factory() as session:
        second_poll = find_due_reminders(session, now)

    assert len(first_poll) == 1
    assert second_poll == []


def test_format_adhoc_reminder():
    reminder = Reminder(text="Llamar al dentista", fire_at=dt.datetime(2026, 8, 28, 11, 0))
    assert format_adhoc_reminder(reminder) == "⏰ Recordatorio: Llamar al dentista"
