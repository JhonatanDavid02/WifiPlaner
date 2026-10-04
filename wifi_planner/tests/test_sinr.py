"""Pruebas de SINR (Fase 12).

Cubre: la fórmula única y estable en ``engine/sinr.py`` (CH/CF/CG),
clasificación frente al objetivo, validación de ``sinr_target_db``,
integración con la física histórica (evaluate_link, simulación,
anotación tras F11, combinación por MAX RSSI), UI (métrica, leyenda,
panel, clientes, resumen) y persistencia (umbral opcional, sin
resultados derivados, schema v1 intacto).

Fronteras verificadas aquí:
- SINR es INFORMACIÓN PARALELA: RSSI/SOM/SNR/calidad/veredicto,
  ``combine_results`` y ``_better`` no cambian (auditoría + regresión).
- Sin interferencia modelada: SINR == SNR exactamente (decisión CG).
- Los resultados derivados (``sinr_db``) NUNCA se escriben en el JSON.
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from core.access_point import AccessPoint
from core.band import DEFAULT_BANDS
from core.geometry import Point2D
from core.project import (
    DEFAULT_SINR_TARGET_DB,
    SINR_TARGET_MAX_DB,
    SINR_TARGET_MIN_DB,
    CoverageThresholds,
    Project,
)
from core.result import LinkEvaluation, ObstacleLoss, QualityClass, SimulationResult, Verdict
from core.radio import RadioConfiguration
from engine.classifier import meets_sinr_target, sinr_diagnostic
from engine.interference import annotate_interference, emission_for_ap
from engine.link_budget import evaluate_link, signal_to_noise_ratio
from engine.simulator import simulate_coverage
from engine.sinr import (
    annotate_sinr,
    interference_plus_noise_dbm,
    signal_to_interference_noise_ratio,
    sinr_stats_block,
)
from persistence import ProjectFormatError, load_project
from ui.session import EditorSession
from tests.factories import make_session

BAND_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")


@pytest.fixture
def session() -> EditorSession:
    return make_session()


def _ap(ap_id: str, channel: int, width_mhz: int = 20,
        position: Point2D = Point2D(0.0, 0.0)) -> AccessPoint:
    return AccessPoint(
        id=ap_id,
        position=position,
        radio=RadioConfiguration(channel_width_mhz=width_mhz),
        band_id="band_5",
        channel=channel,
    )


def _simulate(ap: AccessPoint, band=BAND_5, points=(Point2D(5.0, 0.0),)):
    return simulate_coverage(
        project=Project(name="f12"),
        access_point=ap,
        frequency_band=band,
        sample_points=list(points),
    )


def _cochannel_results():
    """Dos APs en canal 36 con interferencia real (patrón F11)."""
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    return annotate_interference([r_a, r_b], emissions)


# ===========================================================================
# A. Fórmula única y estable (decisión CF)
# ===========================================================================

def test_sinr_without_interference_equals_snr_exactly():
    """Sin I modelada: denominador = ruido ⇒ SINR == SNR (decisión CG)."""
    for rx, noise in ((-50.0, -95.0), (-67.0, -95.0), (-33.3, -90.0), (0.0, -100.0)):
        assert signal_to_interference_noise_ratio(rx, noise, None) == signal_to_noise_ratio(
            rx, noise
        )


def test_sinr_reference_values():
    # ruido == interferencia: denominador = N + 10·log10(2).
    assert signal_to_interference_noise_ratio(-50.0, -60.0, -60.0) == 6.99
    # I ≫ N (I domina el denominador): SINR ≈ rx − I.
    assert signal_to_interference_noise_ratio(-50.0, -95.0, -60.0) == 10.0
    # N ≫ I: el aporte de I es despreciable (denominador ≈ ruido).
    assert interference_plus_noise_dbm(-30.0, -1000.0) == -30.0


def test_denominator_is_commutative_and_bounded():
    for n, i in ((-95.0, -60.0), (-60.0, -95.0), (-70.0, -70.0), (-95.0, -30.0)):
        denom = interference_plus_noise_dbm(n, i)
        assert denom == interference_plus_noise_dbm(i, n)
        # Entre max(N, I) y max(N, I) + 10·log10(2) (la suma nunca baja).
        assert max(n, i) <= denom <= max(n, i) + 3.0103 + 1e-9


def test_denominator_none_returns_noise_exactly():
    assert interference_plus_noise_dbm(-95.0, None) == -95.0
    assert math.isfinite(interference_plus_noise_dbm(-95.0, None))


def test_no_overflow_no_underflow_extremes():
    # Forma basada en el máximo: exponentes ≤ 0, sin overflow jamás.
    assert math.isfinite(interference_plus_noise_dbm(-1000.0, -1000.0))
    assert math.isfinite(interference_plus_noise_dbm(-1000.0, 1000.0))
    assert math.isfinite(signal_to_interference_noise_ratio(1000.0, -1000.0, 1000.0))
    # Underflow benigno: 10^(muy negativo) → 0 ⇒ log10(1) = 0.
    assert interference_plus_noise_dbm(-30.0, -1000.0) == -30.0


def test_formula_rejects_non_finite_and_non_numeric():
    for bad in (float("nan"), float("inf"), float("-inf"), True, "x"):
        with pytest.raises(ValueError):
            signal_to_interference_noise_ratio(bad, -95.0, None)
        with pytest.raises(ValueError):
            interference_plus_noise_dbm(-95.0, bad)
    # None es válido como interferencia (caso CG) pero NO como rx/ruido.
    with pytest.raises(ValueError):
        signal_to_interference_noise_ratio(None, -95.0, None)
    with pytest.raises(ValueError):
        interference_plus_noise_dbm(None, -60.0)
    # rx no finito también se rechaza.
    with pytest.raises(ValueError):
        signal_to_interference_noise_ratio(float("nan"), -95.0, -60.0)


def test_sinr_rounded_to_two_decimals():
    for rx, noise, i in ((-50.0, -95.0, None), (-53.333, -95.0, -60.0), (-47.7, -91.0, -70.0)):
        value = signal_to_interference_noise_ratio(rx, noise, i)
        assert abs(value * 100 - round(value * 100)) < 1e-9


def test_interference_never_improves_sinr():
    base = signal_to_interference_noise_ratio(-50.0, -95.0, None)
    with_i = signal_to_interference_noise_ratio(-50.0, -95.0, -60.0)
    assert with_i <= base


# ===========================================================================
# B. Clasificación frente al objetivo (decisión CH)
# ===========================================================================

def test_meets_sinr_target_boundary_geq():
    thresholds = CoverageThresholds()
    assert meets_sinr_target(25.0, thresholds) is True  # en el umbral: cumple
    assert meets_sinr_target(24.99, thresholds) is False
    assert meets_sinr_target(45.0, thresholds) is True


def test_meets_sinr_target_custom_threshold():
    thresholds = CoverageThresholds(sinr_target_db=30.0)
    assert meets_sinr_target(30.0, thresholds) is True
    assert meets_sinr_target(29.99, thresholds) is False


def test_sinr_diagnostic_two_labels():
    thresholds = CoverageThresholds()
    assert sinr_diagnostic(45.0, thresholds) == "SINR adecuado"
    assert sinr_diagnostic(10.0, thresholds) == "SINR bajo"


def test_sinr_diagnostic_does_not_replace_rf_diagnostic():
    from engine.classifier import rf_diagnostic

    thresholds = CoverageThresholds()
    # rf_diagnostic sigue con sus 4 salidas exactas (F7 intacto).
    assert rf_diagnostic(-40.0, 45.0, thresholds) == "RSSI adecuado / SNR adecuado"
    assert sinr_diagnostic(45.0, thresholds) == "SINR adecuado"


# ===========================================================================
# C. Umbrales CoverageThresholds (core)
# ===========================================================================

def test_sinr_target_default_is_25():
    assert CoverageThresholds().sinr_target_db == DEFAULT_SINR_TARGET_DB == 25.0


def test_sinr_target_accepts_range_bounds():
    assert CoverageThresholds(sinr_target_db=SINR_TARGET_MIN_DB).sinr_target_db == -20.0
    assert CoverageThresholds(sinr_target_db=SINR_TARGET_MAX_DB).sinr_target_db == 60.0
    assert CoverageThresholds(sinr_target_db=-10).sinr_target_db == -10.0  # int aceptado


def test_sinr_target_rejects_out_of_range_and_bad_types():
    with pytest.raises(ValueError):
        CoverageThresholds(sinr_target_db=60.01)
    with pytest.raises(ValueError):
        CoverageThresholds(sinr_target_db=-20.01)
    with pytest.raises(ValueError):
        CoverageThresholds(sinr_target_db=True)
    with pytest.raises(ValueError):
        CoverageThresholds(sinr_target_db="25")
    with pytest.raises(ValueError):
        CoverageThresholds(sinr_target_db=float("nan"))


def test_coverage_thresholds_is_frozen_with_new_field():
    thresholds = CoverageThresholds()
    with pytest.raises(dataclasses.FrozenInstanceError):
        thresholds.sinr_target_db = 10.0  # type: ignore[misc]


# ===========================================================================
# D. Integración con la física histórica (motor puro)
# ===========================================================================

def test_evaluate_link_sets_sinr_equal_to_snr_without_interference():
    thresholds = CoverageThresholds()
    ev = evaluate_link(
        radio=RadioConfiguration(),
        access_point_id="AP-001",
        band_id="band_5",
        ap_position=Point2D(0.0, 0.0),
        client_position=Point2D(5.0, 0.0),
        frequency_mhz=5180.0,
        thresholds=thresholds,
    )
    assert ev.sinr_db is not None
    assert ev.sinr_db == ev.snr_db
    assert ev.sinr_meets_target == (ev.sinr_db >= thresholds.sinr_target_db)


def test_evaluate_link_keeps_historic_fields_identical():
    thresholds = CoverageThresholds()
    common = dict(
        radio=RadioConfiguration(),
        access_point_id="AP-001",
        band_id="band_5",
        ap_position=Point2D(0.0, 0.0),
        client_position=Point2D(5.0, 0.0),
        frequency_mhz=5180.0,
        thresholds=thresholds,
    )
    ev = evaluate_link(**common)
    assert ev.rx_power_dbm == evaluate_link(**common).rx_power_dbm
    assert ev.snr_db == evaluate_link(**common).snr_db
    assert ev.som_db == evaluate_link(**common).som_db
    assert ev.quality == evaluate_link(**common).quality
    assert ev.verdict == evaluate_link(**common).verdict


def test_simulate_coverage_stats_include_sinr_block():
    result = _simulate(_ap("AP-001", 36))
    stats = result.stats
    for key in (
        "sinr_min_db",
        "sinr_max_db",
        "sinr_avg_db",
        "sinr_target_db",
        "points_meeting_sinr_target",
        "sinr_ratio",
    ):
        assert key in stats, key
    assert stats["sinr_target_db"] == 25.0
    # Sin interferencia modelada: bloque SINR idéntico al SNR.
    assert stats["sinr_min_db"] == stats["snr_min_db"]
    assert stats["sinr_max_db"] == stats["snr_max_db"]
    assert stats["sinr_ratio"] == stats["snr_ratio"]


def test_annotate_sinr_after_interference_lowers_sinr_keeps_legacy():
    results = _cochannel_results()
    thresholds = CoverageThresholds()
    annotated = annotate_sinr(results, thresholds)
    for before, after in zip(results, annotated):
        for old, new in zip(before.evaluations, after.evaluations):
            # Los campos históricos son idénticos (nada se muta).
            assert new.rx_power_dbm == old.rx_power_dbm
            assert new.snr_db == old.snr_db
            assert new.interference_dbm == old.interference_dbm
            # El SINR se recalcula con I y nunca supera al SNR.
            assert new.sinr_db is not None
            assert new.sinr_db <= new.snr_db
            if new.interference_dbm is not None:
                assert new.sinr_db < new.snr_db
                assert new.sinr_db == signal_to_interference_noise_ratio(
                    new.rx_power_dbm, new.noise_floor_dbm, new.interference_dbm
                )
            # Cumplimiento coherente con el umbral.
            assert new.sinr_meets_target == (new.sinr_db >= thresholds.sinr_target_db)
    # El resultado original NO cambió (patrón replace de F11).
    assert results[0].evaluations[0].sinr_db == results[0].evaluations[0].snr_db


def test_annotate_sinr_model_ran_without_contributors_equals_snr():
    # Canales que no se solapan: F11 corre el modelo pero I es None.
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 40, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    annotated = annotate_sinr(
        annotate_interference([r_a, r_b], emissions), CoverageThresholds()
    )
    for ev in annotated[0].evaluations:
        assert ev.interference_evaluated is True
        assert ev.interference_dbm is None
        assert ev.sinr_db == ev.snr_db


def test_annotate_sinr_empty_results_is_empty():
    assert annotate_sinr([], CoverageThresholds()) == []


def test_annotate_sinr_updates_stats_block():
    results = _cochannel_results()
    annotated = annotate_sinr(results, CoverageThresholds())
    stats = annotated[0].stats
    values = [e.sinr_db for e in annotated[0].evaluations]
    assert stats["sinr_min_db"] == min(values)
    assert stats["sinr_max_db"] == max(values)
    assert stats["sinr_ratio"] <= stats.get("snr_ratio", 1.0) + 1e-9


def test_sinr_stats_block_edge_cases():
    assert sinr_stats_block([], 25.0) == {}
    result = _simulate(_ap("AP-001", 36))
    plain = tuple(
        dataclasses.replace(e, sinr_db=None) for e in result.evaluations
    )
    assert sinr_stats_block(plain, 25.0) == {}

    block = sinr_stats_block(result.evaluations, 25.0)
    assert set(block) == {
        "sinr_min_db",
        "sinr_max_db",
        "sinr_avg_db",
        "sinr_target_db",
        "points_meeting_sinr_target",
        "sinr_ratio",
    }
    assert block["sinr_target_db"] == 25.0
    assert block["sinr_ratio"] == round(
        block["points_meeting_sinr_target"] / len(result.evaluations), 4
    )


# ===========================================================================
# E. Integración en la sesión (heatmap combinado y simulación)
# ===========================================================================

def _two_cochannel_aps(session: EditorSession):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    return ap1, ap2


def test_run_heatmap_annotates_sinr_for_every_point(session):
    _two_cochannel_aps(session)
    combined = session.run_heatmap("band_5")
    assert combined.stats["source_results"] == 2
    for ev in combined.evaluations:
        assert ev.sinr_db is not None
        assert ev.sinr_db <= ev.snr_db
        # Autorconsistencia: el SINR del ganador sale de sus propios datos.
        assert ev.sinr_db == signal_to_interference_noise_ratio(
            ev.rx_power_dbm, ev.noise_floor_dbm, ev.interference_dbm
        )
    for key in ("sinr_min_db", "sinr_max_db", "sinr_avg_db", "sinr_ratio"):
        assert key in combined.stats


def test_run_heatmap_single_ap_sinr_equals_snr(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_5")
    assert all(e.sinr_db == e.snr_db for e in result.evaluations)
    assert "sinr_min_db" in result.stats


def test_run_simulation_annotates_sinr_with_context(session):
    _two_cochannel_aps(session)
    result = session.run_simulation()
    assert any(
        e.interference_dbm is not None and e.sinr_db < e.snr_db
        for e in result.evaluations
    )
    assert all(e.sinr_db <= e.snr_db for e in result.evaluations)
    assert "sinr_min_db" in result.stats


def test_sinr_does_not_change_winner_selection(session):
    """El combinador sigue eligiendo por MAX RSSI (BX/BB intactos)."""
    ap1, ap2 = _two_cochannel_aps(session)
    combined = session.run_heatmap("band_5")
    # Recalcula el ganador esperado con la MISMA regla histórica de
    # combine._better: mayor RSSI y, en empate, menor id.
    best = {}
    for ev in combined.evaluations:
        key = (ev.point.x, ev.point.y)
        current = best.get(key)
        if current is None or ev.rx_power_dbm > current.rx_power_dbm or (
            ev.rx_power_dbm == current.rx_power_dbm
            and ev.access_point_id < current.access_point_id
        ):
            best[key] = ev
    for ev in combined.evaluations:
        key = (ev.point.x, ev.point.y)
        assert ev.access_point_id == best[key].access_point_id
    assert set(combined.stats["ap_dominance_percent"]) == {ap1.id, ap2.id}


# ===========================================================================
# F. UI: métrica, leyenda, panel, clientes, resumen
# ===========================================================================

def test_heatmap_metrics_registry_includes_sinr():
    from ui.coverage_renderer import (
        HEATMAP_METRICS,
        HEATMAP_METRIC_SINR,
    )

    assert HEATMAP_METRIC_SINR == "sinr"
    assert HEATMAP_METRICS == ("rssi", "snr", "interference", "sinr")


def test_heatmap_metric_enum_stays_frozen_f7():
    from ui.session import HeatmapMetric

    assert {m.value for m in HeatmapMetric} == {"rssi", "snr"}


def test_set_heatmap_metric_accepts_sinr_without_dirty(session, tmp_path):
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    session.save_project(str(tmp_path / "clean.json"))  # limpia el dirty
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    session.set_heatmap_metric("sinr")
    assert session.heatmap_metric == "sinr"
    # Vista pura: NO invalida el RF ya calculado.
    assert session.heatmap_dirty is False
    assert session.dirty is False  # es vista, no configuración (BA)
    session.set_heatmap_metric("sinr")  # idempotente
    assert session.heatmap_metric == "sinr"
    with pytest.raises(ValueError):
        session.set_heatmap_metric("potencia")


def test_toolbar_metric_labels_include_sinr():
    from ui.panels.toolbar import METRIC_ID_BY_LABEL, METRIC_LABEL_BY_ID

    assert METRIC_LABEL_BY_ID["sinr"] == "SINR"
    assert METRIC_ID_BY_LABEL["SINR"] == "sinr"
    assert list(METRIC_LABEL_BY_ID.values()) == [
        "RSSI",
        "SNR",
        "Interferencia",
        "SINR",
    ]


def test_legend_title_and_rows_for_sinr():
    from ui.coverage_renderer import legend_rows, legend_title

    assert legend_title("sinr") == "SINR (dB)"
    rows = legend_rows(CoverageThresholds(), "sinr")
    assert len(rows) == 2
    assert rows[0]["label"] == "SINR objetivo"
    assert rows[0]["range"] == "≥ 25 dB"
    assert rows[1]["range"] == "< 25 dB"
    rows30 = legend_rows(CoverageThresholds(sinr_target_db=30.0), "sinr")
    assert rows30[0]["range"] == "≥ 30 dB"


def test_sinr_color_scale_normal_direction():
    from ui.coverage_renderer import sinr_to_color, sinr_to_rgb

    # Igual que SNR: 0 dB malo (morado), 45 dB excelente (verde).
    assert sinr_to_rgb(0.0) == (90, 60, 90)
    assert sinr_to_rgb(45.0) == (80, 200, 120)
    assert sinr_to_rgb(1000.0) == (80, 200, 120)  # clamp
    assert sinr_to_rgb(None) == (150, 150, 150)  # sin datos
    r, g, b, a = sinr_to_color(-100.0, alpha=110)
    assert a == 110
    # Dirección normal: más alto ⇒ más verde que más bajo.
    assert sinr_to_rgb(40.0)[1] > sinr_to_rgb(5.0)[1]


def test_build_heatmap_image_supports_sinr_metric(session):
    from ui.coverage_renderer import build_heatmap_image
    from ui.viewport import Viewport

    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_5")
    vp = Viewport(world_width_m=12.0, world_height_m=8.0)
    image = build_heatmap_image(result, vp, cell_size_m=2.0, metric="sinr")
    assert image is not None and image.size[0] > 0 and image.size[1] > 0


def test_heatmap_stats_text_header_for_sinr_metric(session):
    _two_cochannel_aps(session)
    session.run_heatmap("band_5")
    session.set_heatmap_metric("sinr")
    text = session.heatmap_stats_text()
    assert "Métrica: SINR (dB)" in text
    assert "SINR objetivo: 25 dB" in text
    assert "SINR (dB):" in text  # bloque de estadísticas


def test_stats_text_shows_sinr_block_when_present(session):
    from ui.coverage_renderer import stats_text

    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_2_4")
    text = stats_text(result)
    assert "SINR (dB):" in text
    assert "≥ objetivo 25 dB" in text


def test_stats_text_tolerates_legacy_stats_without_sinr_keys():
    from ui.coverage_renderer import stats_text

    ev = LinkEvaluation(
        access_point_id="AP-001",
        band_id="band_2_4",
        point=Point2D(0, 0),
        distance_m=1.0,
        path_loss_db=40.0,
        obstacle_loss_db=0.0,
        obstacle_loss=ObstacleLoss(total_db=0.0, crossings=0),
        rx_power_dbm=-50.0,
        som_db=25.0,
        rssi_meets_target=True,
        verdict=Verdict.APROBADO,
        quality=QualityClass.EXCELLENT,
    )
    result = SimulationResult(
        project_name="x",
        band_id="band_2_4",
        evaluations=(ev,),
        stats={
            "point_count": 1,
            "rx_min_dbm": -50.0,
            "rx_max_dbm": -50.0,
            "rx_avg_dbm": -50.0,
            "quality_counts": {"Excelente": 1},
        },
    )
    text = stats_text(result)
    assert "SINR (dB):" not in text
    assert "SNR (dB):" not in text


def test_ap_sinr_lines_panel(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    # Sin corrida: «sin datos» honesto.
    assert session.ap_sinr_lines(ap.id) == ["SINR: — (sin datos de corrida)"]
    # AP desconocido: vacío.
    assert session.ap_sinr_lines("AP-999") == []
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    session.run_heatmap("band_5")
    lines = session.ap_sinr_lines(ap.id)
    assert lines[0] == "SINR (dB):"
    assert any("mínimo" in ln for ln in lines)
    assert any("≥ objetivo 25 dB" in ln for ln in lines)


def test_ap_sinr_lines_without_channel_still_has_data(session):
    # SINR existe aunque el AP no tenga canal (depende de P_rx/ruido).
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    session.run_heatmap("band_2_4")
    lines = session.ap_sinr_lines(ap.id)
    assert lines[0] == "SINR (dB):"


def test_client_rssi_lines_include_sinr_diagnostic(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.add_client(Point2D(4.0, 4.0))
    session.set_grid_resolution(1.0)
    session.run_heatmap("band_2_4")
    lines = session.client_rssi_lines()
    assert lines, "se esperaba una línea por cliente"
    assert "SINR " in lines[0]
    assert "dB (SINR " in lines[0]
    assert any(tag in lines[0] for tag in ("SINR adecuado", "SINR bajo"))


def test_simulation_summary_text_includes_sinr(session):
    _two_cochannel_aps(session)
    session.run_simulation()
    text = session.simulation_summary_text()
    assert "SINR mínimo:" in text
    assert "SINR máximo:" in text
    # El histórico sigue intacto.
    assert "SNR mínimo:" in text and "RSSI mínimo:" in text


def test_apply_rf_settings_updates_sinr_target(session):
    session.apply_rf_settings(
        noise_floor_dbm=-95.0,
        snr_target_db=25.0,
        rssi_target_dbm=-67.0,
        wifi_standard="802.11ax",
        channel_width_mhz=20,
        sinr_target_db=30.0,
    )
    assert session.project.thresholds.sinr_target_db == 30.0
    # Sin el kwarg (llamadores F7) se conserva el actual.
    session.apply_rf_settings(
        noise_floor_dbm=-95.0,
        snr_target_db=25.0,
        rssi_target_dbm=-67.0,
        wifi_standard="802.11ax",
        channel_width_mhz=20,
    )
    assert session.project.thresholds.sinr_target_db == 30.0
    # Inválido ⇒ ValueError atómico.
    with pytest.raises(ValueError):
        session.apply_rf_settings(
            noise_floor_dbm=-95.0,
            snr_target_db=25.0,
            rssi_target_dbm=-67.0,
            wifi_standard="802.11ax",
            channel_width_mhz=20,
            sinr_target_db=999.0,
        )
    assert session.project.thresholds.sinr_target_db == 30.0


def test_sinr_target_changes_classification(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    result_default = session.run_heatmap("band_2_4")
    assert result_default.stats["sinr_ratio"] > 0.5  # objetivo 25 dB

    session.apply_rf_settings(
        noise_floor_dbm=-95.0,
        snr_target_db=25.0,
        rssi_target_dbm=-67.0,
        wifi_standard="802.11ax",
        channel_width_mhz=20,
        sinr_target_db=60.0,  # objetivo exigentísimo ⇒ mucho menos cumplimiento
    )
    result_strict = session.run_heatmap("band_2_4")
    assert result_strict.stats["sinr_target_db"] == 60.0
    assert result_strict.stats["sinr_ratio"] < result_default.stats["sinr_ratio"]
    total = result_strict.stats["point_count"]
    meets = sum(1 for e in result_strict.evaluations if e.sinr_db >= 60.0)
    assert result_strict.stats["points_meeting_sinr_target"] == meets
    assert result_strict.stats["sinr_ratio"] == round(meets / total, 4)
    assert all(
        e.sinr_meets_target == (e.sinr_db >= 60.0)
        for e in result_strict.evaluations
    )


# ===========================================================================
# G. Persistencia (schema v1 intacto; sin resultados derivados)
# ===========================================================================

def test_sinr_target_persisted_and_roundtripped(session, tmp_path):
    session.apply_rf_settings(
        noise_floor_dbm=-95.0,
        snr_target_db=25.0,
        rssi_target_dbm=-67.0,
        wifi_standard="802.11ax",
        channel_width_mhz=20,
        sinr_target_db=30.0,
    )
    path = session.save_project(str(tmp_path / "sinr.json"))
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["schema_version"] == 1
    assert set(raw) == {"schema_version", "project", "editor"}
    assert raw["project"]["thresholds"]["sinr_target_db"] == 30.0
    loaded, _state = load_project(path)
    assert loaded.thresholds.sinr_target_db == 30.0


def test_persistence_has_no_derived_sinr_results(session, tmp_path):
    _two_cochannel_aps(session)
    session.run_simulation()
    session.run_heatmap("band_5")
    path = session.save_project(str(tmp_path / "sinr_results.json"))
    raw_text = open(path, encoding="utf-8").read()
    raw = json.loads(raw_text)
    assert raw["schema_version"] == 1
    # Nunca resultados derivados (solo configuración de umbral).
    assert "sinr_db" not in raw_text
    assert "sinr_meets_target" not in raw_text
    assert "sinr_ratio" not in raw_text
    # …pero el umbral de configuración sí está.
    assert raw["project"]["thresholds"]["sinr_target_db"] == 25.0


def test_legacy_file_without_sinr_target_loads_default(session, tmp_path):
    path = session.save_project(str(tmp_path / "legacy.json"))
    raw = json.loads(open(path, encoding="utf-8").read())
    raw["project"]["thresholds"].pop("sinr_target_db", None)
    legacy = tmp_path / "legacy_sin_sinr.json"
    legacy.write_text(json.dumps(raw), encoding="utf-8")
    loaded, _state = load_project(str(legacy))
    assert loaded.thresholds.sinr_target_db == 25.0


def test_persistence_rejects_sinr_target_out_of_range(session, tmp_path):
    path = session.save_project(str(tmp_path / "range.json"))
    raw = json.loads(open(path, encoding="utf-8").read())
    raw["project"]["thresholds"]["sinr_target_db"] = 99.0
    bad = tmp_path / "range_bad.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        load_project(str(bad))


def test_persistence_rejects_sinr_target_bad_type(session, tmp_path):
    path = session.save_project(str(tmp_path / "type.json"))
    raw = json.loads(open(path, encoding="utf-8").read())
    raw["project"]["thresholds"]["sinr_target_db"] = "alto"
    bad = tmp_path / "type_bad.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        load_project(str(bad))


# ===========================================================================
# H. Config YAML
# ===========================================================================

def test_default_config_yaml_has_sinr_target():
    from config import load_config

    cfg = load_config()
    assert cfg["thresholds"].sinr_target_db == 25.0


def test_partial_yaml_defaults_sinr_target(tmp_path):
    from config import load_config

    custom = tmp_path / "partial.yaml"
    custom.write_text(
        """
radio: {}
thresholds:
  rssi_target_dbm: -70.0
bands: []
materials: []
""",
        encoding="utf-8",
    )
    cfg = load_config(custom)
    assert cfg["thresholds"].rssi_target_dbm == -70.0
    assert cfg["thresholds"].sinr_target_db == 25.0
