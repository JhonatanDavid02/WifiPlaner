"""Pruebas de canales y configuración RF por AP (Fase 10).

Cubre: catálogo por familia (BQ), canal ≠ frecuencia y frecuencia
derivada (BR), invariante AP banda+canal (BS), validación centralizada
del triple (BT), configuración por AP con persistencia (BV) y —lo más
crítico— que el canal NO altera FSPL/RSSI/SOM/SNR/veredicto/calidad
(A/B y regresión de heatmap; decisiones BR/BW).

No modifica ni replica los tests de F6/F7/F9 (esos contratos se
mantienen intactos aquí y en la suite completa).
"""

from __future__ import annotations

import json

import pytest

from core.access_point import AccessPoint
from core.band import DEFAULT_BANDS
from core.channel import (
    MAX_CHANNEL_NUMBER,
    WifiChannel,
    channel_for_band,
    channel_numbers_for_frequency,
    channels_for_frequency,
    default_channel,
    validate_channel_config,
)
from core.geometry import Point2D
from core.project import Project
from core.radio import RadioConfiguration
from engine.simulator import simulate_coverage
from persistence import (
    ProjectFormatError,
    document_to_dict,
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)
from ui.session import EditorSession, SelectionKind

BAND_24 = next(b for b in DEFAULT_BANDS if b.id == "band_2_4")
BAND_5 = next(b for b in DEFAULT_BANDS if b.id == "band_5")
BAND_6 = next(b for b in DEFAULT_BANDS if b.id == "band_6")


@pytest.fixture
def session() -> EditorSession:
    return EditorSession()


def _ap(session: EditorSession, ap_id: str) -> AccessPoint:
    return next(a for a in session.project.access_points if a.id == ap_id)


def _fingerprint(result) -> list:
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


# ---------------------------------------------------------------------------
# Catálogo por familia (decisión BQ)
# ---------------------------------------------------------------------------

def test_catalog_24ghz_reference_channels():
    assert channel_for_band(BAND_24, 1).center_frequency_mhz == 2412.0
    assert channel_for_band(BAND_24, 6).center_frequency_mhz == 2437.0
    assert channel_for_band(BAND_24, 11).center_frequency_mhz == 2462.0
    assert channel_for_band(BAND_24, 14).center_frequency_mhz == 2484.0
    assert channel_numbers_for_frequency(BAND_24.frequency_mhz) == tuple(
        range(1, 15)
    )


def test_catalog_5ghz_reference_channels():
    assert channel_for_band(BAND_5, 36).center_frequency_mhz == 5180.0
    assert channel_for_band(BAND_5, 44).center_frequency_mhz == 5220.0
    assert channel_for_band(BAND_5, 149).center_frequency_mhz == 5745.0
    assert channel_for_band(BAND_5, 165).center_frequency_mhz == 5825.0
    numbers = channel_numbers_for_frequency(BAND_5.frequency_mhz)
    assert 36 in numbers and 149 in numbers and 165 in numbers
    assert 6 not in numbers  # canal de otra familia


def test_catalog_6ghz_reference_channels():
    assert channel_for_band(BAND_6, 1).center_frequency_mhz == 5955.0
    assert channel_for_band(BAND_6, 5).center_frequency_mhz == 5975.0
    assert channel_for_band(BAND_6, 37).center_frequency_mhz == 6135.0
    assert channel_for_band(BAND_6, 233).center_frequency_mhz == 7115.0


def test_channel_for_band_rejects_cross_family():
    with pytest.raises(ValueError, match="no pertenece"):
        channel_for_band(BAND_5, 6)  # canal 2.4 en banda 5
    with pytest.raises(ValueError, match="no pertenece"):
        channel_for_band(BAND_24, 36)  # canal 5 en banda 2.4
    with pytest.raises(ValueError, match="no pertenece"):
        channel_for_band(BAND_5, 233)  # canal 6 en banda 5
    with pytest.raises(ValueError, match="no pertenece"):
        channel_for_band(BAND_6, 36)  # canal 5 en banda 6
    with pytest.raises(ValueError, match="no pertenece"):
        channel_for_band(BAND_5, 999)
    # Nota: números como 149/165 existen en 5 GHz y en 6 GHz (la
    # numeración se solapa entre familias): por eso la validación SIEMPRE
    # es contextual al canal elegido contra SU banda (decisión BT).
    assert channel_for_band(BAND_5, 149).center_frequency_mhz == 5745.0
    assert channel_for_band(BAND_6, 149).center_frequency_mhz == 6695.0


def test_channel_for_band_rejects_non_int_types():
    with pytest.raises(ValueError):
        channel_for_band(BAND_5, True)
    with pytest.raises(ValueError):
        channel_for_band(BAND_5, 36.0)
    with pytest.raises(ValueError):
        channel_for_band(BAND_5, "36")


def test_channels_for_frequency_family_boundaries():
    assert channels_for_frequency(2437.0) is channels_for_frequency(2484.0)
    assert channels_for_frequency(5180.0) is channels_for_frequency(5825.0)
    assert channels_for_frequency(5925.0) is channels_for_frequency(7115.0)
    with pytest.raises(ValueError):
        channels_for_frequency(0)
    with pytest.raises(ValueError):
        channels_for_frequency(float("nan"))


def test_default_channel_matches_band_reference():
    assert default_channel(BAND_24).number == 6
    assert default_channel(BAND_5).number == 36
    assert default_channel(BAND_6).number == 37


def test_wifi_channel_invariants():
    with pytest.raises(ValueError):
        WifiChannel(number=0, center_frequency_mhz=5180.0)
    with pytest.raises(ValueError):
        WifiChannel(number=MAX_CHANNEL_NUMBER + 1, center_frequency_mhz=7115.0)
    with pytest.raises(ValueError):
        WifiChannel(number=36, center_frequency_mhz=0)
    with pytest.raises(ValueError):
        WifiChannel(number=True, center_frequency_mhz=5180.0)
    assert MAX_CHANNEL_NUMBER == 233


# ---------------------------------------------------------------------------
# Validación centralizada del triple (decisión BT)
# ---------------------------------------------------------------------------

def test_validate_channel_config_ok():
    channel = validate_channel_config(BAND_5, 40, 80)
    assert channel.number == 40
    assert channel.center_frequency_mhz == 5200.0
    assert validate_channel_config(BAND_24, 6, 20).number == 6
    assert validate_channel_config(BAND_6, 37, 160).number == 37


def test_validate_channel_config_rejects_width_not_allowed_on_family():
    with pytest.raises(ValueError, match="no permitido"):
        validate_channel_config(BAND_24, 6, 80)  # regla F7: 2.4 → 20/40
    with pytest.raises(ValueError, match="no permitido"):
        validate_channel_config(BAND_24, 6, 160)
    with pytest.raises(ValueError, match="no permitido"):
        validate_channel_config(BAND_5, 36, 0)


def test_validate_channel_config_rejects_bad_channel_or_type():
    with pytest.raises(ValueError):
        validate_channel_config(BAND_5, 6, 20)  # canal de 2.4 GHz
    with pytest.raises(ValueError):
        validate_channel_config(BAND_5, 36, True)


# ---------------------------------------------------------------------------
# Invariantes de AccessPoint (decisión BS)
# ---------------------------------------------------------------------------

def test_ap_channel_requires_band_id():
    with pytest.raises(ValueError, match="band_id"):
        AccessPoint(id="AP-001", position=Point2D(1, 1), channel=36)


def test_ap_band_and_channel_type_checks():
    with pytest.raises(ValueError, match="band_id"):
        AccessPoint(id="AP-001", position=Point2D(1, 1), band_id="")
    with pytest.raises(ValueError, match="band_id"):
        AccessPoint(id="AP-001", position=Point2D(1, 1), band_id=True)
    with pytest.raises(ValueError):
        AccessPoint(id="AP-001", position=Point2D(1, 1), band_id="band_5", channel=0)
    with pytest.raises(ValueError):
        AccessPoint(
            id="AP-001", position=Point2D(1, 1), band_id="band_5", channel=True
        )
    with pytest.raises(ValueError):
        AccessPoint(
            id="AP-001", position=Point2D(1, 1), band_id="band_5", channel=36.5
        )


def test_ap_defaults_keep_f1_to_f9_compatibility():
    ap = AccessPoint(id="AP-001", position=Point2D(1, 1))
    assert ap.band_id is None
    assert ap.channel is None
    ap_ok = AccessPoint(
        id="AP-002", position=Point2D(1, 1), band_id="band_5", channel=36
    )
    assert ap_ok.band_id == "band_5" and ap_ok.channel == 36


# ---------------------------------------------------------------------------
# CRÍTICO: el canal NO altera la simulación (A/B; decisiones BR/BW)
# ---------------------------------------------------------------------------

def test_ab_channel_does_not_change_simulation():
    project = Project(name="ab")
    points = [Point2D(3, 2), Point2D(8, 6), Point2D(14, 9)]
    ap36 = AccessPoint(
        id="AP-001",
        position=Point2D(1, 1),
        radio=RadioConfiguration(),
        band_id="band_5",
        channel=36,
    )
    ap40 = AccessPoint(
        id="AP-001",
        position=Point2D(1, 1),
        radio=RadioConfiguration(),
        band_id="band_5",
        channel=40,
    )
    r36 = simulate_coverage(
        project=project, access_point=ap36, frequency_band=BAND_5,
        sample_points=points,
    )
    r40 = simulate_coverage(
        project=project, access_point=ap40, frequency_band=BAND_5,
        sample_points=points,
    )
    for e36, e40 in zip(r36.evaluations, r40.evaluations):
        assert e36.path_loss_db == e40.path_loss_db
        assert e36.obstacle_loss_db == e40.obstacle_loss_db
        assert e36.rx_power_dbm == e40.rx_power_dbm
        assert e36.som_db == e40.som_db
        assert e36.snr_db == e40.snr_db
        assert e36.quality == e40.quality
        assert e36.verdict == e40.verdict
        assert e36.band_id == e40.band_id == "band_5"


def test_ab_channel_does_not_change_simulation_with_walls(session):
    """Mismo trayecto con pared: la pérdida de obstáculos tampoco cambia."""
    session.add_wall(Point2D(6, 0), Point2D(6, 10))
    project = session.project
    walls = session.floor.walls
    points = [Point2D(8, 5), Point2D(9, 7)]
    ap20 = AccessPoint(
        id="AP-001", position=Point2D(1, 5), band_id="band_5", channel=36
    )
    ap40 = AccessPoint(
        id="AP-001", position=Point2D(1, 5), band_id="band_5", channel=40
    )
    r20 = simulate_coverage(
        project=project, access_point=ap20, frequency_band=BAND_5,
        sample_points=points, walls=walls,
    )
    r40 = simulate_coverage(
        project=project, access_point=ap40, frequency_band=BAND_5,
        sample_points=points, walls=walls,
    )
    for e20, e40 in zip(r20.evaluations, r40.evaluations):
        assert e20.obstacle_loss_db == e40.obstacle_loss_db > 0
        assert e20.rx_power_dbm == e40.rx_power_dbm
        assert e20.snr_db == e40.snr_db


def test_ab_heatmap_identical_after_configuring_channels(session):
    """Heatmap combinado idéntico antes/después de configurar canales."""
    session.add_access_point(Point2D(2.0, 2.0))
    session.add_access_point(Point2D(10.0, 6.0))
    session.set_grid_resolution(2.0)
    session.run_heatmap("band_5")
    baseline = _fingerprint(session.last_heatmap)
    session.set_ap_rf_config("AP-001", band_id="band_5", channel=36, width_mhz=80)
    session.set_ap_rf_config("AP-002", band_id="band_5", channel=44, width_mhz=40)
    result = session.run_heatmap("band_5")
    assert _fingerprint(result) == baseline
    assert result.stats["source_results"] == 2


# ---------------------------------------------------------------------------
# Configuración por AP (sesión; decisiones BS/BT/BU)
# ---------------------------------------------------------------------------

def test_config_independent_per_ap(session):
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=80)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=44, width_mhz=40)
    assert (_ap(session, ap1.id).band_id, _ap(session, ap1.id).channel) == (
        "band_5",
        36,
    )
    assert (_ap(session, ap2.id).band_id, _ap(session, ap2.id).channel) == (
        "band_5",
        44,
    )
    assert _ap(session, ap1.id).radio.channel_width_mhz == 80
    assert _ap(session, ap2.id).radio.channel_width_mhz == 40
    # No existe canal "global": configurar uno no toca al otro.
    assert not hasattr(session, "channel")


def test_config_atomics_on_invalid_triple(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.mark_saved()  # limpio antes de intentar cambios inválidos
    with pytest.raises(ValueError):
        session.set_ap_rf_config(ap.id, band_id="band_2_4", channel=6, width_mhz=80)
    current = _ap(session, ap.id)
    assert current.band_id is None and current.channel is None
    assert current.radio.channel_width_mhz == 20  # default intacto
    with pytest.raises(ValueError):  # canal de 2.4 en banda 5
        session.set_ap_rf_config(ap.id, band_id="band_5", channel=6, width_mhz=20)
    assert _ap(session, ap.id).band_id is None
    assert session.dirty is False  # nada cambió ⇒ sin dirty (BU)


def test_config_unknown_ap_or_band(session):
    session.add_access_point(Point2D(1, 1))
    with pytest.raises(KeyError):
        session.set_ap_rf_config("AP-999", band_id="band_5", channel=36, width_mhz=20)
    with pytest.raises(KeyError):
        session.set_ap_rf_config(
            "AP-001", band_id="band_99", channel=36, width_mhz=20
        )


def test_config_dirty_only_on_real_change(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    assert session.dirty is True
    session.run_heatmap("band_5")
    assert session.heatmap_dirty is False
    # Mismo triple ⇒ sin mutación: el heatmap sigue válido (decisión BU).
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    assert session.heatmap_dirty is False
    # Cambio de canal ⇒ invalidación genérica F4 (no por la física).
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=40, width_mhz=20)
    assert session.heatmap_dirty is True
    assert _ap(session, ap.id).channel == 40


def test_resolve_band_for_ap(session):
    ap = session.add_access_point(Point2D(1, 1))
    assert session.band_id == "band_2_4"
    assert session.resolve_band_for_ap(ap).id == "band_2_4"  # sin banda ⇒ activa
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    session.set_band("band_6")
    # La banda configurada del AP manda sobre la activa (decisión BS).
    assert session.resolve_band_for_ap(_ap(session, ap.id)).id == "band_5"
    with pytest.raises(KeyError):
        session.resolve_band_for_ap(
            AccessPoint(
                id="AP-X", position=Point2D(0, 0), band_id="band_99", channel=1
            )
        )


def test_heatmap_uses_per_ap_band_over_active(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.set_grid_resolution(2.0)
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    result = session.run_heatmap("band_2_4")
    assert session.band_id == "band_2_4"  # la banda activa no se tocó
    assert result.band_id == "band_5"  # el AP se simuló en su banda
    assert all(e.band_id == "band_5" for e in result.evaluations)


def test_heatmap_mixed_bands_still_rejected(session):
    """Contrato F5 intacto: bandas mixtas → combine_results rechaza."""
    ap1 = session.add_access_point(Point2D(2.0, 2.0))
    ap2 = session.add_access_point(Point2D(8.0, 6.0))
    session.set_grid_resolution(2.0)
    session.set_ap_rf_config(ap1.id, band_id="band_2_4", channel=6, width_mhz=20)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=36, width_mhz=20)
    with pytest.raises(ValueError):
        session.run_heatmap("band_5")


def test_simulation_uses_per_ap_band(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    result = session.run_simulation("band_2_4")
    assert result.band_id == "band_5"
    assert session.last_simulation is result


# ---------------------------------------------------------------------------
# Persistencia: band_id opcional + canal validado (decisión BV)
# ---------------------------------------------------------------------------

def test_persistence_roundtrip_ap_rf(session, tmp_path):
    ap1 = session.add_access_point(Point2D(1, 1))
    ap2 = session.add_access_point(Point2D(5, 5))
    session.set_ap_rf_config(ap1.id, band_id="band_5", channel=36, width_mhz=80)
    session.set_ap_rf_config(ap2.id, band_id="band_5", channel=44, width_mhz=40)
    path = session.save_project(str(tmp_path / "rf.json"))
    loaded, _state = load_project(path)
    a1 = next(a for a in loaded.access_points if a.id == ap1.id)
    a2 = next(a for a in loaded.access_points if a.id == ap2.id)
    assert (a1.band_id, a1.channel, a1.radio.channel_width_mhz) == ("band_5", 36, 80)
    assert (a2.band_id, a2.channel, a2.radio.channel_width_mhz) == ("band_5", 44, 40)
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["project"]["access_points"][0]["band_id"] == "band_5"
    assert raw["project"]["access_points"][0]["channel"] == 36
    # La frecuencia central NUNCA se persiste (decisión BR).
    assert "center_frequency_mhz" not in json.dumps(raw)


def test_persistence_deterministic_with_channels(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=80)
    d1 = project_to_dict(session.project)
    d2 = project_to_dict(session.project)
    assert d1 == d2
    assert project_to_dict(project_from_dict(d1)) == d1


def test_persistence_compat_f6_f9_without_band_id(tmp_path):
    """Archivos F6–F9 sin band_id abren con APs en la banda activa."""
    s = EditorSession()
    ap = s.add_access_point(Point2D(2.0, 2.0))
    path = save_project(s.project, tmp_path / "legacy.json", s.editor_state())
    raw = json.loads(open(path, encoding="utf-8").read())
    for item in raw["project"]["access_points"]:
        item.pop("band_id", None)
        item.pop("channel", None)
    legacy = tmp_path / "legacy_sin_band.json"
    legacy.write_text(json.dumps(raw), encoding="utf-8")
    loaded, _state = load_project(str(legacy))
    legacy_ap = loaded.access_points[0]
    assert legacy_ap.id == ap.id
    assert legacy_ap.band_id is None
    assert legacy_ap.channel is None


def test_persistence_rejects_channel_without_band(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(2.0, 2.0))
    doc = document_to_dict(s.project, s.editor_state())
    doc["project"]["access_points"][0]["channel"] = 36
    path = tmp_path / "sin_banda.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="requiere band_id"):
        load_project(str(path))


def test_persistence_rejects_unknown_band_id(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(2.0, 2.0))
    doc = document_to_dict(s.project, s.editor_state())
    doc["project"]["access_points"][0]["band_id"] = "band_99"
    path = tmp_path / "band_99.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="banda desconocida"):
        load_project(str(path))


def test_persistence_rejects_channel_outside_catalog(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(2.0, 2.0))
    doc = document_to_dict(s.project, s.editor_state())
    doc["project"]["access_points"][0]["band_id"] = "band_5"
    doc["project"]["access_points"][0]["channel"] = 6  # canal de 2.4 GHz
    path = tmp_path / "canales_malos.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="no pertenece"):
        load_project(str(path))


def test_persistence_rejects_bad_types_with_band(tmp_path):
    s = EditorSession()
    s.add_access_point(Point2D(2.0, 2.0))
    doc = document_to_dict(s.project, s.editor_state())
    doc["project"]["access_points"][0]["band_id"] = "band_5"
    doc["project"]["access_points"][0]["channel"] = True
    path = tmp_path / "channel_bool.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="entero"):
        load_project(str(path))
    doc["project"]["access_points"][0]["channel"] = 36
    doc["project"]["access_points"][0]["band_id"] = True
    path = tmp_path / "band_bool.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="texto|cadena|entero"):
        load_project(str(path))


def test_schema_version_still_v1_with_band_id(session, tmp_path):
    ap = session.add_access_point(Point2D(1, 1))
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    path = save_project(session.project, tmp_path / "v1.json", session.editor_state())
    raw = json.loads(open(path, encoding="utf-8").read())
    assert raw["schema_version"] == 1
    loaded, _state = load_project(path)
    assert project_to_dict(loaded) == project_to_dict(session.project)


def test_editor_selection_kind_still_ap_after_config(session):
    ap = session.add_access_point(Point2D(1, 1))
    session.select(SelectionKind.AP, ap.id)
    session.set_ap_rf_config(ap.id, band_id="band_5", channel=36, width_mhz=20)
    assert session.selection.kind == SelectionKind.AP
    assert session.selection.entity_id == ap.id
