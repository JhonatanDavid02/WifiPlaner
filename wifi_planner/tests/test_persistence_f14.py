"""Fase 14-H: persistencia de la geometría editada (schema v1 intacto).

Comprueba que todo lo que la Fase 14 edita (extremos de pared, rects de
espacios/obstáculos, traslaciones, pisos activos…) sobrevive guardar y
cargar, y que el esquema NO creció: ni claves nuevas ni preferencias de
vista (rejilla/snap/medición/undo) colándose en el JSON.
"""

from __future__ import annotations

import json

import pytest

from core.geometry import Point2D, Rect
from core.space import Floor
from tests.factories import make_session
from ui.session import EditorSession

#: Claves exactas del schema v1 (contrato con Fase 6; no cambian en F14).
DOCUMENT_KEYS = {"schema_version", "project", "editor"}
PROJECT_KEYS = {
    "name", "units", "bands", "materials", "radio", "thresholds",
    "floors", "access_points", "clients", "metadata",
}
FLOOR_KEYS = {
    "id", "name", "level", "width_m", "height_m", "elevation_m", "metadata",
    "walls", "spaces", "openings", "obstacles",
}
EDITOR_KEYS = {"band_id", "grid_resolution_m"}


def _edit_with_f14_operations(session):
    """Edita el documento con todas las operaciones nuevas de la F14."""
    session.set_floor_dimensions(30.0, 20.0)
    wall = session.add_wall(Point2D(0.0, 5.0), Point2D(10.0, 5.0))
    session.add_opening(wall.id, "door")
    # Extremos + traslación (ops 14-D) sobre la pared con hueco.
    session.set_wall_endpoints(wall.id, Point2D(2.0, 5.0), Point2D(14.0, 5.0))
    session.move_wall(wall.id, Point2D(0.0, 1.0))
    session.set_wall_material(wall.id, "concrete")
    space = session.add_space(Point2D(1.0, 1.0), Point2D(4.0, 3.0))
    session.move_space(space.id, Point2D(5.0, 6.0))
    obstacle = session.add_obstacle(Point2D(0.0, 0.0), Point2D(2.0, 1.0))
    session.set_obstacle_rect(
        obstacle.id, Rect(x=3.0, y=4.0, width=4.0, height=2.0)
    )
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.move_ap(ap.id, Point2D(8.0, 6.0))
    session.add_client(Point2D(9.0, 9.0))
    return wall, space, obstacle, ap


def test_edited_geometry_round_trip(tmp_path):
    session = make_session()
    wall, space, obstacle, ap = _edit_with_f14_operations(session)
    path = str(tmp_path / "editado.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    floor = loaded.floor

    assert floor.width_m == pytest.approx(30.0)
    assert floor.height_m == pytest.approx(20.0)
    wall2 = loaded.find_wall(wall.id)
    assert wall2.segment.start == Point2D(2.0, 6.0)
    assert wall2.segment.end == Point2D(14.0, 6.0)
    assert wall2.material.id == "concrete"
    openings = loaded.openings_for_wall(wall.id)
    assert len(openings) == 1
    assert openings[0].kind == "door"
    space2 = next(s for s in floor.spaces if s.id == space.id)
    assert space2.rect.x == pytest.approx(6.0)
    assert space2.rect.y == pytest.approx(7.0)
    obstacle2 = next(o for o in floor.obstacles if o.id == obstacle.id)
    assert obstacle2.rect.width == pytest.approx(4.0)
    assert obstacle2.rect.height == pytest.approx(2.0)
    ap2 = next(a for a in loaded.project.access_points if a.id == ap.id)
    assert ap2.position == Point2D(8.0, 6.0)
    assert len(loaded.project.clients) == 1


def test_undo_history_not_persisted(tmp_path):
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    assert session.can_undo() is True
    path = str(tmp_path / "undo.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    # El historial es transitorio del documento en memoria.
    assert loaded.can_undo() is False
    assert loaded.can_redo() is False
    assert loaded.selection is None
    assert loaded.active_floor_id is None


def test_view_prefs_not_persisted(tmp_path):
    session = make_session()
    session.set_grid_step(1.0)
    session.set_snap_to_grid(False)
    session.set_measure_anchor(Point2D(1.0, 1.0))
    session.set_measure_cursor(Point2D(4.0, 5.0))
    path = str(tmp_path / "vista.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    # Preferencias de vista: schema v1 intacto ⇒ vuelven a los defaults.
    assert loaded.grid_step_m == pytest.approx(0.5)
    assert loaded.snap_to_grid is True
    assert loaded.measure_distance_m() is None


def test_schema_v1_keys_unchanged_after_f14_edits(tmp_path):
    session = make_session()
    _edit_with_f14_operations(session)
    path = tmp_path / "claves.json"
    session.save_project(str(path))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw.keys()) == DOCUMENT_KEYS
    assert raw["schema_version"] == 1
    assert set(raw["project"].keys()) == PROJECT_KEYS
    assert set(raw["editor"].keys()) == EDITOR_KEYS
    assert set(raw["project"]["floors"][0].keys()) == FLOOR_KEYS
    # Nada de estado de la Fase 14 en el JSON.
    serialized = path.read_text(encoding="utf-8")
    for forbidden in ("grid_step", "snap_to_grid", "measure_anchor", "undo"):
        assert forbidden not in serialized


def test_save_after_undo_round_trips_undone_state(tmp_path):
    session = make_session()
    session.add_wall(Point2D(0.0, 4.0), Point2D(6.0, 4.0))
    session.undo()  # volvemos al documento sin paredes
    path = str(tmp_path / "deshacer.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    assert loaded.floor.walls == []
    assert loaded.floor.openings == []


def test_multi_floor_geometry_round_trip(tmp_path):
    session = make_session()
    session.project.floors.append(
        Floor(id="FLOOR-002", name="Primera", width_m=12.0, height_m=8.0)
    )
    session.set_active_floor("FLOOR-002")
    wall = session.add_wall(Point2D(1.0, 1.0), Point2D(5.0, 1.0))
    path = str(tmp_path / "pisos.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    assert [f.id for f in loaded.project.floors] == ["FLOOR-001", "FLOOR-002"]
    second = loaded.project.floors[1]
    assert [w.id for w in second.walls] == [wall.id]
    # El piso activo es transitorio: al cargar vuelve al primero.
    assert loaded.active_floor_id is None
    assert loaded.active_floor.id == "FLOOR-001"
    assert loaded.project.floors[0].walls == []


def test_opening_stays_valid_after_saved_shrink_cycle(tmp_path):
    """Ciclo guardar→cargar conserva la invariantes hueco↔pared."""
    session = make_session()
    wall = session.add_wall(Point2D(0.0, 0.0), Point2D(10.0, 0.0))
    opening = session.add_opening(wall.id, "door")
    path = str(tmp_path / "hueco.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    wall2 = loaded.find_wall(wall.id)
    opening2 = loaded.openings_for_wall(wall.id)[0]
    assert opening2.end_offset_m <= wall2.segment.length + 1e-9
    # Y la edición de extremos sigue protegiendo el hueco tras recargar.
    with pytest.raises(ValueError, match="hueco"):
        loaded.set_wall_endpoints(
            wall.id, Point2D(0.0, 0.0), Point2D(opening2.end_offset_m - 0.5, 0.0)
        )
