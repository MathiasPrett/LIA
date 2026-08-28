from sqlalchemy.orm import Session

from lia.db import Preference


def get_preference(session: Session, key: str) -> str | None:
    pref = session.get(Preference, key)
    return pref.value if pref else None


def set_preference(session: Session, key: str, value: str) -> None:
    pref = session.get(Preference, key)
    if pref is None:
        session.add(Preference(key=key, value=value))
    else:
        pref.value = value
    session.commit()
