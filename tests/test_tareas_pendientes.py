"""Tool `tareas_pendientes`: unifica Canvas + Google Tasks.

El bug que originó estos tests: no existía forma de leer Google Tasks, y el modelo
respondía "no tienes nada" afirmando haber revisado. De ahí que lo central acá sea
que un fallo de consulta NO se vea igual que una lista vacía.
"""

import asyncio
import datetime as dt

import pytest

from lia.config import Settings
from lia.db import make_engine, make_session_factory
from lia.integrations.canvas import CanvasAssignment, CanvasError
from lia.integrations.google_calendar import CalendarNotConnected
from lia.integrations.google_tasks import TaskItem
from lia.llm import tools as tools_module
from lia.llm.tools import build_tools
from lia.services.canvas_ignore import ignore_course

TZ = dt.timezone.utc


def _settings():
    return Settings(
        _env_file=None,
        telegram_bot_token="x",
        owner_user_id=1,
        gemini_api_key="x",
        canvas_base_url="https://canvas.example.com",
        canvas_access_token="x",
    )


def _tool(monkeypatch, *, assignments=None, tasks=None, canvas_exc=None, tasks_exc=None):
    session_factory = make_session_factory(make_engine(":memory:"))

    async def fake_assignments(base_url, token):
        if canvas_exc:
            raise canvas_exc
        return assignments or []

    def fake_tasks(token_path):
        if tasks_exc:
            raise tasks_exc
        return tasks or []

    monkeypatch.setattr(tools_module, "fetch_pending_assignments", fake_assignments)
    monkeypatch.setattr(tools_module, "fetch_tasks", fake_tasks)

    registry = build_tools(_settings(), session_factory)
    return registry.get("tareas_pendientes"), session_factory


def _assignment(name, course="Diseño de Software"):
    return CanvasAssignment(
        name=name, course_name=course, due_at=dt.datetime(2026, 9, 6, 15, 0, tzinfo=TZ), html_url=None
    )


def test_devuelve_las_dos_fuentes_por_separado(monkeypatch):
    tool, _ = _tool(
        monkeypatch,
        assignments=[_assignment("Domino MVC")],
        tasks=[TaskItem(id="a", title="Revisiones de pares", notes=None, due=dt.date(2026, 9, 5))],
    )

    r = asyncio.run(tool.handler())

    assert [t["nombre"] for t in r["canvas"]] == ["Domino MVC"]
    assert [t["titulo"] for t in r["google_tasks"]] == ["Revisiones de pares"]
    assert r["google_tasks"][0]["vence"] == "2026-09-05"


def test_tarea_sin_fecha_viaja_con_vence_none(monkeypatch):
    # Es el caso real: la tarea existe pero no vence ningún día. Tiene que llegar
    # al modelo como null, no desaparecer ni asumirse como "vence hoy".
    tool, _ = _tool(
        monkeypatch, tasks=[TaskItem(id="a", title="Empezar Entrega 2", notes=None, due=None)]
    )

    r = asyncio.run(tool.handler())

    assert r["google_tasks"] == [{"titulo": "Empezar Entrega 2", "vence": None, "notas": None}]


def test_sigue_filtrando_los_cursos_ignorados_de_canvas(monkeypatch):
    tool, session_factory = _tool(
        monkeypatch,
        assignments=[_assignment("Tarea visible", "Redes"), _assignment("Tarea muda", "Cálculo III")],
    )
    with session_factory() as session:
        ignore_course(session, "Cálculo III")

    r = asyncio.run(tool.handler())

    assert [t["nombre"] for t in r["canvas"]] == ["Tarea visible"]


def test_si_google_tasks_falla_devuelve_error_y_no_lista_vacia(monkeypatch):
    # El corazón del bug: "no pude consultar" tiene que ser distinguible de "no hay nada".
    tool, _ = _tool(
        monkeypatch,
        assignments=[_assignment("Domino MVC")],
        tasks_exc=CalendarNotConnected("No se encontró token.json."),
    )

    r = asyncio.run(tool.handler())

    assert "error" in r["google_tasks"]
    assert r["google_tasks"] != []
    assert len(r["canvas"]) == 1  # el fallo de una fuente no arrastra a la otra


def test_si_canvas_falla_google_tasks_igual_responde(monkeypatch):
    tool, _ = _tool(
        monkeypatch,
        canvas_exc=CanvasError("500 desde Canvas"),
        tasks=[TaskItem(id="a", title="Sigue viva", notes=None, due=None)],
    )

    r = asyncio.run(tool.handler())

    assert "error" in r["canvas"]
    assert [t["titulo"] for t in r["google_tasks"]] == ["Sigue viva"]


def test_ambas_vacias_devuelven_listas_vacias_sin_error(monkeypatch):
    tool, _ = _tool(monkeypatch)

    r = asyncio.run(tool.handler())

    assert r == {"canvas": [], "google_tasks": []}


@pytest.mark.parametrize("nombre", ["tareas_pendientes"])
def test_la_tool_esta_registrada_con_el_nombre_unificado(monkeypatch, nombre):
    tool, _ = _tool(monkeypatch)
    assert tool.name == nombre
