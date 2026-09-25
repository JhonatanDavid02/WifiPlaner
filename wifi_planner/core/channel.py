"""Canales Wi-Fi (Fase 10): catálogo por familia de frecuencia.

FUENTE ÚNICA de verdad de canales: número lógico ↔ frecuencia central
física. La UI, el engine y la persistencia consultan este módulo; ninguna
capa duplica tablas de frecuencias (decisión BQ).

Conceptos (decisión BR):

- ``number``: canal como **identificador lógico** (36, 6, 149…).
- ``center_frequency_mhz``: **valor físico derivado** del catálogo. NO se
  persiste nunca: no puede haber inconsistencia canal↔frecuencia porque
  la frecuencia se deriva, no se almacena.
- La frecuencia central **NO entra en FSPL ni en el link budget**: la
  propagación sigue usando ``FrequencyBand.frequency_mhz`` (el canal no
  altera RSSI/SOM/SNR en Fase 10, decisión BR/BW).

La validación del triple (banda, canal, ancho) vive en
``validate_channel_config`` (decisión BT): un único punto de validación
para dominio, sesión, persistencia y engine.

Catálogos (numeración IEEE 802.11 estándar; familia decidida por la
misma frontera de frecuencia que los anchos de canal, decisión AY):

- 2.4 GHz: canales 1–13 a 5 MHz (2412 + 5·(n−1)) y el canal 14 (2484).
- 5 GHz: canales 20 MHz de UNII-1…UNII-4 (36…165).
- 6 GHz: canales 1, 5, 9, …, 233 con centro = 5950 + 5·n MHz
  (el centro del canal 37 = 6135 MHz coincide con la banda 6 por
  defecto del proyecto).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.band import FrequencyBand
# Misma frontera de familia que la regla de anchos AY (fuente única).
from core.radio import _24GHZ_FAMILY_MAX_MHZ, _6GHZ_MIN_MHZ, allowed_channel_widths_mhz

# Último canal de 20 MHz del catálogo (6 GHz, UNII-8).
MAX_CHANNEL_NUMBER = 233


@dataclass(frozen=True)
class WifiChannel:
    """Canal Wi-Fi: número lógico + frecuencia central física.

    Attributes:
        number: Número de canal (1..MAX_CHANNEL_NUMBER).
        center_frequency_mhz: Frecuencia central en MHz (> 0), derivada
            del catálogo; nunca se persiste (decisión BR).
    """

    number: int
    center_frequency_mhz: float

    def __post_init__(self) -> None:
        number = self.number
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError("WifiChannel.number debe ser un entero.")
        if not (1 <= number <= MAX_CHANNEL_NUMBER):
            raise ValueError(
                f"WifiChannel.number debe estar en [1, {MAX_CHANNEL_NUMBER}] "
                f"(got {number!r})."
            )
        center = self.center_frequency_mhz
        if isinstance(center, bool) or not isinstance(center, (int, float)):
            raise ValueError("WifiChannel.center_frequency_mhz debe ser un número.")
        center = float(center)
        if not math.isfinite(center) or center <= 0:
            raise ValueError("WifiChannel.center_frequency_mhz debe ser finita y > 0.")
        object.__setattr__(self, "number", number)
        object.__setattr__(self, "center_frequency_mhz", center)


# --- Catálogos por familia (fuente única; ver docstring) -----------------

# 2.4 GHz: 1–13 cada 5 MHz desde 2412; el canal 14 usa 2484.
_CHANNELS_24GHZ: tuple[WifiChannel, ...] = tuple(
    WifiChannel(number=n, center_frequency_mhz=2412.0 + 5.0 * (n - 1))
    for n in range(1, 14)
) + (WifiChannel(number=14, center_frequency_mhz=2484.0),)

# 5 GHz: bloques de 4 canales (20 MHz) con centros cada 20 MHz.
# 36–64: 5180+20k · 100–144: 5500+20k · 149–161: 5745+20k · 165: 5825.
_CHANNELS_5GHZ: tuple[WifiChannel, ...] = tuple(
    WifiChannel(number=n, center_frequency_mhz=5180.0 + 20.0 * ((n - 36) // 4))
    for n in (36, 40, 44, 48, 52, 56, 60, 64)
) + tuple(
    WifiChannel(number=n, center_frequency_mhz=5500.0 + 20.0 * ((n - 100) // 4))
    for n in (100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144)
) + tuple(
    WifiChannel(number=n, center_frequency_mhz=5745.0 + 20.0 * ((n - 149) // 4))
    for n in (149, 153, 157, 161)
) + (WifiChannel(number=165, center_frequency_mhz=5825.0),)

# 6 GHz: n = 1, 5, 9, …, 233 (pasos de 4); centro = 5950 + 5n MHz.
_CHANNELS_6GHZ: tuple[WifiChannel, ...] = tuple(
    WifiChannel(number=n, center_frequency_mhz=5950.0 + 5.0 * n)
    for n in range(1, MAX_CHANNEL_NUMBER + 1, 4)
)


def channels_for_frequency(frequency_mhz: float) -> tuple[WifiChannel, ...]:
    """Catálogo de canales de la familia de esa frecuencia.

    Misma frontera que los anchos de canal (decisión AY):

        f < 3000 MHz        → 2.4 GHz
        3000 ≤ f < 5925     → 5 GHz
        f ≥ 5925            → 6 GHz

    Args:
        frequency_mhz: Frecuencia de la banda en MHz.

    Returns:
        Tupla de canales ordenada por número.

    Raises:
        ValueError: si la frecuencia no es finita o no es > 0.
    """
    if isinstance(frequency_mhz, bool) or not isinstance(
        frequency_mhz, (int, float)
    ):
        raise ValueError("frequency_mhz debe ser un número.")
    frequency = float(frequency_mhz)
    if not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("frequency_mhz debe ser finita y > 0.")
    if frequency < _24GHZ_FAMILY_MAX_MHZ:
        return _CHANNELS_24GHZ
    if frequency < _6GHZ_MIN_MHZ:
        return _CHANNELS_5GHZ
    return _CHANNELS_6GHZ


def channel_numbers_for_frequency(frequency_mhz: float) -> tuple[int, ...]:
    """Números de canal de una familia (para selectores de la UI)."""
    return tuple(c.number for c in channels_for_frequency(frequency_mhz))


def channel_for_band(band: FrequencyBand, number: int) -> WifiChannel:
    """Busca un canal por número dentro de la familia de la banda.

    Raises:
        ValueError: si el número no es un entero válido o no pertenece
            al catálogo de la banda (canal inexistente o de otra banda).
    """
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError(f"Número de canal inválido: {number!r} (se espera un entero).")
    for channel in channels_for_frequency(band.frequency_mhz):
        if channel.number == number:
            return channel
    raise ValueError(
        f"Canal {number} no pertenece a la banda {band.name} "
        f"({band.frequency_mhz:g} MHz)."
    )


def default_channel(band: FrequencyBand) -> WifiChannel:
    """Canal de referencia de una banda.

    Para las bandas por defecto devuelve el canal cuya frecuencia central
    coincide con ``band.frequency_mhz`` (2437→6, 5180→36, 6135→37). Si no
    hay coincidencia exacta, el canal más cercano (empates → menor número).
    """
    catalog = channels_for_frequency(band.frequency_mhz)
    for channel in catalog:
        if channel.center_frequency_mhz == band.frequency_mhz:
            return channel
    return min(
        catalog,
        key=lambda c: (abs(c.center_frequency_mhz - band.frequency_mhz), c.number),
    )


def validate_channel_config(
    band: FrequencyBand, channel_number: int, width_mhz: int
) -> WifiChannel:
    """Valida el triple (banda, canal, ancho) en un único punto (decisión BT).

    Reglas:

    - El canal debe existir en el catálogo de la familia de la banda.
    - El ancho reutiliza la regla de familia de F7
      (``allowed_channel_widths_mhz``): 2.4 GHz → 20/40; 5/6 GHz →
      20/40/80/160. No se duplica validación.
    - El ancho NO entra en FSPL ni en el link budget (decisión AY/BW).

    Returns:
        El ``WifiChannel`` validado (para derivar la frecuencia central).

    Raises:
        ValueError: si el canal o el ancho no son válidos para la banda
        (tipos no enteros, valores fuera de catálogo).
    """
    channel = channel_for_band(band, channel_number)
    if isinstance(width_mhz, bool) or not isinstance(width_mhz, int):
        raise ValueError(
            f"Ancho de canal inválido: {width_mhz!r} (se espera un entero en MHz)."
        )
    allowed = allowed_channel_widths_mhz(band.frequency_mhz)
    if width_mhz not in allowed:
        raise ValueError(
            f"Ancho de canal {width_mhz} MHz no permitido en la banda "
            f"{band.name}; permitidos: {', '.join(str(w) for w in allowed)} MHz."
        )
    return channel


__all__ = [
    "MAX_CHANNEL_NUMBER",
    "WifiChannel",
    "channels_for_frequency",
    "channel_numbers_for_frequency",
    "channel_for_band",
    "default_channel",
    "validate_channel_config",
]
