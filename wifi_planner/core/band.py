"""Banda de frecuencia.

La arquitectura contempla 2.4 GHz, 5 GHz y 6 GHz desde V1.
El motor recibe la banda como parámetro; no asume un conjunto fijo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrequencyBand:
    """Banda de frecuencia operativa.

    Attributes:
        id: Identificador estable (ej. "band_2_4").
        name: Nombre legible (ej. "2.4 GHz").
        frequency_mhz: Frecuencia de operación en MHz.
    """

    id: str
    name: str
    frequency_mhz: float

    def __post_init__(self) -> None:
        if self.frequency_mhz <= 0:
            raise ValueError("FrequencyBand.frequency_mhz debe ser > 0.")

    @property
    def frequency_hz(self) -> float:
        return self.frequency_mhz * 1_000_000.0


# Bandas por defecto del proyecto. 6 GHz queda registrada desde V1;
# su simulación completa es un objetivo posterior.
DEFAULT_BANDS: tuple[FrequencyBand, ...] = (
    FrequencyBand(id="band_2_4", name="2.4 GHz", frequency_mhz=2437.0),
    FrequencyBand(id="band_5", name="5 GHz", frequency_mhz=5180.0),
    FrequencyBand(id="band_6", name="6 GHz", frequency_mhz=6135.0),
)
