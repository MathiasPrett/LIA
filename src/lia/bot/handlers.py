import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes, filters

from lia.bot.ui import confirmation_keyboard, edit_formatted, reply_formatted
from lia.config import Settings
from lia.integrations.canvas import CanvasError, fetch_pending_assignments
from lia.integrations.google_calendar import CalendarNotConnected, fetch_events
from lia.integrations.transcribe import TranscriptionError, transcribe_audio
from lia.llm.base import PendingConfirmation
from lia.llm.prompts import build_system_prompt
from lia.llm.registry import ToolRegistry
from lia.services.briefing import format_daily_briefing, format_weekly_briefing
from lia.services.conversation import handle_user_message, save_turn

logger = logging.getLogger(__name__)


class OwnerFilter(filters.MessageFilter):
    """Deja pasar únicamente mensajes del user_id autorizado. Todo lo demás se descarta en silencio."""

    def __init__(self, owner_user_id: int) -> None:
        super().__init__(name="OwnerFilter")
        self._owner_user_id = owner_user_id

    def filter(self, message) -> bool:
        sender_id = message.from_user.id if message.from_user else None
        if sender_id != self._owner_user_id:
            logger.warning("Mensaje ignorado de usuario no autorizado: %s", sender_id)
            return False
        return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hola, soy LIA. Todavía estoy en construcción.")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


def _today_range(settings: Settings) -> tuple[dt.date, dt.datetime, dt.datetime]:
    tz = ZoneInfo(settings.timezone)
    today = dt.datetime.now(tz).date()
    time_min = dt.datetime.combine(today, dt.time.min, tzinfo=tz)
    time_max = dt.datetime.combine(today, dt.time.max, tzinfo=tz)
    return today, time_min, time_max


def _this_week_range(settings: Settings) -> tuple[dt.date, dt.datetime, dt.datetime]:
    tz = ZoneInfo(settings.timezone)
    today = dt.datetime.now(tz).date()
    week_start = today - dt.timedelta(days=today.weekday())
    week_end = week_start + dt.timedelta(days=6)
    time_min = dt.datetime.combine(week_start, dt.time.min, tzinfo=tz)
    time_max = dt.datetime.combine(week_end, dt.time.max, tzinfo=tz)
    return week_start, time_min, time_max


async def hoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    today, time_min, time_max = _today_range(settings)

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
        await update.message.reply_text(str(exc))
        return

    try:
        pending_assignments = await fetch_pending_assignments(
            settings.canvas_base_url, settings.canvas_access_token
        )
    except CanvasError:
        logger.exception("No se pudo consultar Canvas para /hoy, sigo solo con el calendario")
        pending_assignments = []

    await reply_formatted(
        update.message, format_daily_briefing(events, today, pending_assignments, settings.timezone)
    )


async def semana(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    week_start, time_min, time_max = _this_week_range(settings)

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
        await update.message.reply_text(str(exc))
        return

    try:
        pending_assignments = await fetch_pending_assignments(
            settings.canvas_base_url, settings.canvas_access_token
        )
    except CanvasError:
        logger.exception("No se pudo consultar Canvas para /semana, sigo solo con el calendario")
        pending_assignments = []

    await reply_formatted(
        update.message,
        format_weekly_briefing(events, week_start, pending_assignments, settings.timezone),
    )


async def _procesar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str) -> None:
    settings: Settings = context.bot_data["settings"]
    session_factory = context.bot_data["session_factory"]
    tools: ToolRegistry = context.bot_data["tools"]
    provider = context.bot_data["llm_provider"]

    with session_factory() as session:
        result = await handle_user_message(
            session=session,
            provider=provider,
            system_prompt=build_system_prompt(settings),
            tools=tools.all(),
            model=settings.gemini_model,
            history_turns=settings.conversation_history_turns,
            user_message=texto,
        )

    if result.pending_confirmation is not None:
        context.user_data["pending_confirmation"] = result.pending_confirmation
        text = result.pending_confirmation.summary
        if result.reply_text:
            text = f"{result.reply_text}\n\n{text}"
        await reply_formatted(
            update.message, text, reply_markup=confirmation_keyboard(result.pending_confirmation.tool_name)
        )
        return

    await reply_formatted(
        update.message, result.reply_text or "No tengo nada que decir a eso, intenta de otra forma."
    )


async def mensaje_libre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _procesar_texto(update, context, update.message.text)


async def nota_de_voz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]

    if not settings.groq_api_key:
        await update.message.reply_text(
            "Todavía no configuraste GROQ_API_KEY, así que no puedo transcribir audios."
        )
        return

    file = await update.message.voice.get_file()
    audio_bytes = bytes(await file.download_as_bytearray())

    try:
        texto = await transcribe_audio(audio_bytes, settings.groq_api_key)
    except TranscriptionError:
        logger.exception("Falló la transcripción de la nota de voz")
        await update.message.reply_text("No pude transcribir el audio, intenta escribirlo como texto.")
        return

    await _procesar_texto(update, context, texto)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Red de seguridad: si algún handler deja pasar una excepción, se loguea y se avisa
    al usuario en vez de dejarlo sin respuesta (p. ej. un 503 de Gemini por alta demanda)."""
    logger.error("Excepción no manejada procesando un update: %s", update, exc_info=context.error)

    settings: Settings | None = context.bot_data.get("settings")
    if settings is None:
        return

    try:
        await context.bot.send_message(
            settings.owner_user_id,
            "Tuve un problema procesando eso (puede ser que el modelo de IA esté con alta demanda "
            "en este momento). Intenta de nuevo en unos segundos.",
        )
    except Exception:
        logger.exception("Encima falló el aviso de error al usuario")


async def confirmar_accion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not query.from_user or query.from_user.id != settings.owner_user_id:
        return

    action, _, tool_name = query.data.partition(":")
    pending: PendingConfirmation | None = context.user_data.get("pending_confirmation")

    if pending is None or pending.tool_name != tool_name:
        await query.edit_message_text("Esa confirmación ya expiró. Pídemelo de nuevo.")
        return

    context.user_data.pop("pending_confirmation", None)

    if action == "cancel":
        await query.edit_message_text("Cancelado, no se hizo ningún cambio.")
        return

    if action == "edit":
        await query.edit_message_text("Dime qué quieres cambiar y te propongo el evento de nuevo.")
        return

    tools: ToolRegistry = context.bot_data["tools"]
    session_factory = context.bot_data["session_factory"]
    tool = tools.get(tool_name)

    try:
        result = await tool.handler(**pending.arguments)
    except Exception:
        logger.exception("Falló la ejecución de %s tras confirmar", tool_name)
        await query.edit_message_text("Algo falló al aplicar el cambio en el calendario. Intenta de nuevo.")
        return

    with session_factory() as session:
        save_turn(
            session,
            "assistant",
            f"Evento creado: {result.get('titulo')} ({result.get('inicio')} - {result.get('fin')}).",
        )

    await edit_formatted(query, f"✅ Listo, agendado:\n{pending.summary}")
