from lia.db import make_engine, make_session_factory
from lia.services.canvas_ignore import ignore_course, list_ignored_courses, unignore_course


def _session_factory():
    engine = make_engine(":memory:")
    return make_session_factory(engine)


def test_ignore_course_then_list():
    session_factory = _session_factory()
    with session_factory() as session:
        ignore_course(session, "Cálculo III")
        assert list_ignored_courses(session) == ["Cálculo III"]


def test_ignore_course_is_idempotent():
    session_factory = _session_factory()
    with session_factory() as session:
        ignore_course(session, "Cálculo III")
        ignore_course(session, "Cálculo III")
        assert list_ignored_courses(session) == ["Cálculo III"]


def test_unignore_course_removes_it_and_reports_existed():
    session_factory = _session_factory()
    with session_factory() as session:
        ignore_course(session, "Cálculo III")
        removed = unignore_course(session, "Cálculo III")
        assert removed is True
        assert list_ignored_courses(session) == []


def test_unignore_course_not_ignored_reports_false():
    session_factory = _session_factory()
    with session_factory() as session:
        assert unignore_course(session, "Nunca ignorado") is False
