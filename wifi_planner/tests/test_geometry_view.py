"""Fase 14-C: vista de geometría (GeometryView) y piso activo.

El Canvas ya no alcanza las listas internas del documento: consume una
instantánea congelada del piso activo, y las operaciones del editor se
aplican al piso seleccionado con ``set_active_floor``.
"""

from __future__ import annotations

import dataclasses

import pytest

from core.geometry import Point2D
from core.space import Floor
from tests.factories import make_session
from ui.geometry_view import GeometryView, build_geometry_view
from ui.session import EditorSession, SelectionKind


# ---------------------------------------------------------------------------
# GeometryView: instantánea inmutable
# ---------------------------------------------------------------------------

def test_view_is_frozen():
    session = make_session()
    view = session.geometry_view
    assert isinstance(view, GeometryView)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.walls = ()


def test_view_snapshot_does_not_change_after_edits():
    session = make_session()
    view_before = session.geometry_view
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    # La vista capturada es una tupla copiada: no se muta con la edición.
    assert len(view_before.walls) == 0
    assert len(session.geometry_view.walls) == 1


def test_view_reflects_wall_opening_and_ap():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 4.0), Point2D(10.0, 4.0))
    session.add_opening(wall.id, "door")
    session.add_access_point(Point2D(5.0, 2.0))
    view = session.geometry_view
    assert [w.id for w in view.walls] == [wall.id]
    assert len(view.openings) == 1
    assert len(view.access_points) == 1


def test_view_reflects_deletion():
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.select(SelectionKind.WALL, wall.id)
    session.delete_selection()
    assert session.geometry_view.walls == ()


def test_view_dimensions_match_floor():
    session = make_session()
    session.set_floor_dimensions(30.0, 20.0)
    view = session.geometry_view
    assert view.width_m == pytest.approx(30.0)
    assert view.height_m == pytest.approx(20.0)


def test_view_dimensions_none_when_undefined():
    session = EditorSession()
    session.project.floors[0].width_m = None
    session.project.floors[0].height_m = None
    view = session.geometry_view
    assert view.width_m is None
    assert view.height_m is None


def test_build_geometry_view_direct_from_floor():
    session = make_session()
    session.add_wall(Point2D(0.0, 2.0), Point2D(4.0, 2.0))
    view = build_geometry_view(
        session.floor,
        access_points=session.project.access_points,
        clients=session.project.clients,
    )
    assert view.floor_id == session.floor.id
    assert len(view.walls) == 1
    assert view.spaces == ()
    assert view.clients == tuple(session.project.clients)


def test_view_floor_id_matches_active_floor():
    session = make_session()
    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    session.set_active_floor("FLOOR-002")
    assert session.geometry_view.floor_id == "FLOOR-002"


# ---------------------------------------------------------------------------
# Piso activo (active_floor)
# ---------------------------------------------------------------------------

def test_default_active_floor_is_first():
    session = make_session()
    assert session.active_floor.id == session.project.floors[0].id
    assert session.floor is session.active_floor


def test_set_active_floor_switches_crud_target():
    session = make_session()
    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    session.set_active_floor("FLOOR-002")
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    first, second = session.project.floors
    assert first.walls == []
    assert len(second.walls) == 1
    assert session.geometry_view.walls[0].id == second.walls[0].id


def test_set_active_floor_invalidates_heatmap():
    session = make_session()
    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    session.heatmap_dirty = False
    session.set_active_floor("FLOOR-002")
    assert session.heatmap_dirty is True


def test_set_active_floor_unknown_id_raises():
    session = make_session()
    with pytest.raises(ValueError, match="Piso desconocido"):
        session.set_active_floor("FLOOR-999")


def test_deleted_active_floor_falls_back_to_first():
    session = make_session()
    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    session.set_active_floor("FLOOR-002")
    session.project.floors.remove(session.project.floors[1])
    assert session.active_floor.id == "FLOOR-001"
    assert session.active_floor_id is None


def test_new_document_resets_active_floor():
    session = make_session()
    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    session.set_active_floor("FLOOR-002")
    session.new_project()
    assert session.active_floor_id is None
    assert session.active_floor.id == "FLOOR-001"


def test_set_same_floor_does_not_invalidate_heatmap():
    session = make_session()
    session.heatmap_dirty = False
    session.set_active_floor(session.active_floor.id)
    assert session.heatmap_dirty is False
