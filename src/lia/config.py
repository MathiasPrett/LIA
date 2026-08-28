from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(description="Token de @BotFather")
    owner_user_id: int = Field(description="Tu user_id numérico de Telegram (de @userinfobot)")

    database_path: Path = Field(default=Path("data/lia.db"))

    log_level: str = Field(default="INFO")

    timezone: str = Field(default="America/Santiago")

    google_credentials_path: Path = Field(default=Path("credentials.json"))
    google_token_path: Path = Field(default=Path("token.json"))
    calendar_ids: str = Field(
        default="primary",
        description=(
            "IDs de calendario a consultar, separados por coma. Cada entrada puede llevar una "
            "etiqueta legible con 'id:etiqueta' (p. ej. 'primary:Personal,xxx@group.calendar.google.com:Compartido'). "
            "Sin etiqueta, se usa el id tal cual."
        ),
    )

    briefing_hour: int = Field(default=7, description="Hora local (0-23) del resumen diario")
    briefing_minute: int = Field(default=0)
    weekly_briefing_hour: int = Field(default=20, description="Hora local (0-23) del resumen semanal (domingo)")
    weekly_briefing_minute: int = Field(default=0)

    gemini_api_key: str = Field(description="API key de Google AI Studio (aistudio.google.com/apikey)")
    gemini_model: str = Field(default="gemini-3.1-flash-lite")

    conversation_history_turns: int = Field(default=15, description="Ventana deslizante de memoria de chat")

    canvas_base_url: str = Field(description="URL base de tu Canvas, ej. https://tuinstitucion.instructure.com")
    canvas_access_token: str = Field(description="Token de acceso personal de Canvas")
    canvas_poll_interval_minutes: int = Field(default=20)

    reminder_lead_minutes: int = Field(default=60, description="Cuánto antes de un evento importante avisar")
    reminder_poll_interval_minutes: int = Field(default=10)
    important_min_duration_minutes: int = Field(
        default=90, description="Duración a partir de la cual un evento se considera importante"
    )
    important_min_attendees: int = Field(
        default=3, description="Cantidad de invitados a partir de la cual un evento se considera importante"
    )
    important_keywords: str = Field(
        default="examen,entrega,presentación,certamen",
        description="Palabras clave (separadas por coma) que marcan un evento como importante si aparecen en el título",
    )
    important_calendar_ids: str = Field(
        default="",
        description="IDs de calendario cuyos eventos siempre se consideran importantes (separados por coma, vacío = ninguno)",
    )

    planner_day_start_hour: int = Field(default=8, description="Hora local de inicio de la jornada para buscar huecos libres")
    planner_day_end_hour: int = Field(default=22, description="Hora local de fin de la jornada para buscar huecos libres")

    adhoc_reminder_poll_interval_minutes: int = Field(default=1)

    # Integraciones opcionales de la Fase 5: si faltan, el resto del bot sigue
    # funcionando y solo esa función puntual avisa que no está configurada.
    groq_api_key: str = Field(default="", description="API key de Groq (console.groq.com/keys), para notas de voz")
    weather_latitude: float | None = Field(default=None)
    weather_longitude: float | None = Field(default=None)

    # Fase 6: endurecimiento
    heartbeat_path: Path = Field(default=Path("data/heartbeat"))
    heartbeat_interval_minutes: int = Field(default=2)

    backup_dir: Path = Field(default=Path("data/backups"))
    backup_interval_hours: int = Field(default=24)
    backup_retention_days: int = Field(default=7)

    llm_budget_usd: float = Field(default=1.0, description="Presupuesto mensual del LLM en USD")
    llm_budget_alert_threshold: float = Field(
        default=0.8, description="Fracción del presupuesto (0-1) a partir de la cual avisar"
    )
    llm_budget_check_interval_hours: int = Field(default=6)

    def _calendar_entries(self) -> list[tuple[str, str]]:
        entries = []
        for raw in self.calendar_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            calendar_id, _, label = raw.partition(":")
            entries.append((calendar_id.strip(), label.strip() or calendar_id.strip()))
        return entries

    @property
    def calendar_id_list(self) -> list[str]:
        return [calendar_id for calendar_id, _ in self._calendar_entries()]

    @property
    def calendar_labels(self) -> dict[str, str]:
        return dict(self._calendar_entries())

    @property
    def important_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.important_keywords.split(",") if k.strip()]

    @property
    def important_calendar_id_list(self) -> list[str]:
        return [c.strip() for c in self.important_calendar_ids.split(",") if c.strip()]


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
