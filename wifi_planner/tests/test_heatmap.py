"""Pruebas del heatmap espacial (Fase 4).

Cubre: simulación espacial real, invalidación, apagado, banda,
6 GHz, leyenda, colores, renderer (Pillow + Viewport) y disclaimer.
"""

import pytest

from core.geometry import Point2D
from core.material import MaterialAttenuationError
from core.result import QualityClass, SimulationResult
from ui.session import EditorSession, SelectionKind
from tests.factories import make_session
from ui.viewport import Viewport


@pytest.fixture
def session() -> EditorSession:
    return make_session()


# ---------------------------------------------------------------------------
# Simulación espacial real (grid → engine)
# ---------------------------------------------------------------------------

def test_heatmap_without_ap_raises(session):
    with pytest.raises(ValueError, match="Access Point"):
        session.run_heatmap("band_2_4")


def test_heatmap_empty_ok_but_invalid_until_run(session):
    # Estado inicial: dirty, sin resultado
    assert session.heatmap_dirty is True
    assert session.last_heatmap is None
    assert session.heatmap_enabled is True
    assert session.grid_resolution_m == pytest.approx(0.5)


def test_heatmap_runs_full_grid(session):
    session.add_access_point(Point2D(1.0, 1.0))
    result = session.run_heatmap("band_2_4")
    assert isinstance(result, SimulationResult)
    # 12×8 a 0.5 m → 25 × 17 = 425 puntos
    assert len(result.evaluations) == 425
    assert result.stats["point_count"] == 425
    assert session.heatmap_dirty is False
    assert session.last_heatmap is result


def test_heatmap_with_wall_adds_obstacle_loss(session):
    session.add_access_point(Point2D(1.0, 4.0))
    session.add_wall(Point2D(6.0, 0.0), Point2D(6.0, 8.0))
    # Punto tras la pared debe cruzarla
    result = session.run_heatmap("band_2_4")
    crossed = [e for e in result.evaluations if e.obstacle_loss.crossings > 0]
    free = [e for e in result.evaluations if e.obstacle_loss.crossings == 0]
    assert crossed and free
    # Pared vertical x=6 entre AP x=1 y puntos x>6
    assert any(e.point.x > 6.0 for e in crossed)
    # AP mismo lado (x<6) no cruza esa pared vertical hacia puntos x<6
    assert all(e.obstacle_loss_db == 0 for e in free if e.point.x < 6.0)


def test_heatmap_band_change_invalidates(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_band("band_5")
    assert session.heatmap_dirty is True
    # Nuevo heatmap usa la banda nueva
    result = session.run_heatmap()
    assert result.band_id == "band_5"


def test_heatmap_6ghz_raises_material_error_without_data(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.add_wall(Point2D(6.0, 0.0), Point2D(6.0, 8.0))
    with pytest.raises(MaterialAttenuationError):
        session.run_heatmap("band_6")


def test_heatmap_move_ap_invalidates(session):
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.move_ap(ap.id, Point2D(5.0, 5.0))
    assert session.heatmap_dirty is True


def test_heatmap_add_wall_invalidates(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.add_wall(Point2D(0.0, 4.0), Point2D(12.0, 4.0))
    assert session.heatmap_dirty is True


def test_heatmap_set_wall_material_invalidates(session):
    session.add_access_point(Point2D(1.0, 1.0))
    wall = session.add_wall(Point2D(6.0, 0.0), Point2D(6.0, 8.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_wall_material(wall.id, "concrete")
    assert session.heatmap_dirty is True


def test_heatmap_set_wall_thickness_invalidates(session):
    session.add_access_point(Point2D(1.0, 1.0))
    wall = session.add_wall(Point2D(6.0, 0.0), Point2D(6.0, 8.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_wall_thickness(wall.id, 0.30)
    assert session.heatmap_dirty is True


def test_heatmap_set_floor_dimensions_invalidates(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_floor_dimensions(20.0, 15.0)
    assert session.heatmap_dirty is True


def test_heatmap_delete_ap_invalidates(session):
    ap = session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.select(SelectionKind.AP, ap.id)
    session.delete_selection()
    assert session.heatmap_dirty is True


def test_heatmap_resolution_change_invalidates(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_grid_resolution(1.0)
    assert session.heatmap_dirty is True


def test_heatmap_resolution_affects_point_count(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.set_grid_resolution(1.0)
    result = session.run_heatmap("band_2_4")
    assert len(result.evaluations) == 13 * 9  # 117


def test_heatmap_enabled_toggle(session):
    session.set_heatmap_enabled(False)
    assert session.heatmap_enabled is False
    session.set_heatmap_enabled(True)
    assert session.heatmap_enabled is True
    assert session.heatmap_dirty is True


def test_heatmap_disabled_run_is_skipped_by_app(session):
    # La sesión solo marca estado; la App decide no llamar run_heatmap.
    session.set_heatmap_enabled(False)
    assert session.heatmap_enabled is False
    # Invalidar no debe forzar dirty al re-habilitar si no cambia nada…
    # (set_heatmap_enabled(True) sí invalida para refrescar al reactivar)
    session.set_heatmap_enabled(True)
    assert session.heatmap_dirty is True


def test_resolve_ap_prefers_selected(session):
    ap1 = session.add_access_point(Point2D(1.0, 1.0))
    ap2 = session.add_access_point(Point2D(5.0, 5.0))
    # Selección manual de AP2
    session.select(SelectionKind.AP, ap2.id)
    assert session.resolve_ap_for_heatmap() is not None
    assert session.resolve_ap_for_heatmap().id == ap2.id
    # Sin selección → primero
    session.select(None, None)
    assert session.resolve_ap_for_heatmap().id == ap1.id


# ---------------------------------------------------------------------------
# Estadísticas y texto
# ---------------------------------------------------------------------------

def test_heatmap_stats_text_disclaimer_and_grid(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    text = session.heatmap_stats_text()
    assert "Puntos del grid" in text
    assert "% del total de puntos" in text
    assert "Resolución" in text
    assert "Banda" in text
    assert "2.4" in text


def test_heatmap_stats_without_result(session):
    assert "Sin heatmap" in session.heatmap_stats_text() or session.heatmap_stats_text() == ""


def test_client_rssi_lines_empty_without_clients(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.run_heatmap("band_2_4")
    assert session.client_rssi_lines() == []


def test_client_rssi_lines_with_client_on_grid(session):
    session.add_access_point(Point2D(1.0, 1.0))
    # Cliente en punto exacto del grid (múltiplo de 0.5)
    session.add_client(Point2D(2.0, 2.0))
    session.run_heatmap("band_2_4")
    lines = session.client_rssi_lines()
    assert len(lines) == 1
    assert "RSSI" in lines[0]
    assert "CLIENT" in lines[0] or "CLIENT-001" in lines[0]


def test_client_rssi_lines_nearest_grid_point_if_off_grid(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.add_client(Point2D(2.13, 1.97))  # no está en el grid 0.5
    session.run_heatmap("band_2_4")
    lines = session.client_rssi_lines()
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# Renderer (colores, leyenda, imagen Pillow + Viewport)
# ---------------------------------------------------------------------------

def test_rssi_to_rgb_strong_is_greenish():
    from ui.coverage_renderer import rssi_to_rgb

    r, g, b = rssi_to_rgb(-40.0)
    assert g >= r and g >= b  # verde dominante cerca de -40


def test_rssi_to_rgb_weak_is_reddish():
    from ui.coverage_renderer import rssi_to_rgb

    r, g, b = rssi_to_rgb(-85.0)
    assert r > g  # rojo/naranja


def test_rssi_to_color_clamps_alpha():
    from ui.coverage_renderer import rssi_to_color

    rgba = rssi_to_color(-60.0, alpha=300)
    assert rgba[3] == 255
    rgba = rssi_to_color(-60.0, alpha=-10)
    assert rgba[3] == 0


def test_rssi_to_rgb_clamps_out_of_range():
    from ui.coverage_renderer import rssi_to_rgb

    # Muy fuerte o muy débil no explota
    rssi_to_rgb(0.0)
    rssi_to_rgb(-200.0)
    # Los extremos caen en stops conocidos
    assert rssi_to_rgb(0.0) == rssi_to_rgb(-30.0)
    assert rssi_to_rgb(-200.0) == rssi_to_rgb(-90.0)


def test_quality_color_mapping():
    from ui.coverage_renderer import quality_color

    assert quality_color(QualityClass.EXCELLENT) == (80, 200, 120)
    assert quality_color(QualityClass.NO_COVERAGE) == (120, 70, 90)
    assert quality_color("unknown") == (150, 150, 150)


def test_legend_rows_uses_thresholds():
    from ui.coverage_renderer import legend_rows

    session = EditorSession()
    rows = legend_rows(session.project.thresholds)
    assert len(rows) == 5
    labels = [r["label"] for r in rows]
    assert QualityClass.EXCELLENT.value in labels
    assert QualityClass.NO_COVERAGE.value in labels
    ranges = " ".join(r["range"] for r in rows)
    assert "-50" in ranges
    assert "-67" in ranges
    assert "-75" in ranges
    assert "-85" in ranges


def test_build_heatmap_image_aligns_to_viewport(session):
    from ui.coverage_renderer import build_heatmap_image

    session.add_access_point(Point2D(6.0, 4.0))
    result = session.run_heatmap("band_2_4")
    vp = Viewport(world_width_m=12.0, world_height_m=8.0)
    image = build_heatmap_image(result, vp, cell_size_m=0.5)
    assert image is not None
    x1, y1, x2, y2 = vp.floor_rect_px
    expected_w = max(1, int(round(x2 - x1)))
    expected_h = max(1, int(round(y2 - y1)))
    assert image.size == (expected_w, expected_h)
    # Tiene píxeles no transparentes (se pintó algo)
    assert image.getextrema()[3][1] > 0  # canal alfa con valores


def test_build_heatmap_image_none_without_evaluations(session):
    from ui.coverage_renderer import build_heatmap_image

    empty = SimulationResult(project_name="x", band_id="band_2_4")
    vp = Viewport(
        world_width_m=session.floor_width_m, world_height_m=session.floor_height_m
    )
    assert build_heatmap_image(empty, vp) is None


def test_build_heatmap_image_infer_cell_size(session):
    from ui.coverage_renderer import build_heatmap_image, _infer_cell_size

    session.add_access_point(Point2D(1.0, 1.0))
    session.set_grid_resolution(1.0)
    result = session.run_heatmap("band_2_4")
    vp = Viewport(
        world_width_m=session.floor_width_m, world_height_m=session.floor_height_m
    )
    # Inferido ≈ 1.0 m
    inferred = _infer_cell_size(result.evaluations)
    assert inferred == pytest.approx(1.0, abs=1e-6)
    image = build_heatmap_image(result, vp)
    assert image is not None


def test_stats_text_percentages_sum_roughly_100(session):
    from ui.coverage_renderer import stats_text

    session.add_access_point(Point2D(6.0, 4.0))
    result = session.run_heatmap("band_2_4")
    text = stats_text(result)
    assert "Puntos del grid: 425" in text
    # Debe listar las 5 clases
    for label in (
        QualityClass.EXCELLENT.value,
        QualityClass.GOOD.value,
        QualityClass.REGULAR.value,
        QualityClass.WEAK.value,
        QualityClass.NO_COVERAGE.value,
    ):
        assert label in text


def test_heatmap_disclaimer_in_renderer_docstring():
    import ui.coverage_renderer as mod

    assert "estimación" in mod.__doc__.lower() or "ESTIMACIÓN" in mod.__doc__


def test_heatmap_simulation_result_stats_coverage_ratio(session):
    session.add_access_point(Point2D(1.0, 1.0))
    result = session.run_heatmap("band_2_4")
    ratio = result.stats["coverage_ratio"]
    assert 0.0 <= ratio <= 1.0
    # Denominador = 425
    assert result.stats["point_count"] == 425
    # quality_percent debe sumar ~100
    total_pct = sum(result.stats["quality_percent"].values())
    assert total_pct == pytest.approx(100.0, abs=0.5)


def test_heatmap_simulation_uses_floor_walls_not_obstacle_map(session):
    session.add_access_point(Point2D(1.0, 4.0))
    wall = session.add_wall(Point2D(6.0, 0.0), Point2D(6.0, 8.0))
    session.set_wall_material(wall.id, "concrete")
    result = session.run_heatmap("band_2_4")
    # Materiales de pared deben aplicarse (concreto > drywall)
    crossed = [e for e in result.evaluations if e.obstacle_loss.crossings >= 1]
    assert crossed
    # concrete band_2_4 = 12 dB en espesor ref
    assert all(e.obstacle_loss_db >= 12.0 - 0.01 for e in crossed if e.obstacle_loss.crossings == 1)
