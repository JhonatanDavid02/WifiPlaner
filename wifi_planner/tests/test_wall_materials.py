"""Pruebas de atenuación por material y espesor (Fase 2, Tests 11–19)."""

import pytest

from core.geometry import Point2D, Segment2D
from core.material import Material, MaterialAttenuationError, default_materials
from core.project import Project
from core.wall import Wall
from engine.obstacles import trace_walls, wall_attenuation_db


def _material(material_id: str) -> Material:
    return next(m for m in default_materials() if m.id == material_id)


def _wall(
    material_id: str,
    thickness_m: float | None = None,
    wall_id: str = "w1",
) -> Wall:
    return Wall(
        id=wall_id,
        segment=Segment2D(Point2D(5, -10), Point2D(5, 10)),
        material=_material(material_id),
        thickness_m=thickness_m,
    )


def _crossing_wall(material_id: str, thickness_m: float | None = None) -> Wall:
    """Pared vertical en x=5 que el trayecto (0,0)→(10,0) atraviesa."""
    return _wall(material_id, thickness_m)


# ---------------------------------------------------------------------------
# Tests 11–14 — Atenuación de referencia por material y banda
# ---------------------------------------------------------------------------

def test_drywall_24ghz():
    wall = _crossing_wall("drywall")
    assert wall_attenuation_db(wall, "band_2_4") == pytest.approx(3.0)


def test_drywall_5ghz():
    wall = _crossing_wall("drywall")
    assert wall_attenuation_db(wall, "band_5") == pytest.approx(4.0)


def test_concrete_24ghz():
    wall = _crossing_wall("concrete")
    assert wall_attenuation_db(wall, "band_2_4") == pytest.approx(12.0)


def test_concrete_5ghz():
    wall = _crossing_wall("concrete")
    assert wall_attenuation_db(wall, "band_5") == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Test 15 — Cambio de material produce diferente pérdida
# ---------------------------------------------------------------------------

def test_different_materials_different_loss():
    drywall_loss = wall_attenuation_db(_crossing_wall("drywall"), "band_2_4")
    concrete_loss = wall_attenuation_db(_crossing_wall("concrete"), "band_2_4")
    metal_loss = wall_attenuation_db(_crossing_wall("metal"), "band_2_4")

    assert drywall_loss != concrete_loss
    assert concrete_loss != metal_loss
    assert drywall_loss < concrete_loss < metal_loss


# ---------------------------------------------------------------------------
# Test 16 — Mayor espesor según el modelo lineal
# ---------------------------------------------------------------------------

def test_double_thickness_doubles_loss():
    # drywall: espesor ref 0.012 m, L_ref 3 dB @2.4
    wall_1x = _crossing_wall("drywall", thickness_m=0.012)
    wall_2x = _crossing_wall("drywall", thickness_m=0.024)
    assert wall_attenuation_db(wall_1x, "band_2_4") == pytest.approx(3.0)
    assert wall_attenuation_db(wall_2x, "band_2_4") == pytest.approx(6.0)

    # concrete: espesor ref 0.15 m, L_ref 12 dB @2.4
    conc_1x = _crossing_wall("concrete", thickness_m=0.15)
    conc_half = _crossing_wall("concrete", thickness_m=0.075)
    assert wall_attenuation_db(conc_1x, "band_2_4") == pytest.approx(12.0)
    assert wall_attenuation_db(conc_half, "band_2_4") == pytest.approx(6.0)


def test_default_thickness_uses_reference_unchanged():
    """thickness_m=None => espesor de referencia => L = L_ref."""
    wall = _crossing_wall("brick")
    assert wall.effective_thickness == _material("brick").thickness_default_m
    assert wall_attenuation_db(wall, "band_2_4") == pytest.approx(6.0)
    assert wall_attenuation_db(wall, "band_5") == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Test 17 — Espesor inválido falla correctamente
# ---------------------------------------------------------------------------

def test_zero_thickness_raises():
    wall = _crossing_wall("drywall", thickness_m=0.0)
    with pytest.raises(ValueError):
        wall_attenuation_db(wall, "band_2_4")


def test_negative_thickness_raises():
    wall = _crossing_wall("drywall", thickness_m=-0.01)
    with pytest.raises(ValueError):
        wall_attenuation_db(wall, "band_2_4")


# ---------------------------------------------------------------------------
# Test 18 — Material inexistente falla correctamente
# ---------------------------------------------------------------------------

def test_nonexistent_material_lookup_raises():
    project = Project()
    with pytest.raises(KeyError):
        project.get_material("unobtainium")


def test_material_without_band_data_raises():
    hollow = Material(id="hollow", name="Hollow", attenuation_db={})
    wall = Wall(
        id="w_hollow",
        segment=Segment2D(Point2D(5, -1), Point2D(5, 1)),
        material=hollow,
    )
    with pytest.raises(MaterialAttenuationError):
        wall_attenuation_db(wall, "band_2_4")


# ---------------------------------------------------------------------------
# Test 19 — 6 GHz sin atenuación definida falla de forma explícita
# ---------------------------------------------------------------------------

def test_6ghz_without_data_raises_explicitly():
    wall = _crossing_wall("drywall")
    with pytest.raises(MaterialAttenuationError):
        wall_attenuation_db(wall, "band_6")


def test_6ghz_trace_walls_raises_and_does_not_invent_values():
    wall = _crossing_wall("concrete")
    with pytest.raises(MaterialAttenuationError):
        trace_walls(Point2D(0, 0), Point2D(10, 0), [wall], "band_6")


def test_6ghz_not_silently_mapped_to_5ghz():
    """Asegura que no hay fallback encubierto 5→6 GHz."""
    wall = _crossing_wall("concrete")
    loss_5 = wall_attenuation_db(wall, "band_5")
    with pytest.raises(MaterialAttenuationError) as exc_info:
        wall_attenuation_db(wall, "band_6")
    assert "band_6" in str(exc_info.value)
    # 5 GHz sigue disponible y con su propio valor
    assert loss_5 == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Paredes que no bloquean señal
# ---------------------------------------------------------------------------

def test_non_blocking_wall_zero_loss():
    wall = Wall(
        id="deco",
        segment=Segment2D(Point2D(5, -1), Point2D(5, 1)),
        material=_material("metal"),
        blocks_signal=False,
    )
    assert wall_attenuation_db(wall, "band_2_4") == 0.0
