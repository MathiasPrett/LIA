import datetime as dt

from lia.db import LlmUsage, make_engine, make_session_factory
from lia.services.budget import month_to_date_cost_usd


def _session_factory():
    engine = make_engine(":memory:")
    return make_session_factory(engine)


def test_month_to_date_cost_usd_sums_only_current_month():
    session_factory = _session_factory()
    now = dt.datetime(2026, 8, 27, 12, 0)

    with session_factory() as session:
        session.add(LlmUsage(model="x", tokens_in=1, tokens_out=1, cost_usd=0.30, called_at=dt.datetime(2026, 8, 1, 0, 0)))
        session.add(LlmUsage(model="x", tokens_in=1, tokens_out=1, cost_usd=0.20, called_at=dt.datetime(2026, 8, 26, 23, 59)))
        session.add(LlmUsage(model="x", tokens_in=1, tokens_out=1, cost_usd=0.50, called_at=dt.datetime(2026, 7, 31, 23, 59)))
        session.commit()

        assert month_to_date_cost_usd(session, now) == 0.50


def test_month_to_date_cost_usd_with_no_usage_is_zero():
    session_factory = _session_factory()
    with session_factory() as session:
        assert month_to_date_cost_usd(session, dt.datetime(2026, 8, 27)) == 0.0
