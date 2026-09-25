"""Pruebas de optimización de canales (Fase 13).

Cubre: API (evaluate/optimize/resultado estructurado), casos 0/1/2/N
APs, empates y desempate (decisión CL), candidatos y canales inválidos
(decisión CN), semántica SINR = SNR sin interferencia (CG intacta),
None sin conversiones silenciosas, determinismo y no mutación, propiedades
físicas (separar canales no empeora; ya óptima no cambia; RSSI/SNR no
destructivos) y la integración de sesión (propuesta + aplicación).

No modifica tests de F1–F12: la frontera F13 es la de optimización; el
ganador por MAX RSSI, el enum de métricas, el schema y la fórmula SINR
siguen intactos (se reafirman aquí como regresión).
"""

from __future__ import annotations

import pytest

from core.access_point import AccessPoint
from core.band import DEFAULT_BANDS
from core.geometry import Point2D
from core.project import CoverageThresholds, Project
from core.radio import RadioConfiguration
from engine.channel_optimization import (
    EXHAUSTIVE_LIMIT,
    SEARCH_COORDINATE_DESCENT,
    SEARCH_EXHAUSTIVE,
    AssignmentEvaluation,
    OptimizationResult,
    OptimizationTarget,
    candidate_channels,
    evaluate_channel_assignment,
    optimize_channels,
)
from engine.coverage_grid import CoverageGrid
from engine.simulator import simulate_coverage
from ui.session import EditorSession

BAND_24 = next(b for b in DEFAULT_BANDS if b.id == "band_2_4")
BAND_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")
THRESHOLDS = CoverageThresholds()
POINTS = CoverageGrid(width_m=12.0, height_m=8.0, resolution_m=2.0).points()


def _ap(
    ap_id: str,
    channel: int | None,
    x: float,
    band_id: str = "band_2_4",
    width_mhz: int = 20,
    y: float = 4.0,
) -> AccessPoint:
    return AccessPoint(
        id=ap_id,
        position=Point2D(x, y),
        radio=RadioConfiguration(channel_width_mhz=width_mhz),
        band_id=band_id,
        channel=channel,
    )


def _base(aps, band=BAND_24, points=POINTS) -> dict:
    project = Project(name="f13")
    return {
        ap.id: simulate_coverage(project, ap, band, list(points)) for ap in aps
    }


def _targets(aps, band=BAND_24) -> list:
    return [
        OptimizationTarget(
            ap_id=ap.id,
            band=band,
            width_mhz=ap.radio.channel_width_mhz,
            current_channel=ap.channel,
        )
        for ap in aps
    ]


def _fingerprint(result) -> list:
    """Huella de los campos RF históricos (patrón F10/F11)."""
    return [
        (
            e.point.x,
            e.point.y,
            e.access_point_id,
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


# ===========================================================================
# A. API
# ===========================================================================

def test_evaluate_returns_structured_result():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    ev = evaluate_channel_assignment(
        _targets(aps),
        {"AP-001": 1, "AP-002": 6},
        base,
        THRESHOLDS,
    )
    assert isinstance(ev, AssignmentEvaluation)
    assert ev.assignment == (("AP-001", 1), ("AP-002", 6))
    assert isinstance(ev.score, float)
    assert isinstance(ev.sinr_min_db, float)
    assert "sinr_avg_db" in ev.stats and "sinr_min_db" in ev.stats
    assert "snr_avg_db" in ev.stats and "coverage_ratio" in ev.stats


def test_optimize_returns_structured_result():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert isinstance(result, OptimizationResult)
    assert set(result.original_assignment) == {"AP-001", "AP-002"}
    assert set(result.optimized_assignment) == {"AP-001", "AP-002"}
    assert isinstance(result.original_score, float)
    assert isinstance(result.optimized_score, float)
    assert isinstance(result.improvement, float)
    assert result.search in (SEARCH_EXHAUSTIVE, SEARCH_COORDINATE_DESCENT)
    assert result.evaluation_count >= 1
    assert isinstance(result.changed, bool)
    assert isinstance(result.original_stats, dict)
    assert isinstance(result.optimized_stats, dict)


def test_candidate_channels_is_full_catalog():
    assert candidate_channels(BAND_24, 20) == tuple(range(1, 15))
    channels_5 = candidate_channels(BAND_5, 20)
    assert channels_5[0] == 36 and channels_5[-1] == 165
    assert len(channels_5) == 25
    # Orden determinista creciente (sin dependencia de hash).
    assert list(channels_5) == sorted(channels_5)


def test_candidate_channels_rejects_bad_width():
    with pytest.raises(ValueError):
        candidate_channels(BAND_24, 80)  # 2.4 GHz: solo 20/40
    with pytest.raises(ValueError):
        candidate_channels(BAND_24, True)


# ===========================================================================
# B. Un solo AP
# ===========================================================================

def test_single_ap_no_change():
    aps = [_ap("AP-001", 6, 5.0)]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert result.changed is False
    assert result.optimized_assignment == {"AP-001": 6}
    assert result.improvement == 0.0
    # Sin otro emisor no hay I modelada: SINR == SNR (decisión CG).
    assert (
        result.original_stats["sinr_avg_db"]
        == result.original_stats["snr_avg_db"]
    )
    assert (
        result.original_stats["sinr_min_db"]
        == result.original_stats["snr_min_db"]
    )


def test_single_ap_space_is_exhaustive():
    aps = [_ap("AP-001", 6, 5.0)]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    # 14 candidatos ≤ EXHAUSTIVE_LIMIT: semilla + 13 = 14 evaluaciones.
    assert result.search == SEARCH_EXHAUSTIVE
    assert result.evaluation_count == 14


# ===========================================================================
# C. Dos APs
# ===========================================================================

def test_two_ap_conflict_proposes_improvement():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert result.changed is True
    assert result.optimized_assignment != result.original_assignment
    assert result.improvement is not None
    assert result.improvement > 0.0
    assert result.optimized_score > result.original_score
    # El ganador por RSSI no cambia: mismo nº de puntos del grid.
    assert result.optimized_stats["point_count"] == result.original_stats["point_count"]


def test_evaluate_conflict_vs_separated():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    conflict = evaluate_channel_assignment(
        _targets(aps), {"AP-001": 6, "AP-002": 6}, base, THRESHOLDS
    )
    separated = evaluate_channel_assignment(
        _targets(aps), {"AP-001": 1, "AP-002": 11}, base, THRESHOLDS
    )
    assert conflict.score < separated.score  # 1/6/11 son disjuntos (20 MHz)
    # Separados: sin I modelada ⇒ SINR == SNR exacto (CG).
    assert separated.stats["sinr_avg_db"] == separated.stats["snr_avg_db"]
    assert conflict.stats["sinr_avg_db"] < conflict.stats["snr_avg_db"]


def test_two_ap_already_separated_no_change():
    aps = [_ap("AP-001", 1, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    # Sin interferencia ya no hay score mejor posible: sin cambios.
    assert result.changed is False
    assert result.improvement == 0.0


# ===========================================================================
# D. Múltiples APs
# ===========================================================================

def test_three_ap_improvement_and_structure():
    aps = [
        _ap("AP-001", 6, 2.0),
        _ap("AP-002", 6, 8.0),
        _ap("AP-003", 6, 10.0),
    ]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert result.changed is True
    assert result.improvement is not None
    assert result.improvement > 0.0
    assert set(result.optimized_assignment) == {"AP-001", "AP-002", "AP-003"}


def test_search_mode_follows_space_size():
    aps = [
        _ap("AP-001", 6, 2.0),
        _ap("AP-002", 6, 8.0),
        _ap("AP-003", 6, 10.0),
    ]
    base = _base(aps)
    # 3×14³ = 2744 > 64 ⇒ descenso coordenado acotado.
    large = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert large.search == SEARCH_COORDINATE_DESCENT
    assert large.evaluation_count < 2744
    # Espacio pequeño pedido ⇒ exhaustivo (2³ = 8 ≤ 64).
    requested = {ap.id: [6, 11] for ap in aps}
    small = optimize_channels(_targets(aps), base, THRESHOLDS, requested)
    assert small.search == SEARCH_EXHAUSTIVE
    # 8 combos: la semilla (6,6,6) ya está dentro ⇒ 8 evaluaciones.
    assert small.evaluation_count == 8
    assert EXHAUSTIVE_LIMIT == 64


def test_three_ap_deterministic_across_runs():
    aps = [
        _ap("AP-001", 3, 2.0),
        _ap("AP-002", 4, 6.0),
        _ap("AP-003", 5, 10.0),
    ]
    base = _base(aps)
    first = optimize_channels(_targets(aps), base, THRESHOLDS)
    second = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert first == second


# ===========================================================================
# E. Empates y desempate (decisión CL)
# ===========================================================================

def test_tie_prefers_fewer_changes():
    # Semilla en conflicto (6,6). Espacio pedido: (1|6, 1|11).
    # Cero solapamiento: (1,11) con 2 cambios y (6,1)/(6,11) con 1
    # cambio. Entre los de 1 cambio gana el lexicográfico menor:
    # AP-001 = 6 (empate) ⇒ AP-002 = 1 < 11. Verifica la CADENA
    # completa score → nº de cambios → orden (decisión CL).
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    result = optimize_channels(
        _targets(aps),
        base,
        THRESHOLDS,
        {"AP-001": [1, 6], "AP-002": [1, 11]},
    )
    assert result.optimized_assignment == {"AP-001": 6, "AP-002": 1}
    assert result.improvement > 0.0
    # La semilla (6,6) no está en el producto (AP-002 solo admite 1/11):
    # 1 semilla + 4 combos = 5 evaluaciones, exhaustivas.
    assert result.search == SEARCH_EXHAUSTIVE
    assert result.evaluation_count == 5


def test_tie_lexicographic_smallest_channel_wins():
    aps = [_ap("AP-001", 1, 2.0), _ap("AP-002", 1, 8.0)]
    base = _base(aps)
    requested = {"AP-001": [6, 11], "AP-002": [6, 11]}
    result = optimize_channels(_targets(aps), base, THRESHOLDS, requested)
    # (6, 11) y (11, 6) empatan en score (disjuntos) y en cambios (2):
    # gana el lexicográfico menor ⇒ AP-001 = 6.
    assert result.optimized_assignment == {"AP-001": 6, "AP-002": 11}


def test_repeated_optimize_is_identical():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    runs = [optimize_channels(_targets(aps), base, THRESHOLDS) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


# ===========================================================================
# F. Canales inválidos
# ===========================================================================

def test_evaluate_rejects_channel_out_of_band_and_unknown():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    targets = _targets(aps)
    for bad in (149, 999, 0, -1):
        with pytest.raises(ValueError):
            evaluate_channel_assignment(
                targets, {"AP-001": bad, "AP-002": 6}, base, THRESHOLDS
            )
    with pytest.raises(ValueError):
        evaluate_channel_assignment(
            targets, {"AP-001": True, "AP-002": 6}, base, THRESHOLDS
        )


def test_evaluate_rejects_incomplete_assignment():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    targets = _targets(aps)
    with pytest.raises(ValueError):
        evaluate_channel_assignment(targets, {"AP-001": 1}, base, THRESHOLDS)
    with pytest.raises(ValueError):
        evaluate_channel_assignment(
            targets,
            {"AP-001": 1, "AP-002": 6, "AP-003": 6},
            base,
            THRESHOLDS,
        )


def test_requested_candidates_filtered_invalid_values():
    aps = [_ap("AP-001", 11, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    requested = {"AP-001": [6, 999, "x", True, 36, 11.0]}
    result = optimize_channels(_targets(aps), base, THRESHOLDS, requested)
    # Solo 6 y 11 sobreviven al filtro F10; nada fuera aparece jamás.
    assert result.optimized_assignment["AP-001"] in (6, 11)
    assert result.optimized_assignment["AP-002"] in (6,)


def test_requested_candidates_unknown_ap_raises():
    aps = [_ap("AP-001", 6, 2.0)]
    base = _base(aps)
    with pytest.raises(ValueError):
        optimize_channels(
            _targets(aps), base, THRESHOLDS, {"NO-EXISTE": [6]}
        )


def test_duplicate_targets_raise():
    aps = [_ap("AP-001", 6, 2.0)]
    base = _base(aps)
    targets = _targets(aps) + _targets(aps)
    with pytest.raises(ValueError):
        optimize_channels(targets, base, THRESHOLDS)


def test_target_without_base_result_raises():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps[:1])
    with pytest.raises(ValueError):
        optimize_channels(_targets(aps), base, THRESHOLDS)


def test_target_with_bad_width_raises():
    # Ni siquiera hacen falta resultados base: el ancho ilegal se
    # rechaza primero (mismo guard que engine.simulator, decisión AY).
    ap = _ap("AP-001", 6, 2.0, width_mhz=80)  # ilegal en 2.4 GHz
    with pytest.raises(ValueError):
        optimize_channels(_targets([ap]), {}, THRESHOLDS)


# ===========================================================================
# G. Candidatos
# ===========================================================================

def test_requested_candidates_respected_when_small():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    requested = {"AP-001": [6, 11], "AP-002": [1, 11]}
    result = optimize_channels(_targets(aps), base, THRESHOLDS, requested)
    assert result.optimized_assignment["AP-001"] in (6, 11)
    assert result.optimized_assignment["AP-002"] in (1, 11)
    # Exhaustivo con espacio 2×2 = 4; la semilla (6,6) queda fuera
    # (AP-002 solo admite 1/11) ⇒ 1 + 4 = 5 evaluaciones.
    assert result.search == SEARCH_EXHAUSTIVE
    assert result.evaluation_count == 5


def test_requested_candidates_duplicates_and_order_irrelevant():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    a = optimize_channels(
        _targets(aps), base, THRESHOLDS, {"AP-001": [11, 6, 11, 6]}
    )
    b = optimize_channels(
        _targets(aps), base, THRESHOLDS, {"AP-001": [6, 11]}
    )
    assert a == b


def test_empty_candidate_list_keeps_current_channel():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    result = optimize_channels(
        _targets(aps), base, THRESHOLDS, {"AP-002": []}
    )
    # AP-002 sin candidatos: solo AP-001 puede moverse.
    assert result.optimized_assignment["AP-002"] == 6
    assert result.changed is True  # AP-001 escapa del canal 6
    assert result.optimized_assignment["AP-001"] != 6


# ===========================================================================
# H. Sin interferencia modelada
# ===========================================================================

def test_no_interference_invented_for_channel_less_ap():
    # Solo un AP con canal: el otro no emite (CB) ⇒ SINR == SNR en
    # toda la evaluación y la optimización no inventa interferencia.
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", None, 8.0)]
    base = _base(aps)
    targets = [
        OptimizationTarget(
            ap_id="AP-001", band=BAND_24, width_mhz=20, current_channel=6
        )
    ]
    ev = evaluate_channel_assignment(
        targets, {"AP-001": 6}, base, THRESHOLDS
    )
    assert ev.stats["sinr_avg_db"] == ev.stats["snr_avg_db"]
    result = optimize_channels(targets, base, THRESHOLDS)
    assert result.changed is False
    assert "AP-002" not in result.optimized_assignment


def test_disjoint_assignment_keeps_sinr_equals_snr():
    aps = [_ap("AP-001", 1, 2.0), _ap("AP-002", 11, 8.0)]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert result.changed is False
    assert (
        result.original_stats["sinr_avg_db"]
        == result.original_stats["snr_avg_db"]
    )


# ===========================================================================
# I. None y casos vacíos
# ===========================================================================

def test_zero_targets_no_exception():
    result = optimize_channels([], {}, THRESHOLDS)
    assert result.original_assignment == {}
    assert result.optimized_assignment == {}
    assert result.original_score is None
    assert result.optimized_score is None
    assert result.improvement is None
    assert result.changed is False
    assert result.evaluation_count == 1
    assert result.search == SEARCH_EXHAUSTIVE


def test_target_with_current_channel_none_stays_none():
    # AP-001 fuera del modelo espectral (sin canal); asignarle canal
    # solo puede empeorar (añade un emisor) o empatar ⇒ la semilla gana.
    aps = [_ap("AP-001", None, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    targets = [
        OptimizationTarget(
            ap_id="AP-001", band=BAND_24, width_mhz=20, current_channel=None
        ),
        OptimizationTarget(
            ap_id="AP-002", band=BAND_24, width_mhz=20, current_channel=6
        ),
    ]
    result = optimize_channels(targets, base, THRESHOLDS)
    assert result.original_assignment == {"AP-001": None, "AP-002": 6}
    assert result.optimized_assignment == {"AP-001": None, "AP-002": 6}
    assert result.changed is False


# ===========================================================================
# K/L. Determinismo y no mutación
# ===========================================================================

def test_target_order_permutation_gives_same_result():
    # Propiedad 3: el orden de entrada de los targets no cambia nada.
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0), _ap("AP-003", 6, 10.0)]
    base = _base(aps)
    forward = optimize_channels(_targets(aps), base, THRESHOLDS)
    backward = optimize_channels(list(reversed(_targets(aps))), base, THRESHOLDS)
    assert forward == backward


def test_evaluate_and_optimize_do_not_mutate_base_results():
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    before = {ap_id: _fingerprint(res) for ap_id, res in base.items()}
    stats_before = {ap_id: dict(res.stats) for ap_id, res in base.items()}
    tuple_before = {ap_id: res.evaluations for ap_id, res in base.items()}
    evaluate_channel_assignment(
        _targets(aps), {"AP-001": 1, "AP-002": 6}, base, THRESHOLDS
    )
    optimize_channels(_targets(aps), base, THRESHOLDS)
    after = {ap_id: _fingerprint(res) for ap_id, res in base.items()}
    stats_after = {ap_id: dict(res.stats) for ap_id, res in base.items()}
    assert before == after
    assert stats_before == stats_after
    # Ni siquiera se reemplazan los objetos: misma tupla de evaluaciones.
    assert all(
        base[ap_id].evaluations is tuple_before[ap_id] for ap_id in base
    )


# ===========================================================================
# Propiedades físicas (§15 F13)
# ===========================================================================

def test_property_separation_does_not_worsen_interference():
    # Propiedad 1: separar canales que se solapaban no empeora el score.
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    conflict = evaluate_channel_assignment(
        _targets(aps), {"AP-001": 6, "AP-002": 6}, base, THRESHOLDS
    )
    separated = evaluate_channel_assignment(
        _targets(aps), {"AP-001": 1, "AP-002": 11}, base, THRESHOLDS
    )
    assert separated.score >= conflict.score
    assert separated.sinr_min_db >= conflict.sinr_min_db


def test_property_already_optimal_never_changes():
    # Propiedad 2: 1/6/11 mutuamente disjuntos = cero I = score máximo.
    aps = [
        _ap("AP-001", 1, 2.0),
        _ap("AP-002", 6, 6.0),
        _ap("AP-003", 11, 10.0),
    ]
    base = _base(aps)
    result = optimize_channels(_targets(aps), base, THRESHOLDS)
    assert result.changed is False
    assert result.improvement == 0.0


def test_property_rx_and_snr_not_destructive():
    # Propiedad 4: cambiar de canal reevalúa I/SINR sin tocar RSSI/SNR.
    aps = [_ap("AP-001", 6, 2.0), _ap("AP-002", 6, 8.0)]
    base = _base(aps)
    conflict = evaluate_channel_assignment(
        _targets(aps), {"AP-001": 6, "AP-002": 6}, base, THRESHOLDS
    )
    separated = evaluate_channel_assignment(
        _targets(aps), {"AP-001": 1, "AP-002": 11}, base, THRESHOLDS
    )
    # RSSI/SNR históricos idénticos (el canal no altera FSPL, BR).
    assert conflict.stats["rx_avg_dbm"] == separated.stats["rx_avg_dbm"]
    assert conflict.stats["snr_avg_db"] == separated.stats["snr_avg_db"]
    assert conflict.stats["sinr_avg_db"] != separated.stats["sinr_avg_db"]


# ===========================================================================
# Integración con la sesión (propuesta + aplicación)
# ===========================================================================

@pytest.fixture
def session() -> EditorSession:
    return EditorSession()


def _session_with_conflict(session: EditorSession) -> tuple:
    session.set_grid_resolution(2.0)
    ap1 = session.add_access_point(Point2D(2.0, 4.0))
    ap2 = session.add_access_point(Point2D(9.0, 4.0))
    session.set_ap_rf_config(ap1.id, band_id="band_2_4", channel=6, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_2_4", channel=6, width_mhz=20)
    session.dirty = False  # la configuración inicial ya está aplicada
    return ap1, ap2


def test_session_optimize_is_a_non_mutating_proposal(session):
    ap1, ap2 = _session_with_conflict(session)
    result = session.optimize_channels()
    assert result.changed is True
    assert result.improvement > 0.0
    # Propuesta pura: nada del proyecto cambió (I8/L). Ojo: los objetos
    # devueltos por add_access_point quedan stale tras set_ap_rf_config
    # (replace en la lista); se relee SIEMPRE desde el proyecto.
    channels = {
        ap.id: ap.channel for ap in session.project.access_points
    }
    assert channels == {ap1.id: 6, ap2.id: 6}
    assert session.dirty is False
    assert session.last_heatmap is None
    # Las claves de la propuesta son exactamente los APs con canal.
    assert set(result.optimized_assignment) == {ap1.id, ap2.id}


def test_session_apply_channel_assignment(session):
    ap1, ap2 = _session_with_conflict(session)
    result = session.optimize_channels()
    applied = session.apply_channel_assignment(result.optimized_assignment)
    # Solo se aplican los APs cuyo canal difiere de la propuesta actual.
    expected = {
        ap_id
        for ap_id, channel in result.optimized_assignment.items()
        if channel != result.original_assignment[ap_id]
    }
    assert set(applied) == expected
    changed = {
        ap.id: ap.channel for ap in session.project.access_points
    }
    assert changed == result.optimized_assignment
    assert session.dirty is True
    # Ya aplicada: reoptimizar no propone cambios (semilla = actual).
    again = session.optimize_channels()
    assert again.changed is False
    assert again.improvement == 0.0
    # Aplicar un id inexistente falla con KeyError (sin tocar nada).
    with pytest.raises(KeyError):
        session.apply_channel_assignment({"NO-EXISTE": 11})


def test_session_optimize_is_scoped_to_active_band(session):
    session.set_grid_resolution(2.0)
    ap24 = session.add_access_point(Point2D(2.0, 4.0))
    ap5 = session.add_access_point(Point2D(9.0, 4.0))
    session.set_ap_rf_config(ap24.id, band_id="band_2_4", channel=6, width_mhz=20)
    session.set_ap_rf_config(ap5.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_band("band_2_4")
    session.dirty = False
    result = session.optimize_channels()  # banda activa: 2.4 GHz
    # El AP de 5 GHz queda fuera de la corrida (una banda por corrida).
    assert set(result.optimized_assignment) == {ap24.id}
    project_aps = {ap.id: ap for ap in session.project.access_points}
    assert project_aps[ap5.id].channel == 36
    assert project_aps[ap24.id].channel == 6  # sin mutación
    assert session.dirty is False


def test_session_optimize_without_ap_is_safe(session):
    result = session.optimize_channels()
    assert result.changed is False
    assert result.original_score is None
    assert result.optimized_assignment == {}
    assert session.dirty is False
