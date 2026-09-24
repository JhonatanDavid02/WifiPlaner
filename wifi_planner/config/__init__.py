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
    # Los defaults provienen de la instancia por defecto (fuente única
    # en core/radio.py): no se repiten literales aquí (Paso 20 de F7).
    defaults = RadioConfiguration()
    return RadioConfiguration(
        p_tx_dbm=float(data.get("p_tx_dbm", defaults.p_tx_dbm)),
        g_tx_dbi=float(data.get("g_tx_dbi", defaults.g_tx_dbi)),
        l_tx_db=float(data.get("l_tx_db", defaults.l_tx_db)),
        g_rx_dbi=float(data.get("g_rx_dbi", defaults.g_rx_dbi)),
        l_rx_db=float(data.get("l_rx_db", defaults.l_rx_db)),
        sensitivity_dbm=float(data.get("sensitivity_dbm", defaults.sensitivity_dbm)),
        fade_margin_db=float(data.get("fade_margin_db", defaults.fade_margin_db)),
        noise_floor_dbm=float(data.get("noise_floor_dbm", defaults.noise_floor_dbm)),
        channel_width_mhz=int(data.get("channel_width_mhz", defaults.channel_width_mhz)),
        wifi_standard=str(data.get("wifi_standard", defaults.wifi_standard)),
    )


def _parse_thresholds(data: dict) -> CoverageThresholds:
    # Mismo criterio: defaults desde la instancia por defecto (core/).
    defaults = CoverageThresholds()
    return CoverageThresholds(
        rssi_target_dbm=float(data.get("rssi_target_dbm", defaults.rssi_target_dbm)),
        som_aprobado_min_db=float(
            data.get("som_aprobado_min_db", defaults.som_aprobado_min_db)
        ),
        som_riesgo_min_db=float(
            data.get("som_riesgo_min_db", defaults.som_riesgo_min_db)
        ),
        excellent_min_dbm=float(
            data.get("excellent_min_dbm", defaults.excellent_min_dbm)
        ),
        good_min_dbm=float(data.get("good_min_dbm", defaults.good_min_dbm)),
        regular_min_dbm=float(data.get("regular_min_dbm", defaults.regular_min_dbm)),
        weak_min_dbm=float(data.get("weak_min_dbm", defaults.weak_min_dbm)),
        snr_target_db=float(data.get("snr_target_db", defaults.snr_target_db)),
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
