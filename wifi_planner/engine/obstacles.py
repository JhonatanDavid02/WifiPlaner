"""Pérdida por obstáculos (materiales atravesados).

Fase 1: la estructura está preparada pero el cálculo real de
intersección rayo ↔ pared llega en Fase 2. Mientras tanto:

- ``obstacle_loss_for_crossings`` ya implementa la suma de atenuaciones
  por material y banda (testeable desde Fase 1).
- ``evaluate_link`` recibe la pérdida como parámetro opcional.

Fórmula conceptual (Fase 2 conectará la geometría):

    L_obstacles = Σ atenuación(material_i, banda)
"""

from __future__ import annotations

from dataclasses import dataclass

from core.material import Material
from core.result import ObstacleLoss


@dataclass(frozen=True)
class CrossingLoss:
    """Atenuación de un único atravesamiento de material.

    Attributes:
        material_id: Id del material atravesado.
        band_id: Id de la banda evaluada.
        loss_db: Atenuación en dB.
        wall_id: Id de la pared asociada (si aplica).
    """

    material_id: str
    band_id: str
    loss_db: float
    wall_id: str | None = None


def obstacle_loss_for_crossings(
    materials: list[Material],
    band_id: str,
    wall_ids: list[str] | None = None,
) -> ObstacleLoss:
    """Suma la atenuación de cada material atravesado para una banda.

    Args:
        materials: Materiales atravesados en orden (puede estar vacío).
        band_id: Id de la banda (ej. "band_2_4").
        wall_ids: Ids de paredes correspondientes (opcional, para detalle).

    Returns:
        ObstacleLoss con total en dB, cantidad de crossings y desglose.

    Raises:
        MaterialAttenuationError: si un material no tiene atenuación
            configurada para la banda.
    """
    if not materials:
        return ObstacleLoss(total_db=0.0, crossings=0)

    if wall_ids is not None and len(wall_ids) != len(materials):
        raise ValueError("wall_ids y materials deben tener la misma longitud.")

    detail = []
    total = 0.0

    for index, material in enumerate(materials):
        loss = material.attenuation_for(band_id)
        wall_id = wall_ids[index] if wall_ids is not None else None
        total += loss
        detail.append(
            CrossingLoss(
                material_id=material.id,
                band_id=band_id,
                loss_db=loss,
                wall_id=wall_id,
            )
        )

    return ObstacleLoss(
        total_db=round(total, 2),
        crossings=len(materials),
        detail=tuple(detail),
    )
