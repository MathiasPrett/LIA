import datetime as dt

from lia.db import make_engine, make_session_factory
from lia.integrations.canvas import CanvasActivityItem
from lia.services.canvas_watcher import find_new_items

TZ = dt.timezone.utc


def _item(key: str, title: str) -> CanvasActivityItem:
    return CanvasActivityItem(
        key=key,
        kind="Announcement",
        title=title,
        course_name="Diseño Detallado de Software",
        updated_at=dt.datetime(2026, 8, 27, 10, 0, tzinfo=TZ),
        html_url="https://canvas.example.com/x",
    )


def _session_factory():
    engine = make_engine(":memory:")
    return make_session_factory(engine)


def test_first_run_backfills_silently():
    session_factory = _session_factory()
    items = [_item("Announcement:1", "Aviso 1"), _item("Announcement:2", "Aviso 2")]

    with session_factory() as session:
        new_items = find_new_items(session, items)

    assert new_items == []


def test_second_run_does_not_repeat_already_seen_items():
    session_factory = _session_factory()
    items = [_item("Announcement:1", "Aviso 1"), _item("Announcement:2", "Aviso 2")]

    with session_factory() as session:
        find_new_items(session, items)  # primera corrida: backfill

    with session_factory() as session:
        new_items = find_new_items(session, items)  # misma lista de nuevo

    assert new_items == []


def test_second_run_detects_only_the_actually_new_item():
    session_factory = _session_factory()
    first_batch = [_item("Announcement:1", "Aviso 1")]

    with session_factory() as session:
        find_new_items(session, first_batch)  # backfill

    second_batch = [_item("Announcement:1", "Aviso 1"), _item("Announcement:2", "Aviso 2 nuevo")]
    with session_factory() as session:
        new_items = find_new_items(session, second_batch)

    assert [i.key for i in new_items] == ["Announcement:2"]


def test_running_twice_in_a_row_never_duplicates():
    session_factory = _session_factory()
    items = [_item("Announcement:1", "Aviso 1")]

    with session_factory() as session:
        find_new_items(session, items)  # backfill, primera vez

    with session_factory() as session:
        first_poll = find_new_items(session, items)
    with session_factory() as session:
        second_poll = find_new_items(session, items)

    assert first_poll == []
    assert second_poll == []
