"""Propagación en espacio libre (FSPL) y longitud de onda.

Fórmulas canónicas:

    λ = c / f
    FSPL(dB) = 20·log10(d[m]) + 20·log10(f[MHz]) - 27.55

Unidades explícitas:
- distancia: metros
- frecuencia de entrada: Hz (wavelength) o MHz (FSPL), nunca ambiguo
- salida: metros (λ) o dB (FSPL)
"""

from __future__ import annotations

import math

# Velocidad de la luz en el vacío (aproximación de ingeniería usada
# en el proyecto legacy y en el DOCX): 3×10^8 m/s.
SPEED_OF_LIGHT_M_S = 300_000_000.0

# Constante del modelo FSPL de la ITU/fórmula abreviada (dB).
_FSPL_CONSTANT_DB = -27.55


def wavelength_m(frequency_hz: float) -> float:
    """Longitud de onda en metros.

    Args:
        frequency_hz: Frecuencia en Hz.

    Returns:
        Longitud de onda en metros.

    Raises:
        ValueError: si frequency_hz <= 0.
    """
    if frequency_hz <= 0:
        raise ValueError("La frecuencia debe ser mayor que 0 Hz.")
    return SPEED_OF_LIGHT_M_S / frequency_hz


def path_loss_fspl_db(distance_m: float, frequency_mhz: float) -> float:
    """Pérdida en espacio libre (Free Space Path Loss).

    FSPL(dB) = 20*log10(d) + 20*log10(f_MHz) - 27.55

    Args:
        distance_m: Distancia en metros (> 0).
        frequency_mhz: Frecuencia en MHz (> 0).

    Returns:
        Pérdida en dB, redondeada a 2 decimales (compatibilidad con legacy).

    Raises:
        ValueError: si distancia o frecuencia no son positivas.
    """
    if distance_m <= 0:
        raise ValueError("La distancia debe ser mayor que 0 metros.")
    if frequency_mhz <= 0:
        raise ValueError("La frecuencia debe ser mayor que 0 MHz.")

    return round(
        20.0 * math.log10(distance_m)
        + 20.0 * math.log10(frequency_mhz)
        + _FSPL_CONSTANT_DB,
        2,
    )


# Alias canónico usado por el dominio del proyecto.
fspl_db = path_loss_fspl_db
