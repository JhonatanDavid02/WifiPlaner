"""Pruebas de configuración centralizada."""

from pathlib import Path

from config import load_config


def test_load_default_config():
    cfg = load_config()
    assert cfg["radio"].p_tx_dbm == 20.0
    assert cfg["radio"].fade_margin_db == 10.0
    assert cfg["thresholds"].rssi_target_dbm == -67.0
    assert cfg["thresholds"].som_aprobado_min_db == 20.0
    assert cfg["thresholds"].som_riesgo_min_db == 10.0
    assert cfg["thresholds"].excellent_min_dbm == -50.0
    assert cfg["thresholds"].weak_min_dbm == -85.0


def test_config_has_three_bands():
    cfg = load_config()
    band_ids = [b.id for b in cfg["bands"]]
    assert band_ids == ["band_2_4", "band_5", "band_6"]


def test_config_materials_have_required_ids():
    cfg = load_config()
    material_ids = {m.id for m in cfg["materials"]}
    expected = {
        "drywall",
        "wood",
        "glass",
        "brick",
        "concrete",
        "reinforced_concrete",
        "metal",
    }
    assert expected.issubset(material_ids)


def test_config_materials_have_24_and_5_bands():
    cfg = load_config()
    for material in cfg["materials"]:
        assert material.has_band("band_2_4"), material.id
        assert material.has_band("band_5"), material.id


def test_config_loads_from_custom_path(tmp_path: Path):
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        """
radio:
  p_tx_dbm: 30.0
  fade_margin_db: 0.0
thresholds:
  rssi_target_dbm: -70.0
bands: []
materials: []
""",
        encoding="utf-8",
    )
    cfg = load_config(custom)
    assert cfg["radio"].p_tx_dbm == 30.0
    assert cfg["radio"].fade_margin_db == 0.0
    assert cfg["thresholds"].rssi_target_dbm == -70.0
