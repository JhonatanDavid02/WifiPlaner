"""Pruebas del CoverageGrid (Fase 4: malla espacial en metros)."""

import pytest

from core.geometry import Point2D
from engine.coverage_grid import (
    MAX_GRID_POINTS,
    MIN_RESOLUTION_M,
    CoverageGrid,
)


# ---------------------------------------------------------------------------
# Generación básica
# ---------------------------------------------------------------------------

def test_grid_exact_multiple_12x8_at_0_5():
    grid = CoverageGrid(width_m=12.0, height_m=8.0, resolution_m=0.5)
    # 12/0.5 = 24 intervalos → 25 puntos; 8/0.5 = 16 → 17
    assert grid.cols == 25
    assert grid.rows == 17
    assert grid.point_count == 25 * 17  # 425


def test_grid_points_order_row_major():
    grid = CoverageGrid(width_m=1.0, height_m=1.0, resolution_m=0.5)
    pts = grid.points()
    # ys creciente, luego xs: (0,0), (0.5,0), (1,0), (0,0.5)...
    assert pts[0] == Point2D(0.0, 0.0)
    assert pts[1] == Point2D(0.5, 0.0)
    assert pts[2] == Point2D(1.0, 0.0)
    assert pts[3] == Point2D(0.0, 0.5)
    assert len(pts) == grid.point_count


def test_grid_non_multiple_adds_edge_point():
    # 2.3 / 1.0 = 2.3 → floor = 2 → puntos 0,1,2 + borde 2.3
    grid = CoverageGrid(width_m=2.3, height_m=1.0, resolution_m=1.0)
    assert grid.xs == [0.0, 1.0, 2.0, 2.3]
    assert grid.ys == [0.0, 1.0]
    assert grid.point_count == 4 * 2
    # Borde exacto incluido
    assert any(abs(p.x - 2.3) < 1e-9 for p in grid.points())


def test_grid_all_points_inside_bounds():
    grid = CoverageGrid(width_m=7.7, height_m=3.3, resolution_m=0.5)
    for p in grid.points():
        assert -1e-9 <= p.x <= 7.7 + 1e-9
        assert -1e-9 <= p.y <= 3.3 + 1e-9


def test_grid_contains_corner_and_outside():
    grid = CoverageGrid(width_m=4.0, height_m=4.0, resolution_m=1.0)
    assert grid.contains(Point2D(0, 0))
    assert grid.contains(Point2D(4, 4))
    assert not grid.contains(Point2D(4.1, 0))
    assert not grid.contains(Point2D(0, -0.1))


def test_grid_12x8_at_1m_is_13x9():
    grid = CoverageGrid(width_m=12.0, height_m=8.0, resolution_m=1.0)
    assert grid.cols == 13
    assert grid.rows == 9
    assert grid.point_count == 117


def test_grid_12x8_at_0_25_is_49x33():
    grid = CoverageGrid(width_m=12.0, height_m=8.0, resolution_m=0.25)
    assert grid.cols == 49
    assert grid.rows == 33
    assert grid.point_count == 49 * 33  # 1617


# ---------------------------------------------------------------------------
# Validaciones / límites
# ---------------------------------------------------------------------------

def test_grid_rejects_zero_resolution():
    with pytest.raises(ValueError):
        CoverageGrid(width_m=12, height_m=8, resolution_m=0)


def test_grid_rejects_negative_resolution():
    with pytest.raises(ValueError):
        CoverageGrid(width_m=12, height_m=8, resolution_m=-1)


def test_grid_rejects_below_min_resolution():
    with pytest.raises(ValueError):
        CoverageGrid(width_m=12, height_m=8, resolution_m=MIN_RESOLUTION_M / 2)


def test_grid_rejects_zero_dimensions():
    with pytest.raises(ValueError):
        CoverageGrid(width_m=0, height_m=8, resolution_m=0.5)
    with pytest.raises(ValueError):
        CoverageGrid(width_m=12, height_m=0, resolution_m=0.5)


def test_grid_rejects_too_many_points():
    # 100 x 100 m a 0.05 m → 2001 x 2001 ≈ 4M puntos > 100_000
    with pytest.raises(ValueError):
        CoverageGrid(width_m=100.0, height_m=100.0, resolution_m=MIN_RESOLUTION_M)


def test_max_grid_points_constant_is_documented_limit():
    assert MAX_GRID_POINTS == 100_000
    assert MIN_RESOLUTION_M == 0.05


def test_grid_point_count_is_exact():
    grid = CoverageGrid(width_m=3.0, height_m=3.0, resolution_m=0.7)
    assert grid.point_count == len(grid.points())


# ---------------------------------------------------------------------------
# Integración con Session
# ---------------------------------------------------------------------------

def test_session_build_coverage_grid():
    from ui.session import EditorSession

    session = EditorSession()
    grid = session.build_coverage_grid()
    assert grid.width_m == pytest.approx(12.0)
    assert grid.height_m == pytest.approx(8.0)
    assert grid.resolution_m == pytest.approx(0.5)
    assert grid.point_count == 425


def test_session_set_grid_resolution_valid():
    from ui.session import EditorSession

    session = EditorSession()
    session.set_grid_resolution(0.25)
    assert session.grid_resolution_m == pytest.approx(0.25)
    assert session.heatmap_dirty is True


def test_session_set_grid_resolution_rejects_nonpositive():
    from ui.session import EditorSession

    session = EditorSession()
    with pytest.raises(ValueError):
        session.set_grid_resolution(0)
    with pytest.raises(ValueError):
        session.set_grid_resolution(-0.5)


def test_session_set_grid_resolution_rejects_too_fine():
    from ui.session import EditorSession

    session = EditorSession()
    with pytest.raises(ValueError):
        session.set_grid_resolution(0.01)


def test_session_grid_respects_floor_dimensions():
    from ui.session import EditorSession

    session = EditorSession()
    session.set_floor_dimensions(5.0, 4.0)
    session.set_grid_resolution(1.0)
    grid = session.build_coverage_grid()
    assert grid.width_m == pytest.approx(5.0)
    assert grid.height_m == pytest.approx(4.0)
    assert grid.point_count == 6 * 5  # 0..5 y 0..4
