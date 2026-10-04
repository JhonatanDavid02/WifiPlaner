"""Pruebas de la Fase 7: extensión RF básica.

Cubre: piso de ruido configurable, SNR, umbrales de SNR/cobertura,
estándar Wi-Fi y ancho de canal (metadato/propiedad), heatmap de SNR,
stats ampliadas, diagnóstico RF básico, persistencia compatible con
schema v1/proyectos F6, configuración RF en sesión y renderer.

Lo que NO cambia (regresión congelada): fórmula FSPL, SOM, calidad,
RSSI estricto, MIN_FSPL_DISTANCE_M, MaterialAttenuationError en 6 GHz,
legacy y key-set del schema F6.
"""

from __future__ import annotations

import pytest

from config import load_config
from core.geometry import Point2D
from core.material import MaterialAttenuationError
from core.project import (
    SNR_TARGET_MAX_DB,
    SNR_TARGET_MIN_DB,
    CoverageThresholds,
    Project,
)
from core.radio import (
    CHANNEL_WIDTHS_MHZ,
    DEFAULT_NOISE_FLOOR_DBM,
    NOISE_FLOOR_MAX_DBM,
    NOISE_FLOOR_MIN_DBM,
    WIFI_STANDARDS,
    RadioConfiguration,
    allowed_channel_widths_mhz,
    wifi_generation,
)
from core.result import (
    LinkEvaluation,
    ObstacleLoss,
    QualityClass,
    SimulationResult,
    Verdict,
)
from engine.classifier import (
    classify_quality,
    meets_rssi_target,
    meets_snr_target,
    rf_diagnostic,
)
from engine.link_budget import (
    MIN_FSPL_DISTANCE_M,
    evaluate_link,
    link_budget,
    signal_to_noise_ratio,
)
from engine.simulator import simulate_coverage
from persistence import (
    SCHEMA_VERSION,
    project_from_dict,
    project_to_dict,
)
from ui.session import EditorSession, HeatmapMetric, _standard_label
from tests.factories import make_session


@pytest.fixture
def session() -> EditorSession:
    return make_session()


def _eval_at(distance_m: float = 10.0, **radio_kwargs) -> LinkEvaluation:
    radio = RadioConfiguration(**radio_kwargs)
    return evaluate_link(
        access_point_id="AP-001",
        band_id="band_2_4",
        ap_position=Point2D(0.0, 0.0),
        client_position=Point2D(distance_m, 0.0),
        radio=radio,
        frequency_mhz=2412.0,
        obstacle_loss=ObstacleLoss(total_db=0.0, crossings=0),
        thresholds=CoverageThresholds(),
    )


# ---------------------------------------------------------------------------
# 1. core/radio: piso de ruido, ancho de canal, estándar (defaults/validación)
# ---------------------------------------------------------------------------

def test_radio_defaults_f7():
    radio = RadioConfiguration()
    assert radio.noise_floor_dbm == DEFAULT_NOISE_FLOOR_DBM == -95.0
    assert radio.channel_width_mhz == 20
    assert radio.wifi_standard == "802.11ax"


def test_radio_constants_f7():
    assert CHANNEL_WIDTHS_MHZ == (20, 40, 80, 160)
    assert WIFI_STANDARDS == ("802.11n", "802.11ac", "802.11ax", "802.11be")
    assert NOISE_FLOOR_MIN_DBM == -200.0
    assert NOISE_FLOOR_MAX_DBM == 0.0


def test_noise_floor_range_limits():
    RadioConfiguration(noise_floor_dbm=NOISE_FLOOR_MIN_DBM)
    RadioConfiguration(noise_floor_dbm=NOISE_FLOOR_MAX_DBM)
    with pytest.raises(ValueError, match="debe estar en"):
        RadioConfiguration(noise_floor_dbm=NOISE_FLOOR_MIN_DBM - 0.1)
    with pytest.raises(ValueError, match="debe estar en"):
        RadioConfiguration(noise_floor_dbm=NOISE_FLOOR_MAX_DBM + 0.1)


def test_noise_floor_must_be_finite():
    with pytest.raises(ValueError, match="finito"):
        RadioConfiguration(noise_floor_dbm=float("nan"))
    with pytest.raises(ValueError, match="finito"):
        RadioConfiguration(noise_floor_dbm=float("inf"))


def test_channel_width_membership_and_int_normalization():
    RadioConfiguration(channel_width_mhz=160)
    radio = RadioConfiguration(channel_width_mhz=80.0)
    assert radio.channel_width_mhz == 80
    assert isinstance(radio.channel_width_mhz, int)
    with pytest.raises(ValueError, match="channel_width_mhz"):
        RadioConfiguration(channel_width_mhz=30)


def test_wifi_standard_membership():
    for standard in WIFI_STANDARDS:
        assert RadioConfiguration(wifi_standard=standard).wifi_standard == standard
    with pytest.raises(ValueError, match="wifi_standard"):
        RadioConfiguration(wifi_standard="802.11g")


def test_allowed_channel_widths_by_family():
    assert allowed_channel_widths_mhz(2412.0) == (20, 40)
    assert allowed_channel_widths_mhz(5180.0) == CHANNEL_WIDTHS_MHZ
    assert allowed_channel_widths_mhz(6135.0) == CHANNEL_WIDTHS_MHZ


def test_wifi_generation_labels():
    assert wifi_generation("802.11n", 2412.0) == "Wi-Fi 4"
    assert wifi_generation("802.11ac", 5180.0) == "Wi-Fi 5"
    assert wifi_generation("802.11ax", 2412.0) == "Wi-Fi 6"
    assert wifi_generation("802.11ax", 6135.0) == "Wi-Fi 6E"
    assert wifi_generation("802.11be", 6135.0) == "Wi-Fi 7"


# ---------------------------------------------------------------------------
# 2. core/project: umbral de SNR y coherencia con el RSSI objetivo
# ---------------------------------------------------------------------------

def test_thresholds_snr_default_and_range():
    thresholds = CoverageThresholds()
    assert thresholds.snr_target_db == 25.0
    CoverageThresholds(snr_target_db=SNR_TARGET_MIN_DB)
    CoverageThresholds(snr_target_db=SNR_TARGET_MAX_DB)
    with pytest.raises(ValueError, match="snr_target_db"):
        CoverageThresholds(snr_target_db=SNR_TARGET_MIN_DB - 1.0)
    with pytest.raises(ValueError, match="snr_target_db"):
        CoverageThresholds(snr_target_db=SNR_TARGET_MAX_DB + 1.0)


def test_thresholds_validates_finiteness():
    with pytest.raises(ValueError, match="finito"):
        CoverageThresholds(snr_target_db=float("nan"))
    with pytest.raises(ValueError, match="finito"):
        CoverageThresholds(rssi_target_dbm=float("inf"))


def test_thresholds_defaults_are_coherent_with_noise_floor():
    # Decisión AW: con piso −95 y objetivo RSSI −67, el SNR en el umbral
    # es 28 dB ⇒ cumplir RSSI implica cumplir el SNR objetivo (25 dB).
    thresholds = CoverageThresholds()
    radio = RadioConfiguration()
    snr_at_rssi_target = thresholds.rssi_target_dbm - radio.noise_floor_dbm
    assert round(snr_at_rssi_target, 2) >= thresholds.snr_target_db


# ---------------------------------------------------------------------------
# 3. engine: fórmula SNR, evaluate_link y congelación histórica
# ---------------------------------------------------------------------------

def test_signal_to_noise_ratio_formula():
    assert signal_to_noise_ratio(-60.0, -95.0) == 35.0
    assert signal_to_noise_ratio(-60.0, -90.0) == 30.0
    assert signal_to_noise_ratio(-95.5, -95.0) == -0.5
    assert signal_to_noise_ratio(-70.123, -95.0) == 24.88  # 2 decimales


def test_evaluate_link_populates_snr_fields():
    ev = _eval_at(10.0)
    assert ev.noise_floor_dbm == DEFAULT_NOISE_FLOOR_DBM
    assert ev.snr_db == round(ev.rx_power_dbm - DEFAULT_NOISE_FLOOR_DBM, 2)
    assert ev.snr_meets_target == (ev.snr_db >= CoverageThresholds().snr_target_db)


def test_noise_floor_change_does_not_alter_rssI_som_or_quality():
    strong = _eval_at(10.0, noise_floor_dbm=-95.0)
    noisy = _eval_at(10.0, noise_floor_dbm=-85.0)
    # Mismo FSPL y potencia recibida; solo cambia el SNR (complementa).
    assert strong.rx_power_dbm == noisy.rx_power_dbm
    assert strong.som_db == noisy.som_db
    assert strong.quality == noisy.quality
    assert strong.verdict == noisy.verdict
    assert strong.rssi_meets_target == noisy.rssi_meets_target
    assert strong.snr_db - noisy.snr_db == pytest.approx(10.0)


def test_channel_width_does_not_enter_fspl():
    wide = link_budget(
        radio=RadioConfiguration(channel_width_mhz=20),
        distance_m=10.0,
        frequency_mhz=5180.0,
    )
    wider = link_budget(
        radio=RadioConfiguration(channel_width_mhz=160),
        distance_m=10.0,
        frequency_mhz=5180.0,
    )
    assert wide.path_loss_db == wider.path_loss_db
    assert wide.rx_power_dbm == wider.rx_power_dbm


def test_legacy_fspl_floor_and_som_unchanged():
    assert MIN_FSPL_DISTANCE_M == 0.1
    ev = _eval_at(10.0)
    # SOM histórico: P_rx − sensibilidad (−75 por defecto)
    assert ev.som_db == pytest.approx(ev.rx_power_dbm - (-75.0), abs=0.01)
    # Calidad histórica intacta
    assert classify_quality(-45.0, CoverageThresholds()) == QualityClass.EXCELLENT
    assert classify_quality(-60.0, CoverageThresholds()) == QualityClass.GOOD
    assert classify_quality(-90.0, CoverageThresholds()) == QualityClass.NO_COVERAGE


def test_meets_snr_target_uses_gte_and_rssi_stays_strict():
    thresholds = CoverageThresholds()
    assert meets_snr_target(thresholds.snr_target_db, thresholds) is True
    assert meets_snr_target(thresholds.snr_target_db - 0.01, thresholds) is False
    # Regresión decisión C: RSSI sigue siendo estricto (>)
    assert meets_rssi_target(thresholds.rssi_target_dbm, thresholds) is False
    assert meets_rssi_target(thresholds.rssi_target_dbm + 0.01, thresholds) is True


def test_rf_diagnostic_quadrants():
    thresholds = CoverageThresholds()  # RSSI > −67, SNR >= 25
    assert rf_diagnostic(-60.0, 30.0, thresholds) == "RSSI adecuado / SNR adecuado"
    assert rf_diagnostic(-60.0, 20.0, thresholds) == "RSSI adecuado / SNR bajo"
    assert rf_diagnostic(-70.0, 30.0, thresholds) == "RSSI bajo / SNR adecuado"
    assert rf_diagnostic(-70.0, 20.0, thresholds) == "RSSI bajo / SNR bajo"


def test_6ghz_material_error_still_raises(session):
    from core.geometry import Point2D as P

    session.add_access_point(P(2.0, 2.0))
    session.add_wall(P(6.0, 0.0), P(6.0, 8.0))
    with pytest.raises(MaterialAttenuationError):
        session.run_heatmap("band_6")


# ---------------------------------------------------------------------------
# 4. engine/simulator: compatibilidad ancho×banda y stats de SNR
# ---------------------------------------------------------------------------

def test_simulator_rejects_width_incompatible_with_24ghz(session):
    ap = session.add_access_point(Point2D(2.0, 2.0))
    session.apply_rf_settings(
        noise_floor_dbm=-95.0,
        snr_target_db=25.0,
        rssi_target_dbm=-67.0,
        wifi_standard="802.11ax",
        channel_width_mhz=80,
    )
    assert ap.radio.channel_width_mhz == 80
    with pytest.raises(ValueError, match="incompatible"):
        session.run_heatmap("band_2_4")


def test_simulator_accepts_valid_widths_per_band():
    from core.access_point import AccessPoint

    grid_points = [Point2D(1.0, 1.0), Point2D(2.0, 2.0)]
    project = Project()
    # 2.4 GHz: 40 MHz válido
    ap40 = AccessPoint(id="AP-001", position=Point2D(1.0, 1.0),
                       radio=RadioConfiguration(channel_width_mhz=40))
    simulate_coverage(
        project=project,
        access_point=ap40,
        frequency_band=project.get_band("band_2_4"),
        sample_points=grid_points,
        walls=(),
    )
    # 5 GHz: 160 MHz válido
    ap160 = AccessPoint(id="AP-001", position=Point2D(1.0, 1.0),
                        radio=RadioConfiguration(channel_width_mhz=160))
    simulate_coverage(
        project=project,
        access_point=ap160,
        frequency_band=project.get_band("band_5"),
        sample_points=grid_points,
        walls=(),
    )


def test_heatmap_stats_include_snr_keys(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_2_4")
    stats = result.stats
    for key in (
        "snr_min_db",
        "snr_max_db",
        "snr_avg_db",
        "snr_target_db",
        "points_meeting_snr_target",
        "snr_ratio",
    ):
        assert key in stats
    assert stats["snr_min_db"] <= stats["snr_avg_db"] <= stats["snr_max_db"]
    assert stats["snr_target_db"] == CoverageThresholds().snr_target_db
    assert 0.0 <= stats["snr_ratio"] <= 1.0
    assert stats["snr_min_db"] == min(e.snr_db for e in result.evaluations)
    # Coherencia SNR/RSSI: mismo ganador, misma distancia
    for ev in result.evaluations:
        assert ev.snr_db == round(ev.rx_power_dbm - ev.noise_floor_dbm, 2)


def test_multi_ap_combined_stats_include_snr_from_winner(session):
    session.add_access_point(Point2D(1.0, 1.0))
    session.add_access_point(Point2D(7.0, 5.0))
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_2_4")
    assert "ap_dominance_percent" in result.stats  # combinado (F5)
    assert "snr_min_db" in result.stats
    assert result.stats["snr_min_db"] == min(e.snr_db for e in result.evaluations)
    assert result.stats["snr_target_db"] == 25.0
    assert 0.0 <= result.stats["snr_ratio"] <= 1.0


# ---------------------------------------------------------------------------
# 5. ui/session: métrica del heatmap y configuración RF
# ---------------------------------------------------------------------------

def test_heatmap_metric_defaults_and_enum():
    session = EditorSession()
    assert session.heatmap_metric == HeatmapMetric.RSSI.value == "rssi"
    assert {m.value for m in HeatmapMetric} == {"rssi", "snr"}


def test_set_heatmap_metric_does_not_invalidate_rf(session, tmp_path):
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    session.save_project(str(tmp_path / "clean.json"))  # limpia el dirty
    session.run_heatmap("band_2_4")
    assert session.heatmap_dirty is False
    assert session.dirty is False
    heatmap = session.last_heatmap

    session.set_heatmap_metric("snr")
    assert session.heatmap_metric == "snr"
    # Es solo una vista: NO invalida el RF (la UI repinta la imagen con
    # build_heatmap_image(..., metric=) sin volver a simular).
    assert session.heatmap_dirty is False
    assert session.last_heatmap is heatmap
    assert session.dirty is False  # es vista, no configuración (BA)

    session.set_heatmap_metric("snr")  # idempotente: no re-invalida nada nuevo
    assert session.heatmap_metric == "snr"


def test_set_heatmap_metric_rejects_unknown():
    session = EditorSession()
    with pytest.raises(ValueError, match="Métrica"):
        session.set_heatmap_metric("potencia")


def test_apply_rf_settings_atomic_and_syncs_aps(session, tmp_path):
    session.add_access_point(Point2D(2.0, 2.0))
    ap = session.project.access_points[0]
    session.save_project(str(tmp_path / "clean.json"))  # limpia el dirty
    assert session.dirty is False

    session.apply_rf_settings(
        noise_floor_dbm=-90.0,
        snr_target_db=30.0,
        rssi_target_dbm=-70.0,
        wifi_standard="802.11be",
        channel_width_mhz=40,
    )
    assert session.project.radio.noise_floor_dbm == -90.0
    assert session.project.thresholds.snr_target_db == 30.0
    assert session.project.thresholds.rssi_target_dbm == -70.0
    assert session.project.radio.wifi_standard == "802.11be"
    # F7 sin config por AP: los APs existentes se sincronizan
    assert ap.radio.noise_floor_dbm == -90.0
    assert ap.radio.channel_width_mhz == 40
    assert ap.radio.wifi_standard == "802.11be"
    assert session.dirty is True
    assert session.heatmap_dirty is True


def test_apply_rf_settings_is_atomic_on_invalid_input(session):
    # Valores de partida conocidos (sin mutar nada)
    before = (
        session.project.radio.noise_floor_dbm,
        session.project.radio.channel_width_mhz,
        session.project.thresholds.snr_target_db,
    )
    with pytest.raises(ValueError):
        session.apply_rf_settings(
            noise_floor_dbm=-999.0,
            snr_target_db=25.0,
            rssi_target_dbm=-67.0,
            wifi_standard="802.11ax",
            channel_width_mhz=20,
        )
    after = (
        session.project.radio.noise_floor_dbm,
        session.project.radio.channel_width_mhz,
        session.project.thresholds.snr_target_db,
    )
    assert before == after
    assert session.dirty is False


def test_heatmap_stats_text_header_with_standard_and_metric(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    session.run_heatmap("band_2_4")

    text = session.heatmap_stats_text()
    lines = text.split("\n")
    assert lines[0].startswith("AP: ")
    assert "Estándar: 802.11ax (Wi-Fi 6)" in text
    assert "Métrica: SNR" not in text

    session.set_heatmap_metric("snr")
    text_snr = session.heatmap_stats_text()
    assert text_snr.split("\n")[0].startswith("AP: ")
    assert "Métrica: SNR (dB)" in text_snr
    assert "SNR objetivo: 25 dB" in text_snr
    assert "SNR (dB):" in text_snr  # bloque de stats ampliadas


def test_standard_label_6e():
    assert _standard_label(Project(), 6135.0) == "802.11ax (Wi-Fi 6E)"
    assert _standard_label(Project(), 2412.0) == "802.11ax (Wi-Fi 6)"


def test_client_rssi_lines_include_snr_distance_ap_and_diagnostic(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.add_client(Point2D(4.0, 4.0))
    session.set_grid_resolution(1.0)
    session.run_heatmap("band_2_4")
    lines = session.client_rssi_lines()
    assert len(lines) == 1
    line = lines[0]
    assert "AP-001" in line
    assert "m |" in line  # distancia
    assert "SNR" in line
    assert "RSSI adecuado" in line or "RSSI bajo" in line


def test_simulation_summary_text_includes_snr(session):
    session.add_access_point(Point2D(2.0, 2.0))
    session.run_simulation("band_2_4")
    text = session.simulation_summary_text()
    assert "SNR mínimo" in text
    assert "SNR máximo" in text
    assert "RSSI mínimo" in text  # no sustituye al RSSI


def test_document_replace_resets_heatmap_metric(tmp_path):
    session = EditorSession()
    session.add_access_point(Point2D(2.0, 2.0))
    session.set_heatmap_metric("snr")
    path = str(tmp_path / "proj.json")
    session.save_project(path)

    session.set_heatmap_metric("snr")
    session.open_project(path)
    assert session.heatmap_metric == "rssi"


# ---------------------------------------------------------------------------
# 6. ui/coverage_renderer: SNR, métrica, stats tolerantes
# ---------------------------------------------------------------------------

def test_stats_text_shows_snr_block_when_present(session):
    from ui.coverage_renderer import stats_text

    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_2_4")
    text = stats_text(result)
    assert "SNR (dB):" in text
    assert "≥ objetivo 25 dB" in text


def test_stats_text_tolerates_legacy_stats_without_snr_keys():
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
    assert "Puntos del grid: 1" in text
    assert "SNR (dB):" not in text


def test_snr_color_scale_bounds():
    from ui.coverage_renderer import snr_to_rgb

    assert snr_to_rgb(0.0) == (90, 60, 90)   # peor
    assert snr_to_rgb(45.0) == (80, 200, 120)  # mejor
    low = snr_to_rgb(5.0)
    high = snr_to_rgb(40.0)
    assert sum(high) > sum(low)


def test_rssi_color_scale_unchanged_regression():
    from ui.coverage_renderer import rssi_to_rgb

    assert rssi_to_rgb(-30.0) == (80, 200, 120)
    assert rssi_to_rgb(-90.0) == (90, 60, 90)
    strong = rssi_to_rgb(-40.0)
    weak = rssi_to_rgb(-88.0)
    assert sum(strong) > sum(weak)


def test_legend_rows_and_title_by_metric():
    from ui.coverage_renderer import legend_rows, legend_title

    thresholds = CoverageThresholds()
    rssi_rows = legend_rows(thresholds)
    assert len(rssi_rows) == 5  # contrato F4/F5 intacto
    assert legend_title("rssi") == "Cobertura Wi-Fi"

    snr_rows = legend_rows(thresholds, metric="snr")
    assert len(snr_rows) == 2
    assert snr_rows[0]["label"] == "SNR objetivo"
    assert "≥ 25 dB" in snr_rows[0]["range"]
    assert "< 25 dB" in snr_rows[1]["range"]
    assert legend_title("snr") == "SNR (dB)"

    with pytest.raises(ValueError):
        legend_rows(thresholds, metric="potencia")
    with pytest.raises(ValueError):
        legend_title("potencia")


def test_build_heatmap_image_by_metric(session):
    from ui.coverage_renderer import build_heatmap_image
    from ui.viewport import Viewport

    session.add_access_point(Point2D(2.0, 2.0))
    session.set_grid_resolution(2.0)
    result = session.run_heatmap("band_2_4")
    vp = Viewport(world_width_m=12.0, world_height_m=8.0)

    img_rssi = build_heatmap_image(result, vp, cell_size_m=2.0, metric="rssi")
    img_snr = build_heatmap_image(result, vp, cell_size_m=2.0, metric="snr")
    assert img_rssi is not None and img_snr is not None
    assert img_rssi.getextrema()[3][1] > 0
    assert img_snr.getextrema()[3][1] > 0

    with pytest.raises(ValueError, match="Métrica"):
        build_heatmap_image(result, vp, metric="potencia")


# ---------------------------------------------------------------------------
# 7. Persistencia: schema v1 + claves opcionales F7 + compatibilidad F6
# ---------------------------------------------------------------------------

def test_schema_version_still_v1_and_project_keyset_unchanged(session):
    session.add_access_point(Point2D(2.0, 2.0))
    document = project_to_dict(session.project)
    assert set(document) == {
        "name", "units", "bands", "materials", "radio", "thresholds",
        "floors", "access_points", "clients", "metadata",
    }  # F7 NO añade claves de nivel project (protege el key-set F6)
    assert sorted(document["radio"]) == sorted(
        [
            "p_tx_dbm", "g_tx_dbi", "l_tx_db", "g_rx_dbi", "l_rx_db",
            "sensitivity_dbm", "fade_margin_db",
            "noise_floor_dbm", "channel_width_mhz", "wifi_standard",
        ]
    )
    assert "snr_target_db" in document["thresholds"]
    assert SCHEMA_VERSION == 1


def test_persistence_round_trip_rf_settings(session, tmp_path):
    from persistence import load_project

    session.add_access_point(Point2D(2.0, 2.0))
    session.apply_rf_settings(
        noise_floor_dbm=-97.5,
        snr_target_db=27.0,
        rssi_target_dbm=-65.0,
        wifi_standard="802.11ac",
        channel_width_mhz=80,
    )
    path = str(tmp_path / "rf.json")
    session.save_project(path)
    reloaded, _state = load_project(path)
    assert reloaded.radio.noise_floor_dbm == -97.5
    assert reloaded.radio.channel_width_mhz == 80
    assert reloaded.radio.wifi_standard == "802.11ac"
    assert reloaded.thresholds.snr_target_db == 27.0
    assert reloaded.thresholds.rssi_target_dbm == -65.0


def test_f6_project_without_new_keys_loads_with_defaults(session):
    document = project_to_dict(session.project)
    for key in ("noise_floor_dbm", "channel_width_mhz", "wifi_standard"):
        document["radio"].pop(key)
    document["thresholds"].pop("snr_target_db")
    loaded = project_from_dict(document)  # archivos F6 no deben romperse
    assert loaded.radio.noise_floor_dbm == RadioConfiguration().noise_floor_dbm
    assert loaded.radio.channel_width_mhz == RadioConfiguration().channel_width_mhz
    assert loaded.radio.wifi_standard == RadioConfiguration().wifi_standard
    assert loaded.thresholds.snr_target_db == CoverageThresholds().snr_target_db


def test_f6_invalid_new_values_are_controlled_errors(session):
    document = project_to_dict(session.project)

    bad_width = project_to_dict(session.project)
    bad_width["radio"]["channel_width_mhz"] = 999
    with pytest.raises(Exception, match="no soportado"):
        project_from_dict(bad_width)

    bad_standard = project_to_dict(session.project)
    bad_standard["radio"]["wifi_standard"] = "802.11g"
    with pytest.raises(Exception, match="no soportado"):
        project_from_dict(bad_standard)

    bad_noise = project_to_dict(session.project)
    bad_noise["radio"]["noise_floor_dbm"] = -500.0
    with pytest.raises(Exception):
        project_from_dict(bad_noise)

    bad_snr = project_to_dict(session.project)
    bad_snr["thresholds"]["snr_target_db"] = 999.0
    with pytest.raises(Exception):
        project_from_dict(bad_snr)

    # El documento base sigue siendo válido (las copias son independientes)
    assert project_from_dict(document).radio.noise_floor_dbm == -95.0


def test_saved_document_contains_f7_keys_and_schema_v1(session, tmp_path):
    import json

    session.add_access_point(Point2D(2.0, 2.0))
    path = str(tmp_path / "doc.json")
    session.save_project(path)
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["schema_version"] == 1
    assert "noise_floor_dbm" in raw["project"]["radio"]
    assert "snr_target_db" in raw["project"]["thresholds"]


# ---------------------------------------------------------------------------
# 8. config: YAML con los nuevos campos y defaults centralizados
# ---------------------------------------------------------------------------

def test_load_config_exposes_f7_fields():
    config = load_config()
    radio = config["radio"]
    thresholds = config["thresholds"]
    assert radio.noise_floor_dbm == -95.0
    assert radio.channel_width_mhz == 20
    assert radio.wifi_standard == "802.11ax"
    assert thresholds.snr_target_db == 25.0
    # Sin literales duplicados: el YAML debe coincidir con core/
    assert radio == RadioConfiguration()
    assert thresholds == CoverageThresholds()
