"""Fase 14-G: deshacer/rehacer por snapshots del documento.

Cada operación mutante decorada con ``@undoable`` guarda una copia
profunda del Project (más la selección) ANTES de ejecutar y solo la
confirma si no hubo excepción. Undo/redo no re-grabarán historial.
"""

from __future__ import annotations

import pytest

from core.geometry import Point2D, Rect
from tests.factories import make_session
from ui.session import MAX_UNDO_STEPS, SelectionKind


def test_history_starts_empty():
    session = make_session()
    assert session.can_undo() is False
    assert session.can_redo() is False
    assert session.undo() is False
    assert session.redo() is False


def test_undo_removes_added_wall():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    assert len(session.floor.walls) == 1
    assert session.can_undo() is True
    assert session.undo() is True
    assert session.floor.walls == []
    assert session.can_redo() is True


def test_redo_restores_added_wall_with_same_id():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.undo()
    assert session.redo() is True
    assert [w.id for w in session.floor.walls] == [wall.id]


def test_undo_restores_wall_after_move():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    session.move_wall(wall.id, Point2D(2.0, 3.0))
    assert session.find_wall(wall.id).segment.start == Point2D(2.0, 3.0)
    session.undo()  # deshace el move
    assert session.find_wall(wall.id).segment.start == Point2D(0.0, 0.0)
    session.undo()  # deshace el add
    assert session.floor.walls == []


def test_undo_restores_wall_and_openings_after_delete():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(6.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.select(SelectionKind.WALL, wall.id)
    assert session.delete_selection() is True
    assert session.floor.walls == []
    assert session.floor.openings == []
    session.undo()
    assert [w.id for w in session.floor.walls] == [wall.id]
    assert [o.id for o in session.floor.openings] == [opening.id]


def test_failed_operation_leaves_no_ghost_step():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))  # paso legítimo
    with pytest.raises(ValueError):
        session.add_wall(Point2D(1.0, 1.0), Point2D(1.0, 1.0))  # degenerada
    # El paso fallido no se anotó: un solo undo deshace el add real.
    assert session.undo() is True
    assert session.floor.walls == []
    assert session.can_undo() is False


def test_nested_calls_record_a_single_step():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(6.0, 0.0))
    session.add_opening(wall.id, "door")
    # move_wall llama internamente a set_wall_endpoints: UN solo paso.
    session.move_wall(wall.id, Point2D(1.0, 1.0))
    assert session.undo() is True
    # Un solo undo: la pared sigue donde estaba tras el add.
    assert session.find_wall(wall.id).segment.start == Point2D(0.0, 0.0)
    assert session.can_undo() is True  # queda el paso del add


def test_new_action_clears_redo_stack():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.undo()
    assert session.can_redo() is True
    session.add_wall(Point2D(1.0, 1.0), Point2D(2.0, 2.0))
    assert session.can_redo() is False


def test_undo_beyond_empty_is_noop():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    assert session.undo() is True
    assert session.undo() is False
    assert session.floor.walls == []


def test_redo_beyond_empty_is_noop():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    assert session.undo() is True
    assert session.redo() is True
    assert session.redo() is False
    assert len(session.floor.walls) == 1


def test_history_cleared_on_new_document():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.new_project()
    assert session.can_undo() is False
    assert session.can_redo() is False


def test_undo_restores_selection():
    session = make_session()
    assert session.selection is None
    wall = session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    # add_wall selecciona la pared nueva; el snapshot previo tenía None.
    assert session.selection is not None
    session.undo()
    assert session.selection is None
    session.redo()
    assert session.selection is not None
    assert session.selection.entity_id == wall.id


def test_undo_marks_dirty_and_invalidates_heatmap():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.heatmap_dirty = False
    assert session.undo() is True
    assert session.dirty is True
    assert session.heatmap_dirty is True


def test_history_is_capped_at_max_undo_steps():
    session = make_session()
    for index in range(MAX_UNDO_STEPS + 5):
        x = float(index)
        session.add_wall(Point2D(x, 0.0), Point2D(x, 2.0))
    assert len(session._undo_stack) == MAX_UNDO_STEPS
    # Al llegar al límite, los pasos más antiguos se descartan.
    undone = 0
    while session.undo():
        undone += 1
    assert undone == MAX_UNDO_STEPS


def test_snapshot_is_isolated_from_later_edits():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    session.move_wall(wall.id, Point2D(5.0, 5.0))  # snapshot del add ya existe
    session.undo()
    # El snapshot del add no se contaminó con el move posterior.
    assert session.find_wall(wall.id).segment.start == Point2D(0.0, 0.0)


def test_space_and_obstacle_edits_undoable():
    session = make_session()
    space = session.add_space(Point2D(1.0, 1.0), Point2D(3.0, 3.0))
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    assert len(session._undo_stack) == 2
    session.set_space_rect(space.id, Rect(x=5.0, y=5.0, width=2.0, height=2.0))
    session.set_obstacle_rect(
        obstacle.id, Rect(x=3.0, y=4.0, width=4.0, height=2.0)
    )
    assert len(session._undo_stack) == 4
    session.undo()
    moved_obstacle = next(o for o in session.floor.obstacles if o.id == obstacle.id)
    assert moved_obstacle.rect.x == pytest.approx(0.0)
    session.undo()
    moved_space = next(s for s in session.floor.spaces if s.id == space.id)
    assert moved_space.rect.x == pytest.approx(1.0)


def test_ap_edits_undoable():
    session = make_session()
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.move_ap(ap.id, Point2D(6.0, 6.0))
    session.undo()
    restored = next(a for a in session.project.access_points if a.id == ap.id)
    assert restored.position == Point2D(2.0, 2.0)


def test_undo_does_not_record_itself():
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.undo()
    # El undo no anotó un paso extra: redo tiene exactamente 1.
    assert len(session._redo_stack) == 1
    session.redo()
    assert len(session._undo_stack) == 1


def test_undo_keeps_document_path():
    session = make_session()
    session.mark_saved("C:/tmp/proyecto.json")
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.undo()
    assert session.project_path == "C:/tmp/proyecto.json"
    assert session.dirty is True
