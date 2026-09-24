"""Carga de configuración centralizada desde config/default_config.yaml.

El motor y la UI leen los parámetros desde aquí; nunca hardcodean
umbrales, potencias ni atenuaciones de materiales.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.band import FrequencyBand
from core.material import Material
from core.project import CoverageThresholds
from core.radio import RadioConfiguration

_DEFAULT_PATH = Path(__file__).resolve().parent / "default_config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Carga el YAML de configuración y devuelve un dict tipado por secciones.

    Args:
        path: Ruta al YAML. Si es None se usa config/default_config.yaml.

    Returns:
        Dict con claves: radio, thresholds, bands, materials.
    """
    config_path = Path(path) if path is not None else _DEFAULT_PATH
    with config_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"Configuración inválida en {config_path}")

    return {
        "radio": _parse_radio(raw.get("radio", {})),
        "thresholds": _parse_thresholds(raw.get("thresholds", {})),
        "bands": _parse_bands(raw.get("bands", [])),
        "materials": _parse_materials(raw.get("materials", [])),
    }


def _parse_radio(data: dict) -> RadioConfiguration:
    return RadioConfiguration(
        p_tx_dbm=float(data.get("p_tx_dbm", 20.0)),
        g_tx_dbi=float(data.get("g_tx_dbi", 3.0)),
        l_tx_db=float(data.get("l_tx_db", 1.0)),
        g_rx_dbi=float(data.get("g_rx_dbi", 0.0)),
        l_rx_db=float(data.get("l_rx_db", 1.0)),
        sensitivity_dbm=float(data.get("sensitivity_dbm", -75.0)),
        fade_margin_db=float(data.get("fade_margin_db", 10.0)),
    )


def _parse_thresholds(data: dict) -> CoverageThresholds:
    return CoverageThresholds(
        rssi_target_dbm=float(data.get("rssi_target_dbm", -67.0)),
        som_aprobado_min_db=float(data.get("som_aprobado_min_db", 20.0)),
        som_riesgo_min_db=float(data.get("som_riesgo_min_db", 10.0)),
        excellent_min_dbm=float(data.get("excellent_min_dbm", -50.0)),
        good_min_dbm=float(data.get("good_min_dbm", -67.0)),
        regular_min_dbm=float(data.get("regular_min_dbm", -75.0)),
        weak_min_dbm=float(data.get("weak_min_dbm", -85.0)),
    )


def _parse_bands(data: list) -> list[FrequencyBand]:
    bands = []
    for item in data:
        bands.append(
            FrequencyBand(
                id=str(item["id"]),
                name=str(item["name"]),
                frequency_mhz=float(item["frequency_mhz"]),
            )
        )
    return bands


def _parse_materials(data: list) -> list[Material]:
    materials = []
    for item in data:
        attenuation = item.get("attenuation_db", {}) or {}
        materials.append(
            Material(
                id=str(item["id"]),
                name=str(item["name"]),
                description=str(item.get("description", "")),
                thickness_default_m=float(item.get("thickness_default_m", 0.1)),
                attenuation_db={str(k): float(v) for k, v in attenuation.items()},
            )
        )
    return materials
