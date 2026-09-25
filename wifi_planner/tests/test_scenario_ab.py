"""Prueba arquitectónica A/B/C (F14-A): el motor es independiente del edificio.

Demuestra formalmente que ``Project`` + ``Floor`` + entidades geométricas
son la ÚNICA fuente de verdad y que la MISMA secuencia

    F10 → F11 → F12 → (+ F13)

procesa escenarios muy distintos (casa 10×10, oficina 50×30, nave
120×80) sin ninguna rama por escenario y sin modificar ``engine/``.

No hay modelo ``Scenario``: cada escenario es un proyecto del dominio
existente construido con ``tests.factories``.
"""

from __future__ import annotations

import inspect
import math

from core.channel import validate_channel_config
from persistence import load_project, save_project
from tests.factories import (
    floor_of,
    grid_for,
    make_session,
    run_rf_pipeline,
    scenario_a,
    scenario_b,
    scenario_c,
)

RESOLUTION_M = 0.5
COARSE_M = 4.0


# ---------------------------------------------------------------------------
# 1. Los escenarios son válidos (dominio existente, sin Scenario)
# ---------------------------------------------------------------------------


def test_scenario_a_is_valid():
    project = scenario_a()
    floor = floor_of(project)
    assert (floor.width_m, floor.height_m) == (10.0, 10.0)
    assert len(floor.walls) == 2
    assert len(project.access_points) == 1
    ap = project.access_points[0]
    assert 0.0 <= ap.position.x <= floor.width_m
    assert 0.0 <= ap.position.y <= floor.height_m
    band = project.get_band(ap.band_id)
    validate_channel_config(band, ap.channel, ap.radio.channel_width_mhz)


def test_scenario_b_is_valid():
    project = scenario_b()
    floor = floor_of(project)
    assert (floor.width_m, floor.height_m) == (50.0, 30.0)
    assert len(floor.walls) == 20
    assert len(project.access_points) == 4
    for ap in project.access_points:
        assert 0.0 <= ap.position.x <= floor.width_m
        assert 0.0 <= ap.position.y <= floor.height_m
        band = project.get_band(ap.band_id)
        validate_channel_config(band, ap.channel, ap.radio.channel_width_mhz)
    # Dos APs comparten canal 6: interferencia real (coherente con F11).
    channels = [ap.channel for ap in project.access_points]
    assert channels.count(6) == 2


def test_scenario_c_is_valid():
    project = scenario_c()
    floor = floor_of(project)
    assert (floor.width_m, floor.height_m) == (120.0, 80.0)
    assert len(floor.walls) == 36
    assert len(project.access_points) == 6
    for ap in project.access_points:
        assert 0.0 <= ap.position.x <= floor.width_m
        assert 0.0 <= ap.position.y <= floor.height_m


# ---------------------------------------------------------------------------
# 2. Los grids se generan desde las dimensiones del dominio
# ---------------------------------------------------------------------------


def test_grids_match_floor_dimensions():
    # 10/0.5 → 21 puntos por eje (21×21 = 441).
    assert grid_for(scenario_a(), RESOLUTION_M).point_count == 21 * 21
    # 50/0.5 → 101 · 30/0.5 → 61 (101×61 = 6161).
    assert grid_for(scenario_b(), RESOLUTION_M).point_count == 101 * 61
    # 120/4 → 31 · 80/4 → 21 (31×21 = 651).
    assert grid_for(scenario_c(), COARSE_M).point_count == 31 * 21


# ---------------------------------------------------------------------------
# 3. F10 en ambos escenarios (misma secuencia, sin ramas)
# ---------------------------------------------------------------------------


def test_f10_runs_on_both_scenarios():
    outcome_a = run_rf_pipeline(scenario_a(), resolution_m=RESOLUTION_M, optimize=False)
    outcome_b = run_rf_pipeline(scenario_b(), resolution_m=1.0, optimize=False)

    for outcome, point_count in (
        (outcome_a, 441),
        (outcome_b, 51 * 31),
    ):
        assert outcome.combined.stats["point_count"] == point_count
        for result in outcome.base_results.values():
            assert len(result.evaluations) == point_count
            for evaluation in result.evaluations:
                assert math.isfinite(evaluation.rx_power_dbm)
                assert evaluation.snr_db is not None

    # La geometría produce pérdidas reales: tras la pared de x=4 en A…
    crossed_a = [
        e
        for e in outcome_a.base_results["AP-001"].evaluations
        if e.point.x > 4.0 and e.point.y < 6.0
    ]
    assert crossed_a and all(e.obstacle_loss_db > 0.0 for e in crossed_a)
    # …y al menos un cruce de pared en B (20 paredes).
    assert any(
        e.obstacle_loss_db > 0.0 for e in outcome_b.base_results["AP-001"].evaluations
    )


# ---------------------------------------------------------------------------
# 4. F11 en ambos escenarios
# ---------------------------------------------------------------------------


def test_f11_runs_on_both_scenarios():
    outcome_a = run_rf_pipeline(scenario_a(), resolution_m=RESOLUTION_M, optimize=False)
    outcome_b = run_rf_pipeline(scenario_b(), resolution_m=1.0, optimize=False)

    # A: 1 AP con canal → F11 se ejecuta (emisión deseada, 0 interferentes).
    evals_a = outcome_a.f12_results[0].evaluations
    assert any(e.interference_evaluated for e in evals_a)
    assert all(e.interference_dbm is None for e in evals_a)

    # B: APs en el mismo canal 6 → interferencia real en algunos puntos.
    interference_points = 0
    for result in outcome_b.f11_results:
        for evaluation in result.evaluations:
            if evaluation.interference_evaluated and evaluation.interference_dbm is not None:
                interference_points += 1
    assert interference_points > 0


# ---------------------------------------------------------------------------
# 5. F12 en ambos escenarios
# ---------------------------------------------------------------------------


def test_f12_runs_on_both_scenarios():
    outcome_a = run_rf_pipeline(scenario_a(), resolution_m=RESOLUTION_M, optimize=False)
    outcome_b = run_rf_pipeline(scenario_b(), resolution_m=1.0, optimize=False)

    # A: sin interferencia modelada, SINR == SNR exactamente (decisión CG).
    for evaluation in outcome_a.f12_results[0].evaluations:
        assert evaluation.sinr_db is not None
        assert evaluation.sinr_db == evaluation.snr_db

    # B: donde hay interferencia, SINR < SNR (el denominador incluye I).
    tighter = [
        e
        for result in outcome_b.f12_results
        for e in result.evaluations
        if e.interference_dbm is not None and e.sinr_db < e.snr_db
    ]
    assert tighter
    # El heatmap combinado transporta SINR del ganador por MAX RSSI.
    assert outcome_b.combined.stats["sinr_avg_db"] is not None
    assert outcome_b.combined.stats["sinr_min_db"] is not None


# ---------------------------------------------------------------------------
# 6. F13 en ambos escenarios
# ---------------------------------------------------------------------------


def test_f13_runs_on_both_scenarios():
    # A: 1 AP → espacio 14 canales ≤ 64 ⇒ exhaustive.
    outcome_a = run_rf_pipeline(scenario_a(), resolution_m=RESOLUTION_M, optimize=True)
    optimization_a = outcome_a.optimization
    assert optimization_a is not None
    assert optimization_a.search == "exhaustive"
    assert 1 <= optimization_a.evaluation_count <= 15
    assert optimization_a.original_score is not None
    assert optimization_a.optimized_score is not None
    assert optimization_a.improvement is not None and optimization_a.improvement >= 0.0
    assert set(optimization_a.optimized_assignment) == {"AP-001"}

    # B: 4 APs → 14^4 > 64 ⇒ coordinate_descent (óptimo local).
    # Se usa una malla gruesa para que la corrida sea rápida: la secuencia
    # es exactamente la misma (mismo código, mismas APIs).
    outcome_b = run_rf_pipeline(scenario_b(), resolution_m=COARSE_M, optimize=True)
    optimization_b = outcome_b.optimization
    assert optimization_b is not None
    assert optimization_b.search == "coordinate_descent"
    assert optimization_b.evaluation_count > 1
    assert optimization_b.original_score is not None
    assert optimization_b.optimized_score is not None
    assert optimization_b.improvement is not None and optimization_b.improvement >= 0.0
    assert set(optimization_b.optimized_assignment) == {
        ap.id for ap in scenario_b().access_points
    }


# ---------------------------------------------------------------------------
# 7. Los resultados dependen de la geometría
# ---------------------------------------------------------------------------


def test_results_depend_on_geometry():
    with_walls = run_rf_pipeline(scenario_a(), resolution_m=RESOLUTION_M, optimize=False)
    project = scenario_a()
    floor_of(project).walls.clear()  # mismo edificio, sin paredes
    without_walls = run_rf_pipeline(project, resolution_m=RESOLUTION_M, optimize=False)

    # Misma malla y mismos APs: solo cambia la geometría.
    assert (
        with_walls.combined.stats["point_count"]
        == without_walls.combined.stats["point_count"]
    )
    # Sin paredes no hay pérdida por obstáculos y el RSSI medio sube.
    assert without_walls.combined.stats["rx_avg_dbm"] > with_walls.combined.stats["rx_avg_dbm"]

    # Escenarios distintos producen heatmaps distintos.
    outcome_b = run_rf_pipeline(scenario_b(), resolution_m=1.0, optimize=False)
    assert (
        with_walls.combined.stats["rx_avg_dbm"]
        != outcome_b.combined.stats["rx_avg_dbm"]
    )


# ---------------------------------------------------------------------------
# 8. engine/ no necesita modificaciones (misma función, sin rama)
# ---------------------------------------------------------------------------


def test_pipeline_has_no_scenario_branch():
    import ast

    source = inspect.getsource(run_rf_pipeline)
    # Ni identificadores de escenario ni ramas por escenario.
    assert "scenario_" not in source
    tree = ast.parse(source)
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not any(name.startswith("scenario_") for name in referenced)
    # La única fuente de verdad de la geometría son Floor + listas.
    assert "floor.walls" in source
    assert "floor.openings" in source
    assert "floor.obstacles" in source


def test_engine_api_is_geometry_primitive_driven():
    # El motor recibe primitivas, no un "edificio": si estas APIs
    # existen, F14 no necesita tocar engine/.
    from engine import (
        CoverageGrid,
        annotate_interference,
        annotate_sinr,
        combine_results,
        optimize_channels,
        simulate_coverage,
    )

    assert callable(simulate_coverage)
    assert callable(annotate_interference)
    assert callable(annotate_sinr)
    assert callable(combine_results)
    assert callable(optimize_channels)
    assert CoverageGrid is not None


# ---------------------------------------------------------------------------
# 9. Tercer escenario grande (económico: resolución gruesa, sin F13)
# ---------------------------------------------------------------------------


def test_scenario_c_scales_to_large_building():
    outcome = run_rf_pipeline(scenario_c(), resolution_m=COARSE_M, optimize=False)
    assert outcome.combined.stats["point_count"] == 651
    assert len(outcome.base_results) == 6
    assert any(
        e.obstacle_loss_db > 0.0
        for result in outcome.base_results.values()
        for e in result.evaluations
    )
    # F11 con 6 APs y canales repetidos: interferencia real presente.
    assert any(
        e.interference_dbm is not None
        for result in outcome.f11_results
        for e in result.evaluations
    )


# ---------------------------------------------------------------------------
# 10. Los escenarios sobreviven el round-trip de persistencia (v1)
# ---------------------------------------------------------------------------


def test_scenarios_survive_persistence_roundtrip(tmp_path):
    for index, builder in enumerate((scenario_a, scenario_b, scenario_c), start=1):
        project = builder()
        path = tmp_path / f"scenario_{index}.json"
        save_project(project, path)
        loaded, _editor = load_project(path)
        assert (loaded.floors[0].width_m, loaded.floors[0].height_m) == (
            project.floors[0].width_m,
            project.floors[0].height_m,
        )
        assert len(loaded.floors[0].walls) == len(project.floors[0].walls)
        assert len(loaded.access_points) == len(project.access_points)
        assert [ap.channel for ap in loaded.access_points] == [
            ap.channel for ap in project.access_points
        ]


# ---------------------------------------------------------------------------
# 11. Fábrica de sesiones (reduce las 8 copias de fixtures)
# ---------------------------------------------------------------------------


def test_make_session_factory_returns_default_session():
    session = make_session()
    assert session.floor_width_m == 12.0
    assert session.floor_height_m == 8.0
    assert session.project.floors
