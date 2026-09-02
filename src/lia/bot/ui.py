import logging
from io import BytesIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ExtBot

logger = logging.getLogger(__name__)


async def reply_formatted(
    message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Responde intentando Markdown; si el texto tiene entidades mal formadas, reintenta en texto plano.

    El LLM no siempre genera Markdown válido para el modo legado de Telegram
    (asteriscos sin cerrar, guiones bajos sueltos, etc.), así que nunca hay que
    dejar que eso rompa el envío del mensaje.
    """
    try:
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except BadRequest:
        logger.warning("No se pudo parsear Markdown en la respuesta, reenvío en texto plano")
        await message.reply_text(text, reply_markup=reply_markup)


async def send_formatted(bot: ExtBot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest:
        logger.warning("No se pudo parsear Markdown en el mensaje, reenvío en texto plano")
        await bot.send_message(chat_id=chat_id, text=text)


async def edit_formatted(query, text: str) -> None:
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest:
        logger.warning("No se pudo parsear Markdown al editar el mensaje, reenvío en texto plano")
        await query.edit_message_text(text)


async def send_document(
    bot: ExtBot, chat_id: int, data: bytes, filename: str, caption: str | None = None
) -> None:
    """Manda un archivo generado en memoria (sin pasar por disco)."""
    await bot.send_document(
        chat_id=chat_id, document=BytesIO(data), filename=filename, caption=caption
    )


def confirmation_keyboard(tool_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm:{tool_name}"),
                InlineKeyboardButton("✏️ Editar", callback_data=f"edit:{tool_name}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{tool_name}"),
            ]
        ]
    )
