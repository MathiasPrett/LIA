from sqlalchemy.orm import Session

from lia.db import IgnoredCanvasCourse


def ignore_course(session: Session, course_name: str) -> None:
    already = session.query(IgnoredCanvasCourse).filter_by(course_name=course_name).first()
    if already is None:
        session.add(IgnoredCanvasCourse(course_name=course_name))
        session.commit()


def unignore_course(session: Session, course_name: str) -> bool:
    existing = session.query(IgnoredCanvasCourse).filter_by(course_name=course_name).first()
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True


def list_ignored_courses(session: Session) -> list[str]:
    rows = session.query(IgnoredCanvasCourse).order_by(IgnoredCanvasCourse.course_name).all()
    return [row.course_name for row in rows]
