import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from lia.bot.ui import send_formatted
from lia.config import Settings
from lia.integrations.canvas import CanvasError, fetch_activity_items, fetch_pending_assignments
from lia.integrations.google_calendar import CalendarNotConnected, fetch_events
from lia.integrations.google_tasks import fetch_tasks
from lia.llm.prompts import build_system_prompt
from lia.services.backup import backup_database, prune_old_backups
from lia.services.briefing import format_daily_briefing, format_weekly_briefing
from lia.services.budget import month_to_date_cost_usd
from lia.services.canvas_watcher import find_new_items, format_activity_notification
from lia.services.conversation import log_usage
from lia.services.expenses import month_bounds, now_local, summarize
from lia.services.preferences import get_preference, set_preference
from lia.services.reminders import find_due_reminders, find_events_needing_reminder, format_adhoc_reminder, format_reminder

logger = logging.getLogger(__name__)

# PTB usa domingo=0 para `days` en run_daily (distinto de datetime.weekday(), donde lunes=0).
_SUNDAY = 0

_CALENDAR_ALERT_KEY = "calendar_disconnected_alerted"
_BUDGET_ALERT_KEY = "budget_alert_month"


async def _handle_calendar_disconnected(
    context: ContextTypes.DEFAULT_TYPE, settings: Settings, session_factory, message: str
) -> None:
    with session_factory() as session:
        already_alerted = get_preference(session, _CALENDAR_ALERT_KEY) == "1"
        if not already_alerted:
            set_preference(session, _CALENDAR_ALERT_KEY, "1")
    if not already_alerted:
        await send_formatted(context.bot, settings.owner_user_id, f"⚠️ {message}")


async def _handle_calendar_reconnected(
    context: ContextTypes.DEFAULT_TYPE, settings: Settings, session_factory
) -> None:
    with session_factory() as session:
        was_alerted = get_preference(session, _CALENDAR_ALERT_KEY) == "1"
        if was_alerted:
            set_preference(session, _CALENDAR_ALERT_KEY, "0")
    if was_alerted:
        await send_formatted(context.bot, settings.owner_user_id, "✅ Google Calendar volvió a conectarse.")


async def _redact_with_llm(context: ContextTypes.DEFAULT_TYPE, settings: Settings, instruction: str, plain_text: str) -> str:
    """Le pide al LLM que redacte una versión más natural de un texto ya armado por código.

    Si el LLM falla por cualquier motivo, se cae al texto plano original — nunca
    debe faltar el mensaje por un problema de redacción.
    """
    provider = context.bot_data.get("llm_provider")
    if provider is None:
        return plain_text

    try:
        result = await provider.run_conversation(
            system_prompt=build_system_prompt(settings),
            history=[],
            user_message=f"{instruction}\n\n{plain_text}",
            tools=[],
        )
        session_factory = context.bot_data["session_factory"]
        with session_factory() as session:
            log_usage(session, settings.gemini_model, result.tokens_in, result.tokens_out)
        return result.reply_text or plain_text
    except Exception:
        logger.exception("Falló la redacción con el LLM, uso el texto plano")
        return plain_text


async def _fetch_google_tasks(settings: Settings, job: str) -> list:
    """Las tareas son un extra del briefing: si fallan, el resumen sale igual sin ellas."""
    try:
        return await asyncio.to_thread(fetch_tasks, settings.google_token_path)
    except Exception:
        logger.exception("Job %s: no se pudo consultar Google Tasks, sigo sin ellas", job)
        return []


async def _send_daily_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]
    tz = ZoneInfo(settings.timezone)
    today = dt.datetime.now(tz).date()
    time_min = dt.datetime.combine(today, dt.time.min, tzinfo=tz)
    time_max = dt.datetime.combine(today, dt.time.max, tzinfo=tz)

    try:
        events = await asyncio.to_thread(
            fetch_events,
            settings.google_token_path,
            time_min,
            time_max,
            settings.timezone,
            settings.calendar_id_list,
        )
    except CalendarNotConnected as exc:
        logger.warning("Job diario: Google Calendar no está conectado todavía, se omite el envío.")
        await _handle_calendar_disconnected(context, settings, session_factory, str(exc))
        return
    await _handle_calendar_reconnected(context, settings, session_factory)

    try:
        pending_assignments = await fetch_pending_assignments(
            settings.canvas_base_url, settings.canvas_access_token
        )
    except CanvasError:
        logger.exception("Job diario: no se pudo consultar Canvas, sigo solo con el calendario")
        pending_assignments = []

    tareas = await _fetch_google_tasks(settings, "diario")
    plain_text = format_daily_briefing(
        events, today, pending_assignments, settings.timezone, tareas
    )
    text = await _redact_with_llm(
        context,
        settings,
        "Redacta el resumen matutino para el usuario en base a esta agenda de hoy. "
        "No inventes eventos que no estén en la lista, no agregues nada que no se pueda "
        "inferir de aquí:",
        plain_text,
    )

    await send_formatted(context.bot, settings.owner_user_id, text)


async def _send_weekly_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]
    tz = ZoneInfo(settings.timezone)
    today = dt.datetime.now(tz).date()
    week_start = today - dt.timedelta(days=today.weekday())
    week_end = week_start + dt.timedelta(days=6)
    time_min = dt.datetime.combine(week_start, dt.time.min, tzinfo=tz)
    time_max = dt.datetime.combine(week_end, dt.time.max, tzinfo=tz)

    try:
        events = await asyncio.to_thread(
            fetch_events,
            settings.google_token_path,
            time_min,
            time_max,
            settings.timezone,
            settings.calendar_id_list,
        )
    except CalendarNotConnected as exc:
        logger.warning("Job semanal: Google Calendar no está conectado todavía, se omite el envío.")
        await _handle_calendar_disconnected(context, settings, session_factory, str(exc))
        return
    await _handle_calendar_reconnected(context, settings, session_factory)

    try:
        pending_assignments = await fetch_pending_assignments(
            settings.canvas_base_url, settings.canvas_access_token
        )
    except CanvasError:
        logger.exception("Job semanal: no se pudo consultar Canvas, sigo solo con el calendario")
        pending_assignments = []

    with session_factory() as session:
        spending = summarize(session, *month_bounds(now_local(settings.timezone)))

    tareas = await _fetch_google_tasks(settings, "semanal")
    plain_text = format_weekly_briefing(
        events, week_start, pending_assignments, settings.timezone, spending, tareas
    )
    text = await _redact_with_llm(
        context,
        settings,
        "Redacta el resumen semanal para el usuario en base a esta agenda de la semana que "
        "empieza. No inventes eventos ni entregas que no estén en la lista, no agregues nada "
        "que no se pueda inferir de aquí:",
        plain_text,
    )

    await send_formatted(context.bot, settings.owner_user_id, text)


async def _check_important_events(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]
    tz = ZoneInfo(settings.timezone)
    now = dt.datetime.now(tz)
    horizon = now + dt.timedelta(minutes=settings.reminder_lead_minutes)

    try:
        events = await asyncio.to_thread(
            fetch_events,
            settings.google_token_path,
            now,
            horizon,
            settings.timezone,
            settings.calendar_id_list,
        )
    except CalendarNotConnected as exc:
        await _handle_calendar_disconnected(context, settings, session_factory, str(exc))
        return
    await _handle_calendar_reconnected(context, settings, session_factory)

    with session_factory() as session:
        to_remind = find_events_needing_reminder(session, events, settings)

    for event in to_remind:
        lead_minutes = max(1, round((event.start - now).total_seconds() / 60))
        await send_formatted(context.bot, settings.owner_user_id, format_reminder(event, lead_minutes))


async def _check_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)  # naive UTC: así se guarda `fire_at`

    with session_factory() as session:
        due = find_due_reminders(session, now)

    for reminder in due:
        await send_formatted(context.bot, settings.owner_user_id, format_adhoc_reminder(reminder))


async def _heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toca un archivo para que el HEALTHCHECK de Docker sepa que el loop de jobs sigue vivo."""
    settings: Settings = context.bot_data["settings"]
    settings.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    settings.heartbeat_path.touch()


async def _backup_database(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    try:
        backup_database(settings.database_path, settings.backup_dir, now)
        prune_old_backups(settings.backup_dir, settings.backup_retention_days, now)
    except Exception:
        logger.exception("Falló el backup de la base de datos")


async def _check_llm_budget(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    current_month = now.strftime("%Y-%m")

    with session_factory() as session:
        if get_preference(session, _BUDGET_ALERT_KEY) == current_month:
            return
        cost = month_to_date_cost_usd(session, now)
        threshold = settings.llm_budget_usd * settings.llm_budget_alert_threshold
        if cost < threshold:
            return
        set_preference(session, _BUDGET_ALERT_KEY, current_month)

    await send_formatted(
        context.bot,
        settings.owner_user_id,
        f"💸 Llevas gastados ${cost:.2f} de los ${settings.llm_budget_usd:.2f} presupuestados "
        f"este mes en el LLM (ya pasaste el {settings.llm_budget_alert_threshold:.0%}).",
    )


async def _poll_canvas(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]

    try:
        items = await fetch_activity_items(settings.canvas_base_url, settings.canvas_access_token)
    except CanvasError:
        logger.exception("Job de Canvas: no se pudo consultar la API, se omite esta corrida")
        return

    with session_factory() as session:
        new_items = find_new_items(session, items)

    for item in new_items:
        await send_formatted(context.bot, settings.owner_user_id, format_activity_notification(item))


def register_jobs(app: Application, settings: Settings) -> None:
    tz = ZoneInfo(settings.timezone)
    app.job_queue.run_daily(
        _send_daily_briefing,
        time=dt.time(hour=settings.briefing_hour, minute=settings.briefing_minute, tzinfo=tz),
        name="daily_briefing",
    )
    app.job_queue.run_daily(
        _send_weekly_briefing,
        time=dt.time(hour=settings.weekly_briefing_hour, minute=settings.weekly_briefing_minute, tzinfo=tz),
        days=(_SUNDAY,),
        name="weekly_briefing",
    )
    app.job_queue.run_repeating(
        _poll_canvas,
        interval=dt.timedelta(minutes=settings.canvas_poll_interval_minutes),
        first=10,
        name="canvas_poll",
    )
    app.job_queue.run_repeating(
        _check_important_events,
        interval=dt.timedelta(minutes=settings.reminder_poll_interval_minutes),
        first=15,
        name="event_reminders",
    )
    app.job_queue.run_repeating(
        _check_due_reminders,
        interval=dt.timedelta(minutes=settings.adhoc_reminder_poll_interval_minutes),
        first=5,
        name="adhoc_reminders",
    )
    app.job_queue.run_repeating(
        _heartbeat,
        interval=dt.timedelta(minutes=settings.heartbeat_interval_minutes),
        first=0,
        name="heartbeat",
    )
    app.job_queue.run_repeating(
        _backup_database,
        interval=dt.timedelta(hours=settings.backup_interval_hours),
        first=60,
        name="db_backup",
    )
    app.job_queue.run_repeating(
        _check_llm_budget,
        interval=dt.timedelta(hours=settings.llm_budget_check_interval_hours),
        first=30,
        name="llm_budget_check",
    )
