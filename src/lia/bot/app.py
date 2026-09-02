from sqlalchemy.orm import sessionmaker
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from lia.bot import handlers
from lia.config import Settings
from lia.llm.base import LLMProvider
from lia.llm.registry import ToolRegistry


def build_application(
    settings: Settings,
    session_factory: sessionmaker,
    llm_provider: LLMProvider,
    tools: ToolRegistry | None = None,
) -> Application:
    """`tools` puede venir vacío y asignarse después en `bot_data`: hace falta para que
    las tools se construyan con una referencia al bot ya creado (ver `__main__.py`).
    Los handlers leen `bot_data["tools"]` recién en tiempo de ejecución."""
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["session_factory"] = session_factory
    app.bot_data["llm_provider"] = llm_provider
    app.bot_data["tools"] = tools

    owner_only = handlers.OwnerFilter(settings.owner_user_id)

    app.add_handler(CommandHandler("start", handlers.start, filters=owner_only))
    app.add_handler(CommandHandler("ping", handlers.ping, filters=owner_only))
    app.add_handler(CommandHandler("hoy", handlers.hoy, filters=owner_only))
    app.add_handler(CommandHandler("semana", handlers.semana, filters=owner_only))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & owner_only, handlers.mensaje_libre)
    )
    app.add_handler(MessageHandler(filters.VOICE & owner_only, handlers.nota_de_voz))
    app.add_handler(CallbackQueryHandler(handlers.confirmar_accion))
    app.add_error_handler(handlers.error_handler)

    return app
