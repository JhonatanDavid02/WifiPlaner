"""Pruebas del presupuesto de enlace y SOM.

Usa golden data del DOCX (Tabla 2 y Tabla 3) como valores de referencia.
"""

import pytest

from core.geometry import Point2D
from core.project import CoverageThresholds
from core.radio import RadioConfiguration
from engine.link_budget import link_budget, system_operating_margin, evaluate_link
from engine.obstacles import obstacle_loss_for_crossings
from core.material import Material
from tests.fixtures.golden_data import (
    LEGACY_RADIO_PARAMS,
    TABLA_2,
    TABLA_3,
)


def _legacy_radio(**overrides) -> RadioConfiguration:
    params = {**LEGACY_RADIO_PARAMS, **overrides}
    return RadioConfiguration(**params)


# ---------------------------------------------------------------------------
# Presupuesto de enlace básico
# ---------------------------------------------------------------------------

def test_link_budget_golden_tabla_2():
    """Valida FSPL / P_rx / SOM / veredicto contra la Tabla 2 del DOCX."""
    thresholds = CoverageThresholds()
    radio = _legacy_radio()
    ap = Point2D(0.0, 0.0)

    for distancia, freq, esperado_fspl, esperado_rssi, esperado_som, esperado_veredicto in TABLA_2:
        cliente = Point2D(distancia, 0.0)
        evaluation = evaluate_link(
            radio=radio,
            access_point_id="AP_TEST",
            band_id="band_test",
            ap_position=ap,
            client_position=cliente,
            frequency_mhz=freq,
            thresholds=thresholds,
        )
        assert evaluation.path_loss_db == pytest.approx(esperado_fspl, abs=0.01)
        assert evaluation.rx_power_dbm == pytest.approx(esperado_rssi, abs=0.01)
        assert evaluation.som_db == pytest.approx(esperado_som, abs=0.01)
        assert evaluation.verdict.value == esperado_veredicto


def test_link_budget_golden_tabla_3():
    """Valida SOM por AP (Tabla 3 del DOCX) con distancias históricas."""
    radio = _legacy_radio()
    ap = Point2D(0.0, 0.0)
    thresholds = CoverageThresholds()

    for _ap_id, distancia, som_24, som_5 in TABLA_3:
        cliente = Point2D(distancia, 0.0)
        ev_24 = evaluate_link(
            radio=radio,
            access_point_id=_ap_id,
            band_id="band_2_4",
            ap_position=ap,
            client_position=cliente,
            frequency_mhz=2437.0,
            thresholds=thresholds,
        )
        ev_5 = evaluate_link(
            radio=radio,
            access_point_id=_ap_id,
            band_id="band_5",
            ap_position=ap,
            client_position=cliente,
            frequency_mhz=5180.0,
            thresholds=thresholds,
        )
        assert ev_24.som_db == pytest.approx(som_24, abs=0.05)
        assert ev_5.som_db == pytest.approx(som_5, abs=0.05)


def test_fade_margin_zero_reproduces_legacy_v3_v4():
    """Con Lm=0 el resultado coincide con las versiones v3/v4 (sin margen)."""
    radio = _legacy_radio(fade_margin_db=0.0)
    budget = link_budget(radio=radio, distance_m=10.0, frequency_mhz=5180.0)
    # FSPL=66.74; P_rx = 20+3-1-66.74-0+0-1 = -45.74
    assert budget.rx_power_dbm == pytest.approx(-45.74, abs=0.01)
    assert budget.som_db == pytest.approx(29.26, abs=0.01)
    assert budget.fade_margin_db == 0.0


def test_fade_margin_default_is_10_db():
    radio = RadioConfiguration()
    assert radio.fade_margin_db == 10.0


def test_som_simple():
    assert system_operating_margin(-55.74, -75.0) == pytest.approx(19.26, abs=0.01)


def test_link_budget_rejects_zero_distance():
    radio = _legacy_radio()
    with pytest.raises(ValueError):
        link_budget(radio=radio, distance_m=0.0, frequency_mhz=5180.0)


def test_link_budget_rejects_negative_obstacle_loss():
    radio = _legacy_radio()
    with pytest.raises(ValueError):
        link_budget(
            radio=radio,
            distance_m=10.0,
            frequency_mhz=5180.0,
            obstacle_loss_db=-1.0,
        )


def test_power_change_affects_rx_linearly():
    radio_a = _legacy_radio(p_tx_dbm=20.0)
    radio_b = _legacy_radio(p_tx_dbm=30.0)
    budget_a = link_budget(radio=radio_a, distance_m=10.0, frequency_mhz=5180.0)
    budget_b = link_budget(radio=radio_b, distance_m=10.0, frequency_mhz=5180.0)
    assert budget_b.rx_power_dbm - budget_a.rx_power_dbm == pytest.approx(10.0, abs=0.01)


def test_obstacle_loss_zero_by_default():
    radio = _legacy_radio()
    budget = link_budget(radio=radio, distance_m=10.0, frequency_mhz=5180.0)
    assert budget.obstacle_loss_db == 0.0


# ---------------------------------------------------------------------------
# Pérdida por obstáculos (materiales)
# ---------------------------------------------------------------------------

def _material(mid, name, att):
    return Material(
        id=mid,
        name=name,
        thickness_default_m=0.1,
        attenuation_db=att,
    )


def test_no_obstacles_loss_is_zero():
    result = obstacle_loss_for_crossings([], "band_2_4")
    assert result.total_db == 0.0
    assert result.crossings == 0


def test_single_wall_obstacle_loss():
    drywall = _material("drywall", "Drywall", {"band_2_4": 3.0, "band_5": 4.0})
    result = obstacle_loss_for_crossings([drywall], "band_5")
    assert result.total_db == pytest.approx(4.0)
    assert result.crossings == 1
    assert result.detail[0].loss_db == pytest.approx(4.0)


def test_multiple_walls_sum():
    drywall = _material("drywall", "Drywall", {"band_2_4": 3.0, "band_5": 4.0})
    brick = _material("brick", "Ladrillo", {"band_2_4": 6.0, "band_5": 8.0})
    result = obstacle_loss_for_crossings([drywall, brick], "band_2_4")
    assert result.total_db == pytest.approx(9.0)
    assert result.crossings == 2


def test_obstacle_loss_reduces_rx_power():
    radio = _legacy_radio()
    drywall = _material("drywall", "Drywall", {"band_2_4": 3.0, "band_5": 4.0})

    budget_sin = link_budget(radio=radio, distance_m=10.0, frequency_mhz=5180.0)
    budget_con = link_budget(
        radio=radio,
        distance_m=10.0,
        frequency_mhz=5180.0,
        obstacle_loss_db=4.0,
    )
    assert budget_con.rx_power_dbm == pytest.approx(
        budget_sin.rx_power_dbm - 4.0, abs=0.01
    )
    assert drywall.attenuation_for("band_5") == 4.0


def test_material_missing_band_raises():
    drywall = _material("drywall", "Drywall", {"band_2_4": 3.0})
    from core.material import MaterialAttenuationError

    with pytest.raises(MaterialAttenuationError):
        obstacle_loss_for_crossings([drywall], "band_6")


# ---------------------------------------------------------------------------
# Cambio de frecuencia / potencia / sensibilidad
# ---------------------------------------------------------------------------

def test_frequency_change_affects_fspl():
    radio = _legacy_radio()
    b_24 = link_budget(radio=radio, distance_m=10.0, frequency_mhz=2437.0)
    b_5 = link_budget(radio=radio, distance_m=10.0, frequency_mhz=5180.0)
    assert b_5.path_loss_db > b_24.path_loss_db
    assert b_5.rx_power_dbm < b_24.rx_power_dbm


def test_sensitivity_change_affects_som():
    radio_loose = _legacy_radio(sensitivity_dbm=-75.0)
    radio_strict = _legacy_radio(sensitivity_dbm=-80.0)
    b_loose = link_budget(radio=radio_loose, distance_m=10.0, frequency_mhz=5180.0)
    b_strict = link_budget(radio=radio_strict, distance_m=10.0, frequency_mhz=5180.0)
    # Sensibilidad más exigente (más negativa) => SOM mayor
    assert b_strict.som_db > b_loose.som_db
