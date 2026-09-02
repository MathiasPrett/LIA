import datetime as dt

from sqlalchemy import DateTime, Engine, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class SeenItem(Base):
    """Dedup de polling externo (Canvas, Gmail): un ítem solo notifica una vez."""

    __tablename__ = "seen_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    fire_at: Mapped[dt.datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Conversation(Base):
    """Ventana deslizante de historial de chat para el contexto del LLM."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class LlmUsage(Base):
    """Registro de cada llamada al LLM para vigilar el presupuesto mensual."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    called_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class Preference(Base):
    __tablename__ = "preferences"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Expense(Base):
    """Gasto personal registrado a mano por el usuario."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # CLP no tiene decimales: Integer evita el error de redondeo de los flotantes al sumar.
    amount_clp: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    # OJO: naive en HORA LOCAL de Chile, no en UTC como el resto de las tablas. Es una
    # excepción deliberada (ver CLAUDE.md): así "este mes" es una comparación directa y
    # un gasto de las 22:00 del 30/09 no se cuela en octubre por el desfase horario.
    spent_at: Mapped[dt.datetime] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)  # naive UTC


class SpendingBudget(Base):
    """Tope mensual de gasto por categoría."""

    __tablename__ = "spending_budgets"

    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    monthly_limit_clp: Mapped[int] = mapped_column(Integer)


class IgnoredCanvasCourse(Base):
    """Cursos de Canvas cuyas novedades/tareas el usuario pidió dejar de notificar."""

    __tablename__ = "ignored_canvas_courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_name: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


def make_engine(database_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
