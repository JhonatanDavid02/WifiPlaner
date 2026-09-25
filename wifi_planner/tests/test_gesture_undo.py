"""Fase 14.1: un gesto interactivo (arrastre) = UNA entrada de historial.

El lienzo abre el gesto con ``begin_edit`` en ``<ButtonPress-1>`` cuando
hay un arrastre en marcha y lo cierra con ``commit_edit`` en
``<ButtonRelease-1>`` (``ui/editor_canvas.py``); mientras tanto las
operaciones ``@undoable`` se ejecutan sin apilar snapshots. Escape
cancela el gesto con ``cancel_edit`` (``ui/app.py``).

Estas pruebas ejercitan el mecanismo a nivel de ``EditorSession`` (sin
abrir Tkinter) sobre las entidades editoriales principales: AP,
cliente, obstáculo, espacio y extremo de pared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.geometry import Point2D, Rect
from tests.factories import make_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ready_session():
    """Sesión 10×10 con un AP de referencia y el historial ya medido."""
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    return session


def _steps(session) -> int:
    """Entradas actuales del historial de deshacer."""
    return len(session._undo_stack)


def _ap(session, ap_id: str):
    return next(ap for ap in session.project.access_points if ap.id == ap_id)


def _obstacle(session, obstacle_id: str):
    return next(
        item
        for item in session.floor.obstacles
        if item.id == obstacle_id
    )


def _space(session, space_id: str):
    return next(item for item in session.floor.spaces if item.id == space_id)


def _wall(session, wall_id: str):
    return session.find_wall(wall_id)


def _client(session, client_id: str):
    return next(c for c in session.project.clients if c.id == client_id)


# ---------------------------------------------------------------------------
# Tests A–E: una entidad por test ⇒ UN solo paso de undo por arrastre
# ---------------------------------------------------------------------------

def test_drag_ap_is_single_undo_step():
    session = _ready_session()
    ap = session.add_access_point(Point2D(2.0, 5.0))
    before = _steps(session)

    session.begin_edit()
    for x in (2.5, 3.0, 3.5, 4.0):  # 4 movimientos = 1 gesto
        session.move_ap(ap.id, Point2D(x, 5.0))
    # Sin snapshots intermedios mientras el gesto está abierto.
    assert _steps(session) == before

    assert session.commit_edit() is True
    assert _steps(session) == before + 1  # UNA sola entrada
    assert _ap(session, ap.id).position == Point2D(4.0, 5.0)

    assert session.undo() is True
    assert _ap(session, ap.id).position == Point2D(2.0, 5.0)
    assert session.redo() is True
    assert _ap(session, ap.id).position == Point2D(4.0, 5.0)


def test_drag_client_is_single_undo_step():
    session = _ready_session()
    client = session.add_client(Point2D(1.0, 1.0))
    before = _steps(session)

    session.begin_edit()
    for point in (Point2D(2.0, 2.0), Point2D(3.0, 3.0), Point2D(4.0, 4.0)):
        session.move_client(client.id, point)
    assert _steps(session) == before

    assert session.commit_edit() is True
    assert _steps(session) == before + 1
    assert _client(session, client.id).position == Point2D(4.0, 4.0)

    session.undo()
    assert _client(session, client.id).position == Point2D(1.0, 1.0)
    session.redo()
    assert _client(session, client.id).position == Point2D(4.0, 4.0)


def test_drag_obstacle_is_single_undo_step():
    session = _ready_session()
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    before = _steps(session)

    session.begin_edit()
    for x in (1.0, 2.0, 3.0):
        session.move_obstacle(obstacle.id, Point2D(float(x), 1.0))
    assert _steps(session) == before

    assert session.commit_edit() is True
    assert _steps(session) == before + 1
    assert _obstacle(session, obstacle.id).rect.x == pytest.approx(3.0)

    session.undo()
    assert _obstacle(session, obstacle.id).rect.x == pytest.approx(0.0)
    session.redo()
    assert _obstacle(session, obstacle.id).rect.x == pytest.approx(3.0)


def test_drag_space_is_single_undo_step():
    session = _ready_session()
    space = session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    before = _steps(session)

    session.begin_edit()
    for delta in (0.5, 1.0, 1.5):  # deltas acumulados durante el arrastre
        session.move_space(space.id, Point2D(delta, 0.0))
    assert _steps(session) == before

    assert session.commit_edit() is True
    assert _steps(session) == before + 1
    assert _space(session, space.id).rect.x == pytest.approx(4.0)

    session.undo()
    assert _space(session, space.id).rect.x == pytest.approx(1.0)
    session.redo()
    assert _space(session, space.id).rect.x == pytest.approx(4.0)


def test_drag_wall_endpoint_is_single_undo_step():
    session = _ready_session()
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(6.0, 0.0))
    before = _steps(session)

    session.begin_edit()
    for end_x in (5.0, 4.0, 3.0, 2.0):
        session.set_wall_endpoints(
            wall.id, Point2D(0.0, 0.0), Point2D(float(end_x), 0.0)
        )
    assert _steps(session) == before

    assert session.commit_edit() is True
    assert _steps(session) == before + 1
    assert _wall(session, wall.id).segment.end == Point2D(2.0, 0.0)

    session.undo()
    assert _wall(session, wall.id).segment.end == Point2D(6.0, 0.0)
    session.redo()
    assert _wall(session, wall.id).segment.end == Point2D(2.0, 0.0)


# ---------------------------------------------------------------------------
# Mecanismo: gestos sin efecto, cancelación y compatibilidad
# ---------------------------------------------------------------------------

def test_gesture_without_edits_records_nothing():
    session = _ready_session()
    session.add_access_point(Point2D(2.0, 5.0))
    before = _steps(session)
    dirty_before = session.dirty

    session.begin_edit()
    assert session.gesture_active is True
    assert session.commit_edit() is False
    assert session.gesture_active is False
    assert _steps(session) == before
    assert session.dirty == dirty_before


def test_gesture_returning_to_start_records_nothing():
    session = _ready_session()
    ap = session.add_access_point(Point2D(2.0, 5.0))
    before = _steps(session)
    dirty_before = session.dirty

    session.begin_edit()
    session.move_ap(ap.id, Point2D(5.0, 5.0))
    session.move_ap(ap.id, Point2D(2.0, 5.0))  # vuelve al punto de partida
    assert session.commit_edit() is False
    assert _steps(session) == before
    assert _ap(session, ap.id).position == Point2D(2.0, 5.0)
    assert session.dirty == dirty_before


def test_cancel_edit_restores_initial_state_without_history():
    session = _ready_session()
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    before = _steps(session)
    dirty_before = session.dirty

    session.begin_edit()
    session.move_obstacle(obstacle.id, Point2D(4.0, 4.0))
    assert session.gesture_active is True
    session.cancel_edit()

    assert session.gesture_active is False
    assert _steps(session) == before
    assert _obstacle(session, obstacle.id).rect.x == pytest.approx(0.0)
    assert session.dirty == dirty_before


def test_cancel_edit_is_noop_without_gesture():
    session = _ready_session()
    session.add_access_point(Point2D(2.0, 5.0))
    before = _steps(session)
    session.cancel_edit()  # no debe tocar nada
    assert _steps(session) == before


def test_commit_edit_is_noop_without_gesture():
    session = _ready_session()
    before = _steps(session)
    assert session.commit_edit() is False
    assert _steps(session) == before


def test_nested_begin_keeps_the_original_snapshot():
    session = _ready_session()
    ap = session.add_access_point(Point2D(2.0, 5.0))
    before = _steps(session)

    session.begin_edit()
    session.move_ap(ap.id, Point2D(3.0, 5.0))
    session.begin_edit()  # anidado: no reinicia la foto inicial
    session.move_ap(ap.id, Point2D(6.0, 5.0))
    assert session.commit_edit() is True
    assert _steps(session) == before + 1

    session.undo()  # un solo undo vuelve al estado PRE-gesto
    assert _ap(session, ap.id).position == Point2D(2.0, 5.0)


def test_undo_during_gesture_cancels_it():
    session = _ready_session()
    ap = session.add_access_point(Point2D(2.0, 5.0))
    before = _steps(session)

    session.begin_edit()
    session.move_ap(ap.id, Point2D(7.0, 7.0))
    assert session.undo() is True  # cancela el gesto en curso

    assert session.gesture_active is False
    assert _steps(session) == before  # las pilas no cambiaron
    assert _ap(session, ap.id).position == Point2D(2.0, 5.0)
    assert session.commit_edit() is False  # el gesto ya estaba cerrado


def test_regular_operations_still_record_one_step_each():
    session = _ready_session()
    before = _steps(session)

    session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.move_ap(ap.id, Point2D(2.0, 2.0))
    session.set_wall_material(
        session.floor.walls[0].id, "concrete"
    )

    # Fuera de un gesto el comportamiento F14-G no cambia.
    assert _steps(session) == before + 4


def test_clear_history_resets_open_gesture():
    session = _ready_session()
    ap = session.add_access_point(Point2D(2.0, 5.0))
    session.begin_edit()
    session.move_ap(ap.id, Point2D(6.0, 6.0))

    session.clear_history()  # documento nuevo/abierto

    assert session.gesture_active is False
    assert session.commit_edit() is False
    assert _steps(session) == 0
    # La edición ya aplicada no se revierte: solo se descarta el gesto.
    assert _ap(session, ap.id).position == Point2D(6.0, 6.0)


def test_consecutive_gestures_record_one_step_each():
    session = _ready_session()
    ap = session.add_access_point(Point2D(1.0, 1.0))
    before = _steps(session)

    for index in range(3):
        session.begin_edit()
        for step in range(5):  # 5 movimientos por gesto
            session.move_ap(ap.id, Point2D(1.0 + index + step * 0.1, 1.0))
        assert session.commit_edit() is True

    # 3 gestos = 3 entradas: UNA por gesto, ni más ni menos.
    assert _steps(session) == before + 3


def test_canvas_opens_and_closes_gesture_on_drag():
    source = (
        Path(__file__).resolve().parents[1] / "ui" / "editor_canvas.py"
    ).read_text(encoding="utf-8")
    assert "begin_edit()" in source
    assert "commit_edit()" in source


def test_app_cancels_gesture_on_escape():
    source = (Path(__file__).resolve().parents[1] / "ui" / "app.py").read_text(
        encoding="utf-8"
    )
    assert "cancel_edit()" in source


def test_rect_and_selection_untouched_outside_gesture():
    session = _ready_session()
    space = session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    before = _steps(session)

    session.begin_edit()
    session.set_space_rect(space.id, Rect(x=6.0, y=6.0, width=2.0, height=2.0))
    assert session.commit_edit() is True
    assert _steps(session) == before + 1

    session.undo()
    restored = _space(session, space.id)
    assert restored.rect.x == pytest.approx(1.0)
    assert restored.rect.y == pytest.approx(1.0)
