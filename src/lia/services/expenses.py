"""Registro de gastos personales.

Todas las fechas de gasto (`Expense.spent_at`) son **naive en hora local de Chile**,
no en UTC como el resto del proyecto. Eso hace que "este mes" sea una comparación
directa contra la columna, sin conversiones, y que un gasto de las 22:00 del 30 de
septiembre no termine contado en octubre.
"""

import csv
import datetime as dt
import io
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from lia.db import Expense, SpendingBudget

# Lista fija a propósito: si el modelo inventara categorías cada vez, terminaríamos con
# "comida", "Comida" y "alimentación" como tres categorías distintas y los totales no
# sumarían. Viaja como enum en el schema de la tool, que además es barato en tokens.
CATEGORIAS_GASTO: dict[str, str] = {
    "comida": "🍔",
    "supermercado": "🛒",
    "transporte": "🚗",
    "fiesta": "🎉",
    "entretencion": "🎬",
    "salud": "💊",
    "educacion": "📚",
    "vestuario": "👕",
    "hogar": "🏠",
    "suscripciones": "🤖",
    "seguros": "🛡️",
    "ahorro": "💰",
    "efectivo": "💵",
    "tabaco": "🚬",
    "donacion": "⛪",
    "otros": "❓",
}

# `ahorro` es un traspaso, no consumo: si entra al total, un aporte a Fintual infla el
# "gastaste X este mes". Por eso el resumen devuelve también un total sin estas.
CATEGORIAS_NO_CONSUMO = frozenset({"ahorro"})


def emoji_categoria(categoria: str) -> str:
    return CATEGORIAS_GASTO.get(categoria, "❓")


def format_clp(monto: int) -> str:
    """34000 → '$34.000' (formato chileno: punto como separador de miles)."""
    return f"${monto:,.0f}".replace(",", ".")


def now_local(timezone: str) -> dt.datetime:
    """Ahora, naive, en hora local — misma referencia que `Expense.spent_at`."""
    return dt.datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)


def month_bounds(ref_local: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Primer instante del mes de `ref_local` y último del mismo mes."""
    start = ref_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - dt.timedelta(microseconds=1)


def day_bounds(start_date: dt.date, end_date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    return (
        dt.datetime.combine(start_date, dt.time.min),
        dt.datetime.combine(end_date, dt.time.max),
    )


def add_expense(
    session: Session,
    amount_clp: int,
    description: str,
    category: str,
    spent_at: dt.datetime,
) -> Expense:
    expense = Expense(
        amount_clp=amount_clp,
        description=description,
        category=category if category in CATEGORIAS_GASTO else "otros",
        spent_at=spent_at,
    )
    session.add(expense)
    session.commit()
    return expense


def _last_expense(session: Session) -> Expense | None:
    return session.query(Expense).order_by(Expense.id.desc()).first()


def update_last_expense(
    session: Session,
    amount_clp: int | None = None,
    description: str | None = None,
    category: str | None = None,
) -> Expense | None:
    """Patch parcial del gasto más reciente: solo toca los campos que vengan."""
    expense = _last_expense(session)
    if expense is None:
        return None

    if amount_clp is not None:
        expense.amount_clp = amount_clp
    if description is not None:
        expense.description = description
    if category is not None and category in CATEGORIAS_GASTO:
        expense.category = category

    session.commit()
    return expense


def delete_last_expense(session: Session) -> Expense | None:
    expense = _last_expense(session)
    if expense is None:
        return None
    session.delete(expense)
    session.commit()
    return expense


def list_expenses(
    session: Session,
    desde: dt.datetime,
    hasta: dt.datetime,
    categoria: str | None = None,
) -> list[Expense]:
    query = session.query(Expense).filter(Expense.spent_at >= desde, Expense.spent_at <= hasta)
    if categoria:
        query = query.filter(Expense.category == categoria)
    return query.order_by(Expense.spent_at).all()


def set_budget(session: Session, categoria: str, monto_mensual: int) -> None:
    """Fija el tope mensual de una categoría. Monto 0 (o menos) lo elimina."""
    existing = session.get(SpendingBudget, categoria)
    if monto_mensual <= 0:
        if existing is not None:
            session.delete(existing)
            session.commit()
        return

    if existing is None:
        session.add(SpendingBudget(category=categoria, monthly_limit_clp=monto_mensual))
    else:
        existing.monthly_limit_clp = monto_mensual
    session.commit()


def list_budgets(session: Session) -> dict[str, int]:
    return {b.category: b.monthly_limit_clp for b in session.query(SpendingBudget).all()}


def month_spend_for_category(session: Session, categoria: str, ref_local: dt.datetime) -> int:
    start, end = month_bounds(ref_local)
    total = (
        session.query(func.sum(Expense.amount_clp))
        .filter(Expense.category == categoria, Expense.spent_at >= start, Expense.spent_at <= end)
        .scalar()
    )
    return int(total or 0)


def summarize(session: Session, desde: dt.datetime, hasta: dt.datetime) -> dict:
    """Agregados por categoría. Devuelve totales, no filas: es lo que se le manda al LLM."""
    rows = (
        session.query(
            Expense.category,
            func.sum(Expense.amount_clp),
            func.count(Expense.id),
        )
        .filter(Expense.spent_at >= desde, Expense.spent_at <= hasta)
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount_clp).desc())
        .all()
    )

    por_categoria = [
        {"categoria": categoria, "total": int(total or 0), "cantidad": cantidad}
        for categoria, total, cantidad in rows
    ]
    total = sum(c["total"] for c in por_categoria)
    total_consumo = sum(
        c["total"] for c in por_categoria if c["categoria"] not in CATEGORIAS_NO_CONSUMO
    )

    gastado = {c["categoria"]: c["total"] for c in por_categoria}
    presupuestos = [
        {
            "categoria": categoria,
            "limite": limite,
            "gastado": gastado.get(categoria, 0),
            "supera": gastado.get(categoria, 0) > limite,
        }
        for categoria, limite in sorted(list_budgets(session).items())
    ]

    return {
        "total": total,
        "total_consumo": total_consumo,
        "por_categoria": por_categoria,
        "presupuestos": presupuestos,
    }


def to_csv_bytes(expenses: list[Expense]) -> bytes:
    """CSV listo para Excel: utf-8-sig (BOM) para que no rompa las tildes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["fecha", "hora", "monto", "descripcion", "categoria"])
    for e in expenses:
        writer.writerow(
            [
                e.spent_at.strftime("%Y-%m-%d"),
                e.spent_at.strftime("%H:%M"),
                e.amount_clp,
                e.description,
                e.category,
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")
