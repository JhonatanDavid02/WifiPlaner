"""Materiales y su atenuación por banda.

IMPORTANTE: Los valores iniciales son ESTIMACIONES de referencia
configurables, NO verdades físicas universales. Deben vivir centralizados
aquí o en config/, nunca dispersos por el código.

Atenuación de referencia por material (estimada, configurable):

| Material            | 2.4 GHz | 5 GHz |
|---------------------|--------:|------:|
| drywall             |    3 dB |  4 dB |
| wood                |    3 dB |  4 dB |
| glass               |    3 dB |  4 dB |
| brick               |    6 dB |  8 dB |
| concrete            |   12 dB | 15 dB |
| reinforced_concrete |   15 dB | 20 dB |
| metal               |   25 dB | 30 dB |

La atenuación se aplica por cada atravesamiento del material con su
espesor de referencia. La atenuación para 6 GHz se añadirá cuando se
configure; hasta entonces se lanza MaterialAttenuationError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


class MaterialAttenuationError(KeyError):
    """La banda solicitada no tiene atenuación configurada para el material."""


@dataclass(frozen=True)
class Material:
    """Material constructivo con atenuación por banda.

    Attributes:
        id: Identificador estable (ej. "drywall").
        name: Nombre legible.
        description: Descripción opcional.
        thickness_default_m: Espesor de referencia en metros.
        attenuation_db: {band_id: atenuación en dB} para el espesor de referencia.
        metadata: Datos adicionales libres.
    """

    id: str
    name: str
    description: str = ""
    thickness_default_m: float = 0.1
    attenuation_db: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def attenuation_for(self, band_id: str) -> float:
        """Devuelve la atenuación en dB para la banda indicada.

        Raises:
            MaterialAttenuationError: si la banda no está configurada.
        """
        try:
            return float(self.attenuation_db[band_id])
        except KeyError:
            raise MaterialAttenuationError(
                f"Material '{self.id}' no tiene atenuación configurada "
                f"para la banda '{band_id}'."
            ) from None

    def has_band(self, band_id: str) -> bool:
        return band_id in self.attenuation_db


def default_materials() -> tuple[Material, ...]:
    """Catálogo inicial de materiales (estimaciones de referencia)."""
    return (
        Material(
            id="drywall",
            name="Muro de yeso",
            description="Muro de yeso (pladur). Estimación de referencia.",
            thickness_default_m=0.012,
            attenuation_db={"band_2_4": 3.0, "band_5": 4.0},
        ),
        Material(
            id="wood",
            name="Madera",
            description="Madera maciza o laminada. Estimación de referencia.",
            thickness_default_m=0.04,
            attenuation_db={"band_2_4": 3.0, "band_5": 4.0},
        ),
        Material(
            id="glass",
            name="Vidrio",
            description="Vidrio estándar de ventanal. Estimación de referencia.",
            thickness_default_m=0.008,
            attenuation_db={"band_2_4": 3.0, "band_5": 4.0},
        ),
        Material(
            id="brick",
            name="Ladrillo",
            description="Mampostería de ladrillo. Estimación de referencia.",
            thickness_default_m=0.12,
            attenuation_db={"band_2_4": 6.0, "band_5": 8.0},
        ),
        Material(
            id="concrete",
            name="Concreto",
            description="Concreto simple. Estimación de referencia.",
            thickness_default_m=0.15,
            attenuation_db={"band_2_4": 12.0, "band_5": 15.0},
        ),
        Material(
            id="reinforced_concrete",
            name="Concreto reforzado",
            description="Concreto con acero de refuerzo. Estimación de referencia.",
            thickness_default_m=0.20,
            attenuation_db={"band_2_4": 15.0, "band_5": 20.0},
        ),
        Material(
            id="metal",
            name="Metal",
            description="Panel o estructura metálica. Estimación de referencia.",
            thickness_default_m=0.005,
            attenuation_db={"band_2_4": 25.0, "band_5": 30.0},
        ),
    )
