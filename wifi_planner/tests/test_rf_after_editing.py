"""Fase 14-I: el pipeline RF (F10→F11→F12→F13) sobre geometría editada.

Las operaciones de la Fase 14 cambian el documento que el motor lee
(``floor.walls/openings/obstacles`` + posiciones de AP): aquí se prueba
que esos cambios alteran los resultados de forma coherente, que deshacer
los restaura exactamente, y que guardar/cargar no cambia la RF.
"""

from __future__ import annotations

import pytest

from core.geometry import Point2D, Rect
from tests.factories import make_session, run_rf_pipeline
from ui.session import EditorSession


def test_pipeline_runs_on_f14_edited_document():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    wall = session.add_wall(Point2D(4.0, 0.0), Point2D(4.0, 10.0))
    session.add_opening(wall.id, "door")
    session.add_access_point(Point2D(2.0, 5.0))
    session.add_access_point(Point2D(8.0, 5.0))
    session.add_obstacle(Point2D(6.0, 0.0), Point2D(7.0, 10.0))
    outcome = run_rf_pipeline(session.project, resolution_m=1.0)
    assert outcome.combined.stats["point_count"] > 0
    assert len(outcome.f11_results) == 2
    assert outcome.optimization is not None


def test_editing_wall_changes_rf_results():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    baseline = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    with_wall = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    # La barrera atenúa: el RSSI medio SINÁPTICO baja (o, como mínimo,
    # los resultados no pueden ser idénticos con geometría distinta).
    assert with_wall.combined.stats["rx_avg_dbm"] != baseline.combined.stats["rx_avg_dbm"]
    assert with_wall.combined.stats["rx_avg_dbm"] < baseline.combined.stats["rx_avg_dbm"]


def test_opening_in_wall_improves_propagation():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    wall = session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    blocked = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    session.add_opening(wall.id, "door", center_offset_m=5.0)
    opened = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    # El hueco elimina la atenuación en su abanico: el promedio sube.
    assert opened.combined.stats["rx_avg_dbm"] > blocked.combined.stats["rx_avg_dbm"]


def test_moving_ap_changes_rf_results():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    ap = session.add_access_point(Point2D(2.0, 5.0))
    near = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    session.move_ap(ap.id, Point2D(9.5, 0.5))
    far = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    assert near.combined.stats["rx_avg_dbm"] != far.combined.stats["rx_avg_dbm"]


def test_resizing_obstacle_changes_rf_results():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(1.0, 5.0))
    small = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    obstacle = session.add_obstacle(Point2D(0.0, 4.0), Point2D(1.0, 6.0))
    session.set_obstacle_rect(
        obstacle.id, Rect(x=3.0, y=0.0, width=3.0, height=10.0)
    )
    big = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    assert big.combined.stats["rx_avg_dbm"] < small.combined.stats["rx_avg_dbm"]


def test_undo_restores_exact_baseline_results():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    baseline = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    session.undo()  # deshacer la pared
    restored = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    assert restored.combined.stats["rx_avg_dbm"] == pytest.approx(
        baseline.combined.stats["rx_avg_dbm"], rel=1e-12
    )


def test_optimize_channels_runs_after_edits():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    session.add_opening(session.floor.walls[0].id, "door", center_offset_m=5.0)
    outcome = run_rf_pipeline(
        session.project, resolution_m=4.0, optimize=True
    )
    assert outcome.optimization is not None
    assert outcome.optimization.search in {"exhaustive", "coordinate_descent"}
    assert outcome.optimization.evaluation_count >= 1
    for channel in outcome.optimization.optimized_assignment.values():
        assert 1 <= channel <= 14


def test_save_load_preserves_rf_results(tmp_path):
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    wall = session.add_wall(Point2D(4.0, 0.0), Point2D(4.0, 10.0))
    session.add_opening(wall.id, "door", center_offset_m=5.0)
    session.add_access_point(Point2D(2.0, 5.0))
    before = run_rf_pipeline(session.project, resolution_m=1.0, optimize=False)
    path = str(tmp_path / "rf.json")
    session.save_project(path)

    loaded = EditorSession()
    loaded.open_project(path)
    after = run_rf_pipeline(loaded.project, resolution_m=1.0, optimize=False)
    assert after.combined.stats["rx_avg_dbm"] == pytest.approx(
        before.combined.stats["rx_avg_dbm"], rel=1e-12
    )
    assert after.combined.stats["sinr_avg_db"] == pytest.approx(
        before.combined.stats["sinr_avg_db"], rel=1e-12
    )


def test_session_heatmap_works_after_geometry_edits():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    wall = session.add_wall(Point2D(5.0, 0.0), Point2D(5.0, 10.0))
    session.add_opening(wall.id, "door", center_offset_m=5.0)
    result = session.run_heatmap()
    assert result.stats["point_count"] > 0
    assert "rx_avg_dbm" in result.stats
    # La edición posterior invalida y el recálculo sigue funcionando.
    session.move_wall(wall.id, Point2D(1.0, 0.0))
    assert session.heatmap_dirty is True
    result2 = session.run_heatmap()
    assert result2.stats["point_count"] == result.stats["point_count"]


def test_snr_and_interference_blocks_available_after_edits():
    session = make_session()
    session.set_floor_dimensions(10.0, 10.0)
    session.add_access_point(Point2D(2.0, 5.0))
    session.add_access_point(Point2D(7.0, 5.0))
    outcome = run_rf_pipeline(session.project, resolution_m=1.0, optimize=True)
    # F11: un resultado por AP con muestras reales tras las ediciones.
    assert len(outcome.f11_results) == 2
    assert all(result.stats["point_count"] > 0 for result in outcome.f11_results)
    # Los APs creados no llevan canal ⇒ F11 no modela interferencia y F12
    # debe cumplir la igualdad exacta SINR = SNR (decisión CG).
    assert all(
        evaluation.interference_dbm is None
        for result in outcome.f11_results
        for evaluation in result.evaluations
    )
    assert outcome.combined.stats["sinr_avg_db"] is not None
    assert outcome.combined.stats["sinr_avg_db"] == pytest.approx(
        outcome.combined.stats["snr_avg_db"]
    )
