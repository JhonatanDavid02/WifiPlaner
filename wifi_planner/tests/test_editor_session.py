"""Pruebas de EditorSession (lógica del editor sin Tkinter)."""

import pytest

from core.geometry import Point2D
from core.space import Floor
from ui.session import (
    EditorSession,
    SelectionKind,
    Tool,
    create_default_project,
    next_entity_id,
)


@pytest.fixture
def session() -> EditorSession:
    return EditorSession()


# ---------------------------------------------------------------------------
# Proyecto inicial / dimensiones
# ---------------------------------------------------------------------------

def test_default_project_dimensions_12x8(session):
    assert session.floor_width_m == pytest.approx(12.0)
    assert session.floor_height_m == pytest.approx(8.0)
    assert session.project.units == "m"
    assert "Wi-Fi Planner" in session.project.name


def test_set_floor_dimensions_valid(session):
    session.set_floor_dimensions(20.0, 15.0)
    assert session.floor_width_m == pytest.approx(20.0)
    assert session.floor_height_m == pytest.approx(15.0)


def test_set_floor_dimensions_rejects_zero(session):
    with pytest.raises(ValueError):
        session.set_floor_dimensions(0, 8)
    with pytest.raises(ValueError):
        session.set_floor_dimensions(12, 0)


def test_set_floor_dimensions_rejects_negative(session):
    with pytest.raises(ValueError):
        session.set_floor_dimensions(-5, 8)


def test_set_floor_dimensions_rejects_unreasonable(session):
    with pytest.raises(ValueError):
        session.set_floor_dimensions(50_000, 8)


def test_floor_rejects_invalid_dimensions():
    with pytest.raises(ValueError):
        Floor(id="F1", width_m=-1, height_m=8)
    with pytest.raises(ValueError):
        Floor(id="F1", width_m=12, height_m=0)


def test_create_default_project_has_floor():
    project = create_default_project()
    assert len(project.floors) == 1
    assert project.floors[0].width_m == 12.0
    assert project.floors[0].height_m == 8.0


# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------

def test_next_entity_id_sequences():
    assert next_entity_id([], "AP") == "AP-001"
    assert next_entity_id(["AP-001"], "AP") == "AP-002"
    assert next_entity_id(["AP-001", "AP-003"], "AP") == "AP-004"
    assert next_entity_id(["WALL-001"], "AP") == "AP-001"


def test_entity_ids_created_sequentially(session):
    ap1 = session.add_access_point(Point2D(1, 1))
    ap2 = session.add_access_point(Point2D(2, 2))
    assert ap1.id == "AP-001"
    assert ap2.id == "AP-002"


# ---------------------------------------------------------------------------
# Crear paredes / APs / clientes
# ---------------------------------------------------------------------------

def test_add_wall_creates_in_meters(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(5, 0))
    assert wall.id.startswith("WALL-")
    assert wall.segment.start.x == 0.0
    assert wall.segment.end.x == 5.0
    assert wall in session.floor.walls
    # Selección automática
    assert session.selection is not None
    assert session.selection.kind == SelectionKind.WALL


def test_add_wall_rejects_degenerate(session):
    with pytest.raises(ValueError):
        session.add_wall(Point2D(1, 1), Point2D(1, 1))


def test_add_ap_and_client(session):
    ap = session.add_access_point(Point2D(3.0, 4.0))
    client = session.add_client(Point2D(5.0, 2.0))
    assert ap.position.x == pytest.approx(3.0)
    assert ap.position.y == pytest.approx(4.0)
    assert client.position.x == pytest.approx(5.0)
    assert ap.id.startswith("AP-")
    assert client.id.startswith("CLIENT-")
    assert ap in session.project.access_points
    assert client in session.project.clients


def test_add_ap_clamps_to_floor(session):
    ap = session.add_access_point(Point2D(100.0, -5.0))
    assert ap.position.x == pytest.approx(12.0)
    assert ap.position.y == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Mover
# ---------------------------------------------------------------------------

def test_move_ap_updates_position_meters(session):
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.move_ap(ap.id, Point2D(5.32, 3.80))
    moved = session.selected_ap() or session.project.access_points[0]
    assert moved.position.x == pytest.approx(5.32)
    assert moved.position.y == pytest.approx(3.80)
    # El objeto original no se muta in-place de forma oculta: lista actualizada
    assert session.project.access_points[0].position.x == pytest.approx(5.32)


def test_move_client_updates_position(session):
    client = session.add_client(Point2D(1.0, 1.0))
    session.move_client(client.id, Point2D(7.5, 6.25))
    assert session.project.clients[0].position.x == pytest.approx(7.5)
    assert session.project.clients[0].position.y == pytest.approx(6.25)


def test_move_ap_unknown_id_raises(session):
    with pytest.raises(KeyError):
        session.move_ap("AP-999", Point2D(1, 1))


def test_move_ap_clamps(session):
    ap = session.add_access_point(Point2D(5, 5))
    session.move_ap(ap.id, Point2D(-1, 99))
    assert session.project.access_points[0].position.x == pytest.approx(0.0)
    assert session.project.access_points[0].position.y == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Material / espesor
# ---------------------------------------------------------------------------

def test_set_wall_material(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    session.set_wall_material(wall.id, "concrete")
    updated = session.selected_wall()
    assert updated.material.id == "concrete"


def test_set_wall_material_unknown_raises(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    with pytest.raises(KeyError):
        session.set_wall_material(wall.id, "kryptonite")


def test_set_wall_thickness_valid(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    session.set_wall_thickness(wall.id, 0.15)
    assert session.selected_wall().thickness_m == pytest.approx(0.15)


def test_set_wall_thickness_rejects_zero(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    with pytest.raises(ValueError):
        session.set_wall_thickness(wall.id, 0.0)


def test_set_wall_thickness_rejects_negative(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    with pytest.raises(ValueError):
        session.set_wall_thickness(wall.id, -0.1)


def test_set_wall_thickness_rejects_unreasonable(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    with pytest.raises(ValueError):
        session.set_wall_thickness(wall.id, 50.0)


# ---------------------------------------------------------------------------
# Eliminar
# ---------------------------------------------------------------------------

def test_delete_wall(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(4, 0))
    assert session.delete_selection() is True
    assert wall not in session.floor.walls
    assert session.selection is None


def test_delete_ap(session):
    ap = session.add_access_point(Point2D(2, 2))
    assert session.delete_selection() is True
    assert ap not in session.project.access_points


def test_delete_client(session):
    client = session.add_client(Point2D(2, 2))
    assert session.delete_selection() is True
    assert client not in session.project.clients


def test_delete_nothing_selected(session):
    assert session.delete_selection() is False


def test_delete_leaves_no_orphans(session):
    wall = session.add_wall(Point2D(0, 0), Point2D(3, 0))
    ap = session.add_access_point(Point2D(1, 1))
    client = session.add_client(Point2D(2, 2))

    # Seleccionar y eliminar cada entidad
    for kind, entity in (
        (SelectionKind.WALL, wall),
        (SelectionKind.AP, ap),
        (SelectionKind.CLIENT, client),
    ):
        session.select(kind, entity.id)
        assert session.delete_selection() is True

    assert session.floor.walls == []
    assert session.project.access_points == []
    assert session.project.clients == []
    assert session.selection is None


# ---------------------------------------------------------------------------
# Herramientas / selección
# ---------------------------------------------------------------------------

def test_set_tool_clears_wall_drag(session):
    session.set_tool(Tool.WALL)
    session.wall_drag_start = Point2D(0, 0)
    session.set_tool(Tool.SELECT)
    assert session.wall_drag_start is None


def test_set_tool_non_select_clears_selection(session):
    session.add_access_point(Point2D(1, 1))
    assert session.selection is not None
    session.set_tool(Tool.WALL)
    assert session.selection is None


# ---------------------------------------------------------------------------
# Simulación (invoca engine con paredes reales)
# ---------------------------------------------------------------------------

def test_simulation_without_ap_raises(session):
    with pytest.raises(ValueError):
        session.run_simulation("band_2_4")


def test_simulation_with_ap_and_walls(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 8.0))
    session.add_client(Point2D(9.0, 4.0))

    result = session.run_simulation("band_2_4")
    assert result.band_id == "band_2_4"
    assert len(result.evaluations) >= 1

    ev = result.evaluations[0]
    # Pared de drywall en x=5 entre AP (1,1) y cliente (9,4) => obstáculo
    assert ev.obstacle_loss_db > 0
    assert ev.obstacle_loss.crossings >= 1


def test_simulation_summary_text(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.run_simulation("band_5")
    text = session.simulation_summary_text()
    assert "AP:" in text
    assert "5 GHz" in text
    assert "RSSI mínimo" in text
    assert "RSSI máximo" in text


def test_simulation_sample_points_default_grid(session):
    session.add_access_point(Point2D(1, 1))
    points = session.sample_points_for_simulation()
    assert len(points) == 9  # malla 3×3 sin clientes
    for p in points:
        assert 0 <= p.x <= session.floor_width_m
        assert 0 <= p.y <= session.floor_height_m


def test_simulation_sample_points_use_clients(session):
    session.add_access_point(Point2D(1, 1))
    session.add_client(Point2D(3, 3))
    session.add_client(Point2D(6, 6))
    points = session.sample_points_for_simulation()
    assert len(points) == 2


def test_simulation_6ghz_raises_material_error(session):
    from core.material import MaterialAttenuationError

    session.add_access_point(Point2D(1, 1))
    session.add_wall(Point2D(5, 0), Point2D(5, 8))
    session.add_client(Point2D(9, 4))
    with pytest.raises(MaterialAttenuationError):
        session.run_simulation("band_6")
