"""Pruebas de interacción espectral e interferencia (Fase 11).

Cubre: utilidades dBm↔mW, ocupación y solapamiento espectral (BY),
contribución efectiva (BZ), agregación en dominio lineal (CA), emisiones
y anotación por punto (reutiliza los P_rx de F1–F10), integración en la
sesión (CB), UI (métrica/leyenda/panel/estadísticas — CC), persistencia
sin cambios (CD) y las fronteras: sin SINR y sin tocar el RSSI/SOM/SNR
históricos.

No modifica ni replica los tests de F1–F10 (esos contratos se mantienen
intactos aquí y en la suite completa).
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from core.access_point import AccessPoint
from core.band import DEFAULT_BANDS
from core.geometry import Point2D
from core.project import Project
from core.radio import RadioConfiguration
from core.result import LinkEvaluation
from engine.interference import (
    InterferenceSummary,
    SpectralEmission,
    SpectralOverlap,
    aggregate_dbm,
    annotate_interference,
    dbm_to_mw,
    effective_interference_dbm,
    emission_for_ap,
    interference_summary,
    mw_to_dbm,
    occupied_interval_mhz,
    spectral_overlap,
)
from engine.simulator import simulate_coverage
from ui.session import EditorSession, HeatmapMetric
from tests.factories import make_session

BAND_24 = next(b for b in DEFAULT_BANDS if b.id == "band_2_4")
BAND_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")


@pytest.fixture
def session() -> EditorSession:
    return make_session()


def _fingerprint(result) -> list:
    """Proyección de campos RF (patrón F10): SIN campos de interferencia."""
    return [
        (
            e.point.x,
            e.point.y,
            e.access_point_id,
            e.band_id,
            e.path_loss_db,
            e.obstacle_loss_db,
            e.rx_power_dbm,
            e.som_db,
            e.snr_db,
            e.quality,
            e.verdict,
        )
        for e in result.evaluations
    ]


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
        project=Project(name="f11"),
        access_point=ap,
        frequency_band=band,
        sample_points=list(points),
    )


# ===========================================================================
# A. Dominio lineal de potencia (decisión CA)
# ===========================================================================

def test_dbm_to_mw_reference_points():
    assert round(dbm_to_mw(0.0), 9) == 1.0
    assert round(dbm_to_mw(30.0), 6) == 1000.0
    assert round(dbm_to_mw(-30.0), 12) == 0.001


def test_mw_to_dbm_roundtrip():
    for value in (-90.0, -60.0, -30.0, 0.0, 20.0):
        assert round(mw_to_dbm(dbm_to_mw(value)), 6) == value


def test_dbm_to_mw_rejects_non_finite():
    for bad in (float("nan"), float("inf"), -float("inf"), True, "x"):
        with pytest.raises(ValueError):
            dbm_to_mw(bad)


def test_mw_to_dbm_rejects_non_positive():
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            mw_to_dbm(bad)


def test_aggregate_dbm_empty_returns_none():
    assert aggregate_dbm([]) is None


def test_aggregate_dbm_sums_in_linear_domain():
    # -3 dBm + -3 dBm = 2 × 0.5 mW = 1 mW ≈ 0.01 dBm (no -6 dBm).
    assert aggregate_dbm([-3.0, -3.0]) == 0.01
    assert aggregate_dbm([-60.0, -60.0]) == -56.99


def test_aggregate_dbm_order_independent():
    powers = [-70.0, -65.0, -80.0]
    assert aggregate_dbm(powers) == aggregate_dbm(list(reversed(powers)))


def test_aggregate_dbm_single_equals_input_rounded():
    assert aggregate_dbm([-46.88]) == -46.88


def test_aggregate_dbm_rejects_non_finite():
    with pytest.raises(ValueError):
        aggregate_dbm([float("inf")])


# ===========================================================================
# B. Ocupación y solapamiento espectral (decisión BY)
# ===========================================================================

def test_occupied_interval_is_symmetric_around_center():
    lo, hi = occupied_interval_mhz(5180.0, 20.0)
    assert (lo, hi) == (5170.0, 5190.0)
    lo80, hi80 = occupied_interval_mhz(5180.0, 80.0)
    assert (lo80, hi80) == (5140.0, 5220.0)


def test_occupied_interval_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        occupied_interval_mhz(0.0, 20.0)
    with pytest.raises(ValueError):
        occupied_interval_mhz(5180.0, -20.0)
    with pytest.raises(ValueError):
        occupied_interval_mhz(float("nan"), 20.0)


def test_spectral_overlap_identical_is_full():
    overlap = spectral_overlap(5180.0, 20.0, 5180.0, 20.0)
    assert overlap.overlap_mhz == 20.0
    assert overlap.overlap_ratio == 1.0


def test_spectral_overlap_touching_edges_is_zero():
    # ch36 [5170, 5190) y ch40 [5190, 5210) solo se tocan: 0 (semiabiertos).
    overlap = spectral_overlap(5180.0, 20.0, 5200.0, 20.0)
    assert overlap.overlap_mhz == 0.0
    assert overlap.overlap_ratio == 0.0


def test_spectral_overlap_disjoint_is_zero():
    # ch36 (5180) vs ch149 (5745): bandas de 5 GHz bien separadas.
    overlap = spectral_overlap(5180.0, 20.0, 5745.0, 20.0)
    assert overlap.overlap_mhz == 0.0
    assert overlap.overlap_ratio == 0.0


def test_spectral_overlap_partial_half():
    # [5160, 5200) ∩ [5190, 5210) = 10 MHz; ancho menor = 20 → 0.5.
    overlap = spectral_overlap(5180.0, 40.0, 5200.0, 20.0)
    assert overlap.overlap_mhz == 10.0
    assert overlap.overlap_ratio == 0.5


def test_spectral_overlap_narrow_inside_wide_is_full_ratio():
    overlap = spectral_overlap(5180.0, 40.0, 5180.0, 20.0)
    assert overlap.overlap_mhz == 20.0
    assert overlap.overlap_ratio == 1.0  # fracción del ancho MENOR


def test_spectral_overlap_is_symmetric():
    a = spectral_overlap(5180.0, 40.0, 5200.0, 20.0)
    b = spectral_overlap(5200.0, 20.0, 5180.0, 40.0)
    assert (a.overlap_mhz, a.overlap_ratio) == (b.overlap_mhz, b.overlap_ratio)


def test_spectral_overlap_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        spectral_overlap(0.0, 20.0, 5180.0, 20.0)
    with pytest.raises(ValueError):
        spectral_overlap(5180.0, 20.0, 5200.0, -20.0)


def test_spectral_overlap_validates_ratio_bounds():
    with pytest.raises(ValueError):
        SpectralOverlap(overlap_mhz=10.0, overlap_ratio=1.5)
    with pytest.raises(ValueError):
        SpectralOverlap(overlap_mhz=-1.0, overlap_ratio=0.5)


def test_spectral_overlap_rounds_deterministically():
    overlap = spectral_overlap(5180.0, 40.0, 5200.0, 20.0)
    assert overlap.overlap_mhz == round(overlap.overlap_mhz, 6)
    assert overlap.overlap_ratio == round(overlap.overlap_ratio, 6)


# ===========================================================================
# C. Contribución efectiva (decisión BZ)
# ===========================================================================

def test_effective_full_overlap_equals_rx():
    assert effective_interference_dbm(-60.0, 20.0, 20.0) == -60.0


def test_effective_half_overlap_costs_3db():
    assert effective_interference_dbm(-60.0, 10.0, 20.0) == -63.01


def test_effective_zero_overlap_returns_none():
    assert effective_interference_dbm(-60.0, 0.0, 20.0) is None


def test_effective_never_exceeds_rx():
    rx = -55.0
    for overlap in (0.5, 5.0, 10.0, 20.0):
        value = effective_interference_dbm(rx, overlap, 20.0)
        assert value is None or value <= rx


def test_effective_is_monotonic_in_overlap():
    values = [
        effective_interference_dbm(-60.0, overlap, 20.0)
        for overlap in (2.0, 5.0, 10.0, 20.0)
    ]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_effective_rejects_overlap_above_width():
    with pytest.raises(ValueError):
        effective_interference_dbm(-60.0, 25.0, 20.0)


def test_effective_rejects_non_finite():
    with pytest.raises(ValueError):
        effective_interference_dbm(float("nan"), 10.0, 20.0)
    with pytest.raises(ValueError):
        effective_interference_dbm(-60.0, 10.0, 0.0)


# ===========================================================================
# D. Emisiones espectrales
# ===========================================================================

def test_emission_for_ap_uses_catalog_center():
    ap = _ap("AP-001", channel=36)
    emission = emission_for_ap(ap, BAND_5)
    assert emission is not None
    assert emission.center_frequency_mhz == 5180.0
    assert emission.width_mhz == 20.0


def test_emission_for_ap_none_without_channel():
    ap = AccessPoint(id="AP-001", position=Point2D(0, 0))
    assert emission_for_ap(ap, BAND_5) is None


def test_emission_for_ap_rejects_channel_from_other_band():
    ap = AccessPoint(
        id="AP-001", position=Point2D(0, 0), band_id="band_2_4", channel=1
    )
    with pytest.raises(ValueError):
        emission_for_ap(ap, BAND_5)


def test_spectral_emission_interval_and_validation():
    emission = SpectralEmission(
        ap_id="AP-001", center_frequency_mhz=5180.0, width_mhz=20.0
    )
    assert emission.interval_mhz == (5170.0, 5190.0)
    with pytest.raises(ValueError):
        SpectralEmission(ap_id="", center_frequency_mhz=5180.0, width_mhz=20.0)
    with pytest.raises(ValueError):
        SpectralEmission(ap_id="AP-001", center_frequency_mhz=-1.0, width_mhz=20.0)


# ===========================================================================
# E. Anotación por punto (motor puro; reutiliza P_rx de F1–F10)
# ===========================================================================

def test_annotate_co_channel_pair_has_single_interferer():
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    out = annotate_interference([r_a, r_b], emissions)
    ev_a, ev_b = out[0].evaluations[0], out[1].evaluations[0]
    assert ev_a.interference_evaluated is True
    assert ev_a.interferer_count == 1
    assert ev_a.interference_dbm is not None
    assert ev_a.dominant_interferer_ap_id == "AP-002"
    assert ev_b.dominant_interferer_ap_id == "AP-001"
    # El RSSI histórico NO cambia.
    assert ev_a.rx_power_dbm == r_a.evaluations[0].rx_power_dbm
    assert ev_b.rx_power_dbm == r_b.evaluations[0].rx_power_dbm


def test_annotate_touching_channels_has_no_contributors():
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 40, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    out = annotate_interference([r_a, r_b], emissions)
    ev = out[0].evaluations[0]
    assert ev.interference_evaluated is True  # modelo corrió…
    assert ev.interference_dbm is None        # …sin solapamiento ⇒ 0
    assert ev.interferer_count == 0
    assert ev.dominant_interferer_ap_id is None


def test_annotate_partial_overlap_matches_formula():
    ap_a = _ap("AP-001", 36, width_mhz=40)
    ap_b = _ap("AP-002", 40, width_mhz=20, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    out = annotate_interference([r_a, r_b], emissions)
    ev = out[0].evaluations[0]
    expected = round(
        r_b.evaluations[0].rx_power_dbm + 10.0 * math.log10(10.0 / 20.0), 2
    )
    assert ev.interferer_count == 1
    assert ev.interference_dbm == expected
    assert ev.interference_dbm <= r_b.evaluations[0].rx_power_dbm


def test_annotate_without_desired_emission_leaves_result_untouched():
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    out = annotate_interference([r_a, r_b], {})  # sin emisiones (AP sin canal)
    assert out[0] is r_a
    assert out[1] is r_b
    assert r_a.evaluations[0].interference_evaluated is False


def test_annotate_does_not_mutate_originals():
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    annotate_interference([r_a, r_b], emissions)
    assert r_a.evaluations[0].interference_evaluated is False
    assert r_a.evaluations[0].interference_dbm is None


def test_annotate_preserves_order_and_count():
    aps = [
        _ap("AP-001", 36),
        _ap("AP-002", 36, position=Point2D(10.0, 0.0)),
        _ap("AP-003", 36, position=Point2D(20.0, 0.0)),
    ]
    results = [_simulate(ap) for ap in aps]
    emissions = {ap.id: emission_for_ap(ap, BAND_5) for ap in aps}
    out = annotate_interference(results, emissions)
    assert [r.evaluations[0].access_point_id for r in out] == [
        "AP-001", "AP-002", "AP-003",
    ]
    assert all(r.evaluations[0].interferer_count == 2 for r in out)


def test_annotate_is_input_order_independent():
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    r_a, r_b = _simulate(ap_a), _simulate(ap_b)
    emissions = {
        "AP-001": emission_for_ap(ap_a, BAND_5),
        "AP-002": emission_for_ap(ap_b, BAND_5),
    }
    out1 = annotate_interference([r_a, r_b], emissions)
    out2 = annotate_interference([r_b, r_a], emissions)
    by_id = {
        r.evaluations[0].access_point_id: r.evaluations[0] for r in out1 + out2
    }
    for r in out1 + out2:
        ev = r.evaluations[0]
        twin = by_id[ev.access_point_id]
        assert ev.interference_dbm == twin.interference_dbm
        assert ev.dominant_interferer_ap_id == twin.dominant_interferer_ap_id


def test_annotate_never_mixes_bands():
    ap5 = _ap("AP-001", 36)
    ap24 = AccessPoint(
        id="AP-002", position=Point2D(10.0, 0.0), band_id="band_2_4", channel=1
    )
    r5 = _simulate(ap5, BAND_5)
    r24 = _simulate(ap24, BAND_24)
    emissions = {
        "AP-001": emission_for_ap(ap5, BAND_5),
        "AP-002": emission_for_ap(ap24, BAND_24),
    }
    out = annotate_interference([r5, r24], emissions)
    for r in out:
        ev = r.evaluations[0]
        assert ev.interference_evaluated is True
        assert ev.interferer_count == 0  # jamás cruza bandas (CB)
        assert ev.interference_dbm is None


def test_annotate_dominant_tie_breaks_by_lower_id():
    # Interferentes simétricos (misma distancia ⇒ misma potencia).
    desired = _ap("AP-000", 36, position=Point2D(5.0, 10.0))
    left = _ap("AP-001", 36, position=Point2D(0.0, 0.0))
    right = _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    points = [Point2D(5.0, 0.0)]
    results = [_simulate(ap, points=points) for ap in (desired, left, right)]
    emissions = {
        ap.id: emission_for_ap(ap, BAND_5) for ap in (desired, left, right)
    }
    out = annotate_interference(results, emissions)
    ev = out[0].evaluations[0]
    assert ev.interferer_count == 2
    assert ev.dominant_interferer_ap_id == "AP-001"  # empate ⇒ menor id (CA)


def test_annotate_empty_results_returns_empty():
    assert annotate_interference([], {}) == []


# ===========================================================================
# F. Resumen para el panel (consumo de campos)
# ===========================================================================

def test_interference_summary_none_without_evaluations():
    assert interference_summary([]) is None


def test_interference_summary_unannotated_reports_zero_evaluated():
    ap = _ap("AP-001", 36)
    summary = interference_summary(list(_simulate(ap).evaluations))
    assert summary is not None
    assert summary.point_count == 1
    assert summary.evaluated_points == 0
    assert summary.interference_max_dbm is None


def test_interference_summary_reports_max_and_dominant():
    ap_a, ap_b = _ap("AP-001", 36), _ap("AP-002", 36, position=Point2D(10.0, 0.0))
    results = annotate_interference(
        [_simulate(ap_a), _simulate(ap_b)],
        {
            "AP-001": emission_for_ap(ap_a, BAND_5),
            "AP-002": emission_for_ap(ap_b, BAND_5),
        },
    )
    summary = interference_summary(list(results[0].evaluations))
    assert summary is not None
    assert summary.evaluated_points == 1
    assert summary.interference_max_dbm is not None
    assert summary.interferer_count_max == 1
    assert summary.dominant_interferer_ap_id == "AP-002"


def test_interference_summary_dataclass_is_frozen():
    assert dataclasses.is_dataclass(InterferenceSummary)


# ===========================================================================
# G. Integración en la sesión (run_simulation / run_heatmap)
# ===========================================================================

def test_run_simulation_annotates_channelled_pair(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    result = session.run_simulation()
    ev = result.evaluations[0]
    assert ev.interference_evaluated is True
    assert ev.interferer_count == 1
    assert ev.interference_dbm is not None
    assert ev.dominant_interferer_ap_id in (ap1.id, ap2.id)


def test_run_simulation_single_channelled_ap_not_annotated(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    ev = session.run_simulation().evaluations[0]
    assert ev.interference_evaluated is False  # sin contexto posible
    assert ev.interference_dbm is None


def test_run_simulation_ap_without_channel_skips_model(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.add_access_point(Point2D(8.0, 6.0))
    ev = session.run_simulation().evaluations[0]
    assert ev.interference_evaluated is False
    assert ev.rx_power_dbm is not None  # el RSSI histórico sigue intacto


def test_run_simulation_different_bands_never_interact(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_2_4", channel=1, width_mhz=20)
    ev = session.run_simulation().evaluations[0]  # AP-002 (selección)
    assert ev.interference_evaluated is False


def test_ab_annotation_does_not_change_rf_fields(session, tmp_path):
    """A/B F11: la anotación NO altera RSSI/SOM/SNR/veredicto/calidad."""
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_ap_rf_config("AP-001", band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    session.run_heatmap("band_5")
    baseline = _fingerprint(session.last_heatmap)
    assert session.last_heatmap.evaluations[0].interference_evaluated is False

    second = session.add_access_point(Point2D(10.0, 6.0))
    session.set_ap_rf_config(second.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_heatmap_ap("AP-001")
    session.run_heatmap("band_5")
    assert _fingerprint(session.last_heatmap) == baseline
    ev = session.last_heatmap.evaluations[0]
    assert ev.interference_evaluated is True
    assert ev.interferer_count == 1


def test_heatmap_all_aps_annotates_before_combine(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(10.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_5")
    assert result.stats.get("combined") is True
    ev = result.evaluations[0]
    assert ev.interference_evaluated is True  # viaja con el ganador (BX)
    assert ev.interference_dbm is not None


def test_heatmap_all_aps_without_channels_not_annotated(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.add_access_point(Point2D(10.0, 6.0))
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_5")
    assert all(not e.interference_evaluated for e in result.evaluations)


def test_heatmap_interference_metric_single_ap_with_context(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(10.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    session.set_heatmap_ap(ap1.id)
    session.set_heatmap_metric("interference")
    result = session.run_heatmap("band_5")
    assert result.evaluations[0].access_point_id == ap1.id  # vista = AP-001
    ev = result.evaluations[0]
    assert ev.interference_evaluated is True
    assert ev.interferer_count == 1
    assert ev.dominant_interferer_ap_id == ap2.id


def test_heatmap_interference_metric_without_others_has_no_data(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    session.set_heatmap_metric("interference")
    result = session.run_heatmap("band_5")
    assert all(not e.interference_evaluated for e in result.evaluations)
    assert "sin datos en esta corrida" in session.heatmap_stats_text()


def test_heatmap_stats_text_interference_header(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(10.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    session.set_heatmap_ap(ap1.id)
    session.set_heatmap_metric("interference")
    session.run_heatmap("band_5")
    text = session.heatmap_stats_text()
    assert "Métrica: Interferencia (dBm)" in text
    assert "Interferencia agregada máx:" in text
    assert "APs interferentes (máx): 1" in text


# ===========================================================================
# H. Métricas del heatmap (registro F11 vs enum congelado F7)
# ===========================================================================

def test_heatmap_metric_enum_remains_frozen_f7():
    assert {m.value for m in HeatmapMetric} == {"rssi", "snr"}


def test_heatmap_metrics_registry_includes_interference():
    from ui.coverage_renderer import (
        HEATMAP_METRICS,
        HEATMAP_METRIC_INTERFERENCE,
        HEATMAP_METRIC_SINR,
    )

    assert HEATMAP_METRIC_INTERFERENCE == "interference"
    assert HEATMAP_METRIC_SINR == "sinr"
    # Supersede F12 (decisión CD): F11 congelaba exactamente 3 métricas;
    # F12 añade la capa paralela "sinr" al registro.
    assert HEATMAP_METRICS == ("rssi", "snr", "interference", "sinr")


def test_set_heatmap_metric_accepts_interference(session):
    session.set_heatmap_metric("interference")
    assert session.heatmap_metric == "interference"


def test_set_heatmap_metric_interference_does_not_invalidate_rf(session, tmp_path):
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    session.save_project(str(tmp_path / "clean.json"))  # limpia el dirty
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    assert session.dirty is False

    session.set_heatmap_metric("interference")
    assert session.heatmap_metric == "interference"
    # Vista pura: el RF ya calculado sigue válido (sin recálculo).
    assert session.heatmap_dirty is False
    assert session.dirty is False  # es vista, no configuración (BA)

    session.set_heatmap_metric("interference")  # idempotente
    assert session.heatmap_metric == "interference"


def test_set_heatmap_metric_still_rejects_unknown():
    session = EditorSession()
    with pytest.raises(ValueError):
        session.set_heatmap_metric("potencia")


# ===========================================================================
# I. Panel de propiedades (solo datos reales — CC)
# ===========================================================================

def test_panel_lines_without_channel(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    lines = session.ap_interference_lines(ap.id)
    assert lines == ["Interferencia: — (AP sin canal)"]


def test_panel_lines_without_shared_spectrum(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    lines = session.ap_interference_lines(ap.id)
    assert lines == ["Interferencia: 0 APs (sin espectro compartido)"]


def test_panel_lines_without_runs_reports_no_data(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    lines = session.ap_interference_lines(ap1.id)
    assert lines == ["Interferencia: — (sin datos de corrida)"]


def test_panel_lines_with_simulation_data(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.run_simulation()  # simula AP-002 (selección actual)
    lines = session.ap_interference_lines(ap2.id)
    assert lines[0] == "Interferencia:"
    assert any(line.startswith("APs interferentes (máx): 1") for line in lines)
    assert any(line.startswith("Potencia agregada máx:") for line in lines)
    assert any(line.startswith("Dominante: ") for line in lines)


def test_panel_lines_unknown_ap_returns_empty(session):
    assert session.ap_interference_lines("AP-999") == []


# ===========================================================================
# J. UI: renderer y toolbar
# ===========================================================================

def test_legend_title_interference():
    from ui.coverage_renderer import legend_title

    assert legend_title("interference") == "Interferencia (dBm)"
    assert legend_title("rssi") == "Cobertura Wi-Fi"
    assert legend_title("snr") == "SNR (dB)"


def test_legend_rows_interference_has_bands_and_still_rejects_unknown():
    from core.project import CoverageThresholds
    from ui.coverage_renderer import legend_rows

    rows = legend_rows(CoverageThresholds(), metric="interference")
    assert len(rows) == 5
    assert {"label", "color", "range"} <= set(rows[0])
    with pytest.raises(ValueError):
        legend_rows(CoverageThresholds(), metric="potencia")


def test_interference_color_scale_direction_and_none():
    from ui.coverage_renderer import interference_to_color, interference_to_rgb

    # None (sin contribuidores) ⇒ color de «sin interferencia» (mínimo).
    assert interference_to_color(None) == interference_to_color(-95.0)
    # Escala invertida: -30 dBm (fuerte) ⇒ morado apagado del máximo.
    assert interference_to_rgb(-30.0) == (140, 50, 90)
    assert interference_to_rgb(-95.0) == (80, 200, 120)
    # Fuerte ⇒ distinto de débil (dirección correcta).
    assert interference_to_rgb(-35.0) != interference_to_rgb(-90.0)


def test_build_heatmap_image_supports_interference_metric(session):
    from ui.coverage_renderer import build_heatmap_image
    from ui.viewport import Viewport

    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(10.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_grid_resolution(2.0)
    session.set_heatmap_ap(ap1.id)
    session.set_heatmap_metric("interference")
    result = session.run_heatmap("band_5")
    vp = Viewport(world_width_m=20.0, world_height_m=15.0)
    image = build_heatmap_image(result, vp, cell_size_m=2.0, metric="interference")
    assert image is not None
    with pytest.raises(ValueError):
        build_heatmap_image(result, vp, metric="potencia")


def test_toolbar_metric_label_registry():
    from ui.panels.toolbar import METRIC_ID_BY_LABEL, METRIC_LABEL_BY_ID

    assert METRIC_LABEL_BY_ID["interference"] == "Interferencia"
    assert METRIC_ID_BY_LABEL["Interferencia"] == "interference"


# ===========================================================================
# K. Fronteras: SINR F12 (supersede CD) y persistencia sin cambios (CD)
# ===========================================================================

def test_sinr_fields_present_and_equal_snr_without_interference():
    """Supersede F12 (decisión CD): F11 congelaba «sin SINR».

    Contrato F12: los campos nuevos existen en LinkEvaluation, con
    interferencia no modelada el SINR es EXACTAMENTE el SNR (decisión
    CG) y el nombre corto «sinr» (sin sufijo) sigue sin ser campo.
    """
    names = {f.name for f in dataclasses.fields(LinkEvaluation)}
    assert "sinr" not in names
    assert "sinr_db" in names
    assert "sinr_meets_target" in names
    ev = _simulate(_ap("AP-001", 36)).evaluations[0]
    assert ev.sinr_db is not None
    assert ev.sinr_db == ev.snr_db  # SINR = SNR sin interferencia (CG)
    assert not hasattr(ev, "sinr")


def test_persistence_schema_unchanged_with_interference(session, tmp_path):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    session.run_simulation()
    path = session.save_project(str(tmp_path / "f11.json"))
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["schema_version"] == 1
    assert set(raw) == {"schema_version", "project", "editor"}
    assert "interference" not in json.dumps(raw).lower()
