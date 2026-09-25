"""Fase 14-B: sin dimensiones implícitas 12×8 (fallbacks eliminados).

El tamaño del plano solo existe cuando se pide explícitamente
(proyecto nuevo con diálogo o «Dimensiones…»); si falta, las operaciones
fallan con un error claro en lugar de inventar un edificio de ejemplo.
"""

from __future__ import annotations

import pytest

from core.space import Floor
from ui.session import (
    DEFAULT_FLOOR_HEIGHT_M,
    DEFAULT_FLOOR_WIDTH_M,
    EditorSession,
    create_default_project,
)


def test_default_size_is_explicit_constant():
    assert DEFAULT_FLOOR_WIDTH_M == pytest.approx(12.0)
    assert DEFAULT_FLOOR_HEIGHT_M == pytest.approx(8.0)


def test_create_default_project_keeps_example_size():
    project = create_default_project()
    assert project.floors[0].width_m == pytest.approx(12.0)
    assert project.floors[0].height_m == pytest.approx(8.0)


def test_create_default_project_accepts_dimensions():
    project = create_default_project(width_m=30.0, height_m=20.0)
    assert project.floors[0].width_m == pytest.approx(30.0)
    assert project.floors[0].height_m == pytest.approx(20.0)


@pytest.mark.parametrize("width,height", [(0.0, 8.0), (12.0, 0.0), (-5.0, 8.0), (12.0, -1.0)])
def test_create_default_project_rejects_non_positive(width, height):
    with pytest.raises(ValueError, match="> 0"):
        create_default_project(width_m=width, height_m=height)


def test_create_default_project_rejects_oversize():
    with pytest.raises(ValueError, match="10000"):
        create_default_project(width_m=10_001.0, height_m=8.0)


def test_empty_floors_creates_container_without_dimensions():
    session = EditorSession()
    session.project.floors.clear()
    floor = session.floor
    assert isinstance(floor, Floor)
    assert len(session.project.floors) == 1
    # Sin fallback: el contenedor existe pero no inventa el tamaño.
    assert floor.width_m is None
    assert floor.height_m is None


def test_missing_width_raises_informative_error():
    session = EditorSession()
    session.project.floors[0].width_m = None
    with pytest.raises(ValueError, match="ancho definido"):
        _ = session.floor_width_m


def test_missing_height_raises_informative_error():
    session = EditorSession()
    session.project.floors[0].height_m = None
    with pytest.raises(ValueError, match="alto definido"):
        _ = session.floor_height_m


def test_add_space_without_dimensions_raises_instead_of_clamping():
    from core.geometry import Point2D

    session = EditorSession()
    session.project.floors.clear()
    with pytest.raises(ValueError, match="ancho definido"):
        session.add_space(Point2D(1.0, 1.0), Point2D(5.0, 5.0))


def test_add_ap_without_dimensions_raises_instead_of_clamping():
    from core.geometry import Point2D

    session = EditorSession()
    session.project.floors.clear()
    with pytest.raises(ValueError, match="ancho definido"):
        session.add_access_point(Point2D(3.0, 3.0))


def test_new_project_accepts_dimensions():
    session = EditorSession()
    session.new_project(width_m=30.0, height_m=20.0)
    assert session.floor_width_m == pytest.approx(30.0)
    assert session.floor_height_m == pytest.approx(20.0)
    assert session.project_path is None
    assert session.dirty is False


def test_new_project_defaults_keep_example_size():
    session = EditorSession()
    session.new_project()
    assert session.floor_width_m == pytest.approx(12.0)
    assert session.floor_height_m == pytest.approx(8.0)


def test_new_project_invalid_dimensions_leave_document_intact():
    session = EditorSession()
    session.new_project(width_m=30.0, height_m=20.0)
    before = session.project
    with pytest.raises(ValueError):
        session.new_project(width_m=0.0, height_m=20.0)
    assert session.project is before
    assert session.floor_width_m == pytest.approx(30.0)
