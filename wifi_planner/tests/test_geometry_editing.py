"""Fase 14-D: edición de geometría (extremos de pared, espacios, objetos).

Cubre las operaciones nuevas del editor: mover/redimensionar paredes con
protección atómica de openings, trasladar espacios y recortar footprints
de obstáculos al piso, siempre en metros y sobre el piso activo.
"""

from __future__ import annotations

import math

import pytest

from core.geometry import Point2D, Rect
from tests.factories import make_session
from ui.session import EditorSession


@pytest.fixture
def session() -> EditorSession:
    return make_session()


# ---------------------------------------------------------------------------
# set_wall_endpoints: mover / redimensionar pared
# ---------------------------------------------------------------------------

def test_set_wall_endpoints_moves_wall(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    session.heatmap_dirty = False
    session.set_wall_endpoints(wall.id, Point2D(1.0, 1.0), Point2D(5.0, 1.0))
    wall2 = session.find_wall(wall.id)
    assert wall2.segment.start == Point2D(1.0, 1.0)
    assert wall2.segment.end == Point2D(5.0, 1.0)
    assert session.heatmap_dirty is True
    assert session.dirty is True


def test_set_wall_endpoints_unknown_wall_raises(session):
    with pytest.raises(KeyError, match="Pared no encontrada"):
        session.set_wall_endpoints(
            "WALL-999", Point2D(0.0, 0.0), Point2D(1.0, 0.0)
        )


def test_set_wall_endpoints_degenerate_raises(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    with pytest.raises(ValueError, match="dos puntos distintos"):
        session.set_wall_endpoints(wall.id, Point2D(2.0, 2.0), Point2D(2.0, 2.0))


def test_set_wall_endpoints_non_finite_raises(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    with pytest.raises(ValueError, match="finitas"):
        session.set_wall_endpoints(
            wall.id, Point2D(math.nan, 0.0), Point2D(4.0, 0.0)
        )


def test_shrinking_wall_with_opening_rejected_atomically(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(10.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    before = session.find_wall(wall.id)
    new_length = opening.end_offset_m - 0.5  # el hueco NO cabe
    with pytest.raises(ValueError, match="hueco"):
        session.set_wall_endpoints(
            wall.id, Point2D(0.0, 0.0), Point2D(new_length, 0.0)
        )
    # Átomo: nada cambió (pared y openings intactos).
    after = session.find_wall(wall.id)
    assert after.segment == before.segment
    assert len(session.openings_for_wall(wall.id)) == 1


def test_shrinking_wall_without_openings_is_allowed(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(10.0, 0.0))
    session.set_wall_endpoints(wall.id, Point2D(0.0, 0.0), Point2D(3.0, 0.0))
    assert session.find_wall(wall.id).segment.length == pytest.approx(3.0)


def test_shrinking_wall_to_exact_opening_end_is_allowed(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(10.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    # Longitud exactamente en el borde del hueco: sigue cabiendo.
    session.set_wall_endpoints(
        wall.id, Point2D(0.0, 0.0), Point2D(opening.end_offset_m, 0.0)
    )
    assert session.find_wall(wall.id).segment.length == pytest.approx(
        opening.end_offset_m
    )


def test_growing_wall_keeps_opening_valid(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(10.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.set_wall_endpoints(wall.id, Point2D(2.0, 2.0), Point2D(20.0, 2.0))
    kept = session.openings_for_wall(wall.id)
    assert [item.id for item in kept] == [opening.id]
    assert kept[0].start_offset_m == pytest.approx(opening.start_offset_m)


# ---------------------------------------------------------------------------
# move_wall: traslación con openings intactos
# ---------------------------------------------------------------------------

def test_move_wall_translates_and_keeps_opening_offsets(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(6.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    session.heatmap_dirty = False
    session.move_wall(wall.id, Point2D(2.0, 3.0))
    wall2 = session.find_wall(wall.id)
    assert wall2.segment.start == Point2D(2.0, 3.0)
    assert wall2.segment.end == Point2D(8.0, 3.0)
    kept = session.openings_for_wall(wall.id)
    assert kept[0].start_offset_m == pytest.approx(opening.start_offset_m)
    assert kept[0].end_offset_m == pytest.approx(opening.end_offset_m)
    assert session.heatmap_dirty is True
    assert session.dirty is True


def test_move_wall_unknown_raises(session):
    with pytest.raises(KeyError, match="Pared no encontrada"):
        session.move_wall("WALL-999", Point2D(1.0, 0.0))


def test_move_wall_non_finite_delta_raises(session):
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    with pytest.raises(ValueError, match="finitas"):
        session.move_wall(wall.id, Point2D(math.inf, 0.0))


# ---------------------------------------------------------------------------
# Espacios: set_space_rect / move_space
# ---------------------------------------------------------------------------

def _add_space(session, a, b):
    return session.add_space(Point2D(*a), Point2D(*b))


def test_set_space_rect_moves_space_without_heatmap_invalidation(session):
    space = _add_space(session, (1.0, 1.0), (3.0, 3.0))
    session.heatmap_dirty = False
    session.set_space_rect(space.id, Rect(x=5.0, y=5.0, width=2.0, height=2.0))
    moved = session.selected_space()  # la selección sigue en el mismo id
    for item in session.floor.spaces:
        if item.id == space.id:
            moved = item
    assert moved.rect.x == pytest.approx(5.0)
    assert moved.rect.y == pytest.approx(5.0)
    # Decisión BH: los espacios no atenúan → el heatmap NO se invalida.
    assert session.heatmap_dirty is False
    assert session.dirty is True


def test_set_space_rect_clamps_to_floor(session):
    space = _add_space(session, (1.0, 1.0), (3.0, 3.0))
    # Piso por defecto 12×8: el rect se recorta al borde.
    session.set_space_rect(space.id, Rect(x=11.0, y=7.0, width=4.0, height=4.0))
    target = next(s for s in session.floor.spaces if s.id == space.id)
    assert target.rect.x + target.rect.width == pytest.approx(12.0)
    assert target.rect.y + target.rect.height == pytest.approx(8.0)


def test_set_space_rect_too_small_after_clamp_raises(session):
    space = _add_space(session, (1.0, 1.0), (3.0, 3.0))
    with pytest.raises(ValueError, match="espacio"):
        session.set_space_rect(space.id, Rect(x=11.95, y=1.0, width=4.0, height=4.0))


def test_set_space_rect_unknown_raises(session):
    with pytest.raises(KeyError, match="Espacio no encontrado"):
        session.set_space_rect("SPACE-999", Rect(x=1.0, y=1.0, width=2.0, height=2.0))


def test_move_space_keeps_size_and_clamps(session):
    space = _add_space(session, (1.0, 1.0), (3.0, 3.0))
    session.move_space(space.id, Point2D(100.0, 100.0))
    moved = next(s for s in session.floor.spaces if s.id == space.id)
    assert moved.rect.width == pytest.approx(space.rect.width)
    assert moved.rect.height == pytest.approx(space.rect.height)
    assert moved.rect.x + moved.rect.width <= 12.0 + 1e-9
    assert moved.rect.y + moved.rect.height <= 8.0 + 1e-9


def test_move_space_unknown_raises(session):
    with pytest.raises(KeyError, match="Espacio no encontrado"):
        session.move_space("SPACE-999", Point2D(1.0, 1.0))


# ---------------------------------------------------------------------------
# Obstáculos: set_obstacle_rect (mover + redimensionar)
# ---------------------------------------------------------------------------

def test_set_obstacle_rect_moves_and_resizes(session):
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    session.heatmap_dirty = False
    session.set_obstacle_rect(obstacle.id, Rect(x=3.0, y=4.0, width=4.0, height=2.0))
    target = next(o for o in session.floor.obstacles if o.id == obstacle.id)
    assert target.rect.x == pytest.approx(3.0)
    assert target.rect.width == pytest.approx(4.0)
    assert target.rect.height == pytest.approx(2.0)
    # La geometría del obstáculo atenúa (Fase 9) → sí invalida.
    assert session.heatmap_dirty is True
    assert session.dirty is True


def test_set_obstacle_rect_clamps_to_floor(session):
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    session.set_obstacle_rect(obstacle.id, Rect(x=11.0, y=7.0, width=5.0, height=5.0))
    target = next(o for o in session.floor.obstacles if o.id == obstacle.id)
    assert target.rect.x + target.rect.width == pytest.approx(12.0)
    assert target.rect.y + target.rect.height == pytest.approx(8.0)


def test_set_obstacle_rect_too_small_after_clamp_raises(session):
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    with pytest.raises(ValueError, match="objeto"):
        session.set_obstacle_rect(
            obstacle.id, Rect(x=11.95, y=1.0, width=5.0, height=5.0)
        )


def test_set_obstacle_rect_unknown_raises(session):
    with pytest.raises(KeyError, match="Objeto no encontrado"):
        session.set_obstacle_rect("OBST-999", Rect(x=1.0, y=1.0, width=2.0, height=1.0))


def test_set_obstacle_rect_non_finite_raises(session):
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    with pytest.raises(ValueError, match="finitos"):
        session.set_obstacle_rect(
            obstacle.id, Rect(x=1.0, y=1.0, width=math.nan, height=1.0)
        )


# ---------------------------------------------------------------------------
# Edición sobre el piso activo
# ---------------------------------------------------------------------------

def test_wall_edit_targets_active_floor(session):
    from core.space import Floor

    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(4.0, 0.0))
    session.set_active_floor("FLOOR-002")
    # La pared vive en FLOOR-001: con otro piso activo no se encuentra…
    with pytest.raises(KeyError):
        session.move_wall(wall.id, Point2D(1.0, 1.0))
    original = next(
        w for w in session.project.floors[0].walls if w.id == wall.id
    )
    assert original.segment == wall.segment
    # …y al volver al piso original la edición sí opera.
    session.set_active_floor("FLOOR-001")
    session.move_wall(wall.id, Point2D(1.0, 1.0))
    moved = session.find_wall(wall.id)
    assert moved.segment.start == Point2D(1.0, 1.0)
