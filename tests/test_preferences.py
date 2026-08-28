from lia.db import make_engine, make_session_factory
from lia.services.preferences import get_preference, set_preference


def _session_factory():
    engine = make_engine(":memory:")
    return make_session_factory(engine)


def test_get_preference_missing_returns_none():
    session_factory = _session_factory()
    with session_factory() as session:
        assert get_preference(session, "unknown") is None


def test_set_then_get_preference():
    session_factory = _session_factory()
    with session_factory() as session:
        set_preference(session, "foo", "bar")
        assert get_preference(session, "foo") == "bar"


def test_set_preference_overwrites_existing():
    session_factory = _session_factory()
    with session_factory() as session:
        set_preference(session, "foo", "bar")
        set_preference(session, "foo", "baz")
        assert get_preference(session, "foo") == "baz"
