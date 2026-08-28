import datetime as dt

from sqlalchemy import func
from sqlalchemy.orm import Session

from lia.db import LlmUsage


def month_to_date_cost_usd(session: Session, now: dt.datetime) -> float:
    """Suma `cost_usd` de `llm_usage` desde el día 1 del mes de `now` (naive, misma zona que `called_at`)."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (
        session.query(func.sum(LlmUsage.cost_usd)).filter(LlmUsage.called_at >= month_start).scalar()
    )
    return total or 0.0
