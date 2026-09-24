"""Configuración de radio de un enlace (AP o dispositivo).

Todas las unidades son explícitas:
- potencia: dBm
- ganancia: dBi
- pérdidas: dB
- sensibilidad: dBm
- piso de ruido: dBm
- fade margin: dB
- ancho de canal: MHz

Fase 7: se añaden ``noise_floor_dbm`` (base del SNR),
``channel_width_mhz`` (propiedad de la radio; NO entra en FSPL) y
``wifi_standard`` (metadato/contexto; sin efecto RF en F7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Piso de ruido por defecto del receptor (dBm). NO es una constante
# universal: es el valor por defecto del modelo y es configurable por
# radio (decisión AU en docs/decisions.md).
DEFAULT_NOISE_FLOOR_DBM = -95.0

# Rango aceptado para el piso de ruido (dBm):
# - mínimo -200: muy por debajo del ruido térmico de cualquier ancho de
#   canal realista (~-101 dBm a 20 MHz); por debajo no tiene sentido.
# - máximo 0: ruido más fuerte que cualquier señal razonable (dBm > 0).
NOISE_FLOOR_MIN_DBM = -200.0
NOISE_FLOOR_MAX_DBM = 0.0

# Anchos de canal soportados como dato (MHz). Solo validación de
# compatibilidad con la banda: NO se usa en FSPL ni en el alcance.
CHANNEL_WIDTHS_MHZ: tuple[int, ...] = (20, 40, 80, 160)

# Estándares Wi-Fi representables en F7 (configuración/metadato).
WIFI_STANDARDS: tuple[str, ...] = ("802.11n", "802.11ac", "802.11ax", "802.11be")

WIFI_LABEL_BY_STANDARD: dict[str, str] = {
    "802.11n": "Wi-Fi 4",
    "802.11ac": "Wi-Fi 5",
    "802.11ax": "Wi-Fi 6",
    "802.11be": "Wi-Fi 7",
}

# Frontera convencional entre la familia 2.4 GHz y 5/6 GHz (MHz).
# No es un motor regulatorio: solo decide qué anchos de canal admite
# cada familia (decisión AY).
_24GHZ_FAMILY_MAX_MHZ = 3000.0

# Inicio de la banda 6 GHz (Wi-Fi 6E: 5925–7125 MHz).
_6GHZ_MIN_MHZ = 5925.0


def allowed_channel_widths_mhz(frequency_mhz: float) -> tuple[int, ...]:
    """Anchos de canal compatibles con la familia de frecuencia.

    Regla simple por familia (F7, decisión AY):

        f < 3000 MHz  (2.4 GHz) → 20, 40 MHz
        en otro caso  (5/6 GHz) → 20, 40, 80, 160 MHz

    Args:
        frequency_mhz: Frecuencia de la banda en MHz (> 0).

    Returns:
        Tupla de anchos permitidos en MHz (orden creciente).
    """
    if frequency_mhz < _24GHZ_FAMILY_MAX_MHZ:
        return (20, 40)
    return CHANNEL_WIDTHS_MHZ


def wifi_generation(standard: str, frequency_mhz: float) -> str:
    """Etiqueta de generación Wi-Fi para un estándar + frecuencia.

    Distingue conceptualmente (sin efecto RF):

        802.11n   → Wi-Fi 4
        802.11ac  → Wi-Fi 5
        802.11ax  → Wi-Fi 6   (y Wi-Fi 6E si la frecuencia es 6 GHz)
        802.11be  → Wi-Fi 7

    Args:
        standard: Estándar IEEE (clave de ``WIFI_STANDARDS``).
        frequency_mhz: Frecuencia operativa en MHz (para Wi-Fi 6E).

    Returns:
        Etiqueta legible ("Wi-Fi 4", "Wi-Fi 6E", ...).
    """
    label = WIFI_LABEL_BY_STANDARD.get(standard, standard)
    if standard == "802.11ax" and frequency_mhz >= _6GHZ_MIN_MHZ:
        return "Wi-Fi 6E"
    return label


@dataclass(frozen=True)
class RadioConfiguration:
    """Parámetros de radio de un enlace.

    Attributes:
        p_tx_dbm: Potencia de transmisión en dBm.
        g_tx_dbi: Ganancia de la antena TX en dBi.
        l_tx_db: Pérdidas TX en dB.
        g_rx_dbi: Ganancia de la antena RX en dBi.
        l_rx_db: Pérdidas RX en dB.
        sensitivity_dbm: Sensibilidad del receptor en dBm.
        fade_margin_db: Margen de desvanecimiento (Lm) en dB.
            Por defecto 10 dB (decisión B). Usar 0 para reproducir
            las versiones legacy v3/v4 que omitían Lm.
        noise_floor_dbm: Piso de ruido del receptor en dBm (F7).
            Por defecto -95 dBm; configurable por radio (decisión AU).
            Rango: [-200, 0] dBm.
        channel_width_mhz: Ancho de canal en MHz (F7). Uno de
            20/40/80/160. NO interviene en FSPL ni en el alcance
            (decisión AY); solo se valida contra la banda al simular.
        wifi_standard: Estándar Wi-Fi (F7): metadato/contexto sin
            efecto RF en F7 (decisión AX). Uno de WIFI_STANDARDS.
    """

    p_tx_dbm: float = 20.0
    g_tx_dbi: float = 3.0
    l_tx_db: float = 1.0
    g_rx_dbi: float = 0.0
    l_rx_db: float = 1.0
    sensitivity_dbm: float = -75.0
    fade_margin_db: float = 10.0
    noise_floor_dbm: float = DEFAULT_NOISE_FLOOR_DBM
    channel_width_mhz: int = 20
    wifi_standard: str = "802.11ax"

    def __post_init__(self) -> None:
        if self.fade_margin_db < 0:
            raise ValueError("RadioConfiguration.fade_margin_db no puede ser negativo.")

        noise = self.noise_floor_dbm
        if isinstance(noise, bool) or not isinstance(noise, (int, float)):
            raise ValueError(
                "RadioConfiguration.noise_floor_dbm debe ser un número (dBm)."
            )
        noise = float(noise)
        if not math.isfinite(noise):
            raise ValueError(
                "RadioConfiguration.noise_floor_dbm debe ser finito (dBm)."
            )
        if not (NOISE_FLOOR_MIN_DBM <= noise <= NOISE_FLOOR_MAX_DBM):
            raise ValueError(
                "RadioConfiguration.noise_floor_dbm debe estar en "
                f"[{NOISE_FLOOR_MIN_DBM:g}, {NOISE_FLOOR_MAX_DBM:g}] dBm "
                f"(got {noise:g})."
            )
        object.__setattr__(self, "noise_floor_dbm", noise)

        width = self.channel_width_mhz
        if isinstance(width, bool) or not isinstance(width, (int, float)):
            raise ValueError(
                "RadioConfiguration.channel_width_mhz debe ser un entero (MHz)."
            )
        if width not in CHANNEL_WIDTHS_MHZ:
            raise ValueError(
                "RadioConfiguration.channel_width_mhz debe ser uno de "
                f"{CHANNEL_WIDTHS_MHZ} MHz (got {width!r})."
            )
        object.__setattr__(self, "channel_width_mhz", int(width))

        if self.wifi_standard not in WIFI_STANDARDS:
            raise ValueError(
                "RadioConfiguration.wifi_standard no soportado: "
                f"{self.wifi_standard!r} (permitidos: {', '.join(WIFI_STANDARDS)})."
            )
