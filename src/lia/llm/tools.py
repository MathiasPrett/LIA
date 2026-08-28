import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy.orm import sessionmaker

from lia.config import Settings
from lia.db import Reminder
from lia.integrations.canvas import fetch_activity_items, fetch_pending_assignments
from lia.integrations.google_calendar import fetch_events, insert_event
from lia.integrations.weather import WeatherError, fetch_daily_forecast
from lia.llm.registry import Tool, ToolRegistry
from lia.services.planner import find_free_slots

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _event_to_dict(event) -> dict:
    return {
        "titulo": event.summary,
        "inicio": event.start.isoformat(),
        "fin": event.end.isoformat(),
        "todo_el_dia": event.all_day,
        "ubicacion": event.location,
        "descripcion": event.description,
    }


def build_tools(settings: Settings, session_factory: sessionmaker) -> ToolRegistry:
    registry = ToolRegistry()

    async def listar_eventos(desde: str, hasta: str) -> dict:
        tz = ZoneInfo(settings.timezone)
        start_date = dt.date.fromisoformat(desde)
        end_date = dt.date.fromisoformat(hasta)
        time_min = dt.datetime.combine(start_date, dt.time.min, tzinfo=tz)
        time_max = dt.datetime.combine(end_date, dt.time.max, tzinfo=tz)

        events = await asyncio.to_thread(
            fetch_events,
            settings.google_token_path,
            time_min,
            time_max,
            settings.timezone,
            settings.calendar_id_list,
        )
        return {"eventos": [_event_to_dict(e) for e in events]}

    registry.register(
        Tool(
            name="listar_eventos",
            description=(
                "Lista los eventos del calendario en un rango de fechas (inclusive). "
                "Incluye el calendario personal y cualquier calendario compartido configurado."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "desde": {"type": "string", "description": "Fecha ISO 8601 (YYYY-MM-DD) de inicio del rango"},
                    "hasta": {"type": "string", "description": "Fecha ISO 8601 (YYYY-MM-DD) de fin del rango, inclusive"},
                },
                "required": ["desde", "hasta"],
            },
            handler=listar_eventos,
        )
    )

    calendar_labels = settings.calendar_labels

    async def crear_evento(
        titulo: str,
        inicio: str,
        fin: str,
        ubicacion: str | None = None,
        descripcion: str | None = None,
        calendario: str | None = None,
    ) -> dict:
        start = dt.datetime.fromisoformat(inicio)
        end = dt.datetime.fromisoformat(fin)
        calendar_id = calendario if calendario in settings.calendar_id_list else "primary"
        event = await asyncio.to_thread(
            insert_event,
            settings.google_token_path,
            calendar_id,
            titulo,
            start,
            end,
            settings.timezone,
            ubicacion,
            descripcion,
        )
        return _event_to_dict(event)

    def _crear_evento_summary(args: dict) -> str:
        start = dt.datetime.fromisoformat(args["inicio"])
        end = dt.datetime.fromisoformat(args["fin"])
        dia = _DIAS[start.weekday()]
        line = (
            f"📅 {args['titulo']}\n"
            f"🕐 {dia} {start.strftime('%d/%m')}, {start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
        )
        if args.get("ubicacion"):
            line += f"\n📍 {args['ubicacion']}"
        if args.get("descripcion"):
            line += f"\n📝 {args['descripcion']}"
        calendario = args.get("calendario")
        if calendario and calendario != "primary":
            line += f"\n🗓️ {calendar_labels.get(calendario, calendario)}"
        return line

    registry.register(
        Tool(
            name="crear_evento",
            description=(
                "Crea un evento nuevo en el calendario. Por defecto va al calendario personal "
                "('primary'); usá el parámetro calendario solo si el usuario pide explícitamente "
                "agregarlo a otro de los calendarios disponibles."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "inicio": {
                        "type": "string",
                        "description": "Fecha y hora de inicio en ISO 8601 con offset de zona horaria",
                    },
                    "fin": {
                        "type": "string",
                        "description": "Fecha y hora de término en ISO 8601 con offset de zona horaria",
                    },
                    "ubicacion": {"type": "string", "description": "Lugar del evento (opcional)"},
                    "descripcion": {"type": "string", "description": "Notas o detalles adicionales (opcional)"},
                    "calendario": {
                        "type": "string",
                        "description": (
                            "Calendario donde crear el evento (opcional, por defecto 'primary'). "
                            "Calendarios disponibles: "
                            + ", ".join(f"'{cid}' ({label})" for cid, label in calendar_labels.items())
                        ),
                        "enum": settings.calendar_id_list,
                    },
                },
                "required": ["titulo", "inicio", "fin"],
            },
            handler=crear_evento,
            requires_confirmation=True,
            confirmation_summary=_crear_evento_summary,
        )
    )

    async def canvas_tareas_pendientes() -> dict:
        assignments = await fetch_pending_assignments(settings.canvas_base_url, settings.canvas_access_token)
        return {
            "tareas": [
                {
                    "nombre": a.name,
                    "curso": a.course_name,
                    "vence": a.due_at.isoformat() if a.due_at else None,
                }
                for a in assignments
            ]
        }

    registry.register(
        Tool(
            name="canvas_tareas_pendientes",
            description="Lista las tareas/entregas pendientes en Canvas, ordenadas por fecha de vencimiento.",
            parameters={"type": "object", "properties": {}},
            handler=canvas_tareas_pendientes,
        )
    )

    async def canvas_novedades(desde: str) -> dict:
        items = await fetch_activity_items(settings.canvas_base_url, settings.canvas_access_token)
        since = dt.datetime.fromisoformat(desde)
        if since.tzinfo is None:
            since = since.replace(tzinfo=dt.timezone.utc)
        recientes = [i for i in items if i.updated_at >= since]
        return {
            "novedades": [
                {
                    "tipo": i.kind,
                    "titulo": i.title,
                    "curso": i.course_name,
                    "fecha": i.updated_at.isoformat(),
                }
                for i in recientes
            ]
        }

    registry.register(
        Tool(
            name="canvas_novedades",
            description="Lista avisos, mensajes y otra actividad reciente de Canvas desde una fecha dada.",
            parameters={
                "type": "object",
                "properties": {
                    "desde": {
                        "type": "string",
                        "description": "Fecha ISO 8601 desde la cual buscar novedades (ej. 2026-08-20)",
                    },
                },
                "required": ["desde"],
            },
            handler=canvas_novedades,
        )
    )

    async def buscar_huecos_libres(desde: str, hasta: str, duracion_minutos: int) -> dict:
        tz = ZoneInfo(settings.timezone)
        range_start = dt.datetime.fromisoformat(desde)
        range_end = dt.datetime.fromisoformat(hasta)
        if range_start.tzinfo is None:
            range_start = range_start.replace(tzinfo=tz)
        if range_end.tzinfo is None:
            range_end = range_end.replace(tzinfo=tz)

        events = await asyncio.to_thread(
            fetch_events,
            settings.google_token_path,
            range_start,
            range_end,
            settings.timezone,
            settings.calendar_id_list,
        )
        slots = find_free_slots(
            events,
            range_start,
            range_end,
            duracion_minutos,
            settings.planner_day_start_hour,
            settings.planner_day_end_hour,
        )
        return {
            "huecos": [{"inicio": start.isoformat(), "fin": end.isoformat()} for start, end in slots]
        }

    registry.register(
        Tool(
            name="buscar_huecos_libres",
            description=(
                "Busca bloques de tiempo libre de al menos cierta duración dentro de un rango de "
                "fechas, considerando los eventos ya agendados y el horario habitual del día "
                f"({settings.planner_day_start_hour}:00 a {settings.planner_day_end_hour}:00). "
                "Útil para proponer un plan de estudio o de trabajo."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "desde": {
                        "type": "string",
                        "description": "Inicio del rango en ISO 8601 con offset de zona horaria",
                    },
                    "hasta": {
                        "type": "string",
                        "description": "Fin del rango en ISO 8601 con offset de zona horaria",
                    },
                    "duracion_minutos": {"type": "integer", "description": "Duración mínima del bloque, en minutos"},
                },
                "required": ["desde", "hasta", "duracion_minutos"],
            },
            handler=buscar_huecos_libres,
        )
    )

    async def crear_recordatorio(texto: str, cuando: str) -> dict:
        when = dt.datetime.fromisoformat(cuando)
        if when.tzinfo is None:
            when = when.replace(tzinfo=ZoneInfo(settings.timezone))
        fire_at_utc = when.astimezone(dt.UTC).replace(tzinfo=None)

        with session_factory() as session:
            session.add(Reminder(text=texto, fire_at=fire_at_utc, status="pending"))
            session.commit()

        return {"texto": texto, "cuando": when.isoformat()}

    registry.register(
        Tool(
            name="crear_recordatorio",
            description=(
                "Crea un recordatorio suelto que se avisa por Telegram en la fecha y hora indicadas. "
                "No es un evento de calendario, es solo un aviso puntual. Se aplica directo, sin "
                "pedir confirmación (es reversible y de bajo riesgo)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Qué recordar"},
                    "cuando": {
                        "type": "string",
                        "description": "Fecha y hora en ISO 8601 con offset de zona horaria",
                    },
                },
                "required": ["texto", "cuando"],
            },
            handler=crear_recordatorio,
        )
    )

    async def clima(fecha: str) -> dict:
        if settings.weather_latitude is None or settings.weather_longitude is None:
            return {"error": "El usuario todavía no configuró su ubicación (WEATHER_LATITUDE/WEATHER_LONGITUDE)."}

        target_date = dt.date.fromisoformat(fecha)
        try:
            forecast = await fetch_daily_forecast(
                settings.weather_latitude, settings.weather_longitude, settings.timezone
            )
        except WeatherError as exc:
            return {"error": str(exc)}

        for day in forecast:
            if day.date == target_date:
                return {
                    "fecha": day.date.isoformat(),
                    "temperatura_maxima": day.temp_max,
                    "temperatura_minima": day.temp_min,
                    "probabilidad_de_lluvia": day.precipitation_probability,
                    "condicion": day.condition,
                }

        return {"error": f"No hay pronóstico disponible para {fecha} (solo días cercanos a hoy)."}

    registry.register(
        Tool(
            name="clima",
            description="Da el pronóstico del clima (temperatura, probabilidad de lluvia) para una fecha dada.",
            parameters={
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "Fecha ISO 8601 (YYYY-MM-DD)"},
                },
                "required": ["fecha"],
            },
            handler=clima,
        )
    )

    return registry
