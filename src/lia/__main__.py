import logging

from lia.bot.app import build_application
from lia.config import load_settings
from lia.db import make_engine, make_session_factory
from lia.llm.gemini import GeminiProvider
from lia.llm.tools import build_tools
from lia.scheduler import register_jobs


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(str(settings.database_path))
    session_factory = make_session_factory(engine)

    llm_provider = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    tools = build_tools(settings, session_factory)

    app = build_application(settings, session_factory, llm_provider, tools)
    register_jobs(app, settings)
    app.run_polling()


if __name__ == "__main__":
    main()
