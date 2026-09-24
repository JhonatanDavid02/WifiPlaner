"""Pérdida por obstáculos: trazado de paredes y suma de atenuaciones.

Fase 2: la geometria real AP → punto se traza contra las paredes del
plano y cada cruce aporta la atenuación de su material (con modelo de
espesor). El resultado estructurado conserva el detalle por pared.

Flujo:

    source/target
        → intersección con cada pared (engine.intersection)
        → atenuación por material y espesor (wall_attenuation_db)
        → ObstacleTraceResult (orden reproducible + total)
        → ObstacleLoss (contrato del link budget)

Fórmulas:

    L_total = Σ L_wall_i
    L_wall  = L_ref(banda) * (espesor_actual / espesor_referencia)

El escalado lineal de espesor es una aproximación de ingeniería para el
modelo predictivo V1, NO una simulación electromagnética.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from core.geometry import Point2D, Segment2D
from core.material import Material
from core.result import ObstacleLoss
from core.wall import Wall
from engine.intersection import crossing_distance_from_start, segment_crossing_parameters


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


@dataclass(frozen=True)
class WallCrossing:
    """Cruce de una pared en un trazado AP → punto.

    Attributes:
        wall: Pared atravesada (referencia al dominio).
        material_id: Id del material de la pared.
        band_id: Id de la banda evaluada.
        loss_db: Atenuación de esta pared en dB (con espesor aplicado).
        distance_from_source_m: Distancia desde el origen hasta el cruce.
        order: Índice 0-based en el orden del trayecto (reproducible).
    """

    wall: Wall
    material_id: str
    band_id: str
    loss_db: float
    distance_from_source_m: float
    order: int


@dataclass(frozen=True)
class ObstacleTraceResult:
    """Resultado estructurado del trazado de paredes.

    Attributes:
        source: Origen del trayecto (AP) en metros.
        target: Destino del trayecto (punto) en metros.
        band_id: Id de la banda evaluada.
        walls_crossed: Paredes atravesadas, ordenadas por distancia
            desde el origen (empate roto por wall.id para reproducibilidad).
        attenuation_db: Pérdida total en dB (suma de walls_crossed).
    """

    source: Point2D
    target: Point2D
    band_id: str
    walls_crossed: tuple[WallCrossing, ...]
    attenuation_db: float

    @property
    def wall_ids(self) -> tuple[str, ...]:
        return tuple(c.wall.id for c in self.walls_crossed)

    @property
    def crossings_count(self) -> int:
        return len(self.walls_crossed)


def wall_attenuation_db(wall: Wall, band_id: str) -> float:
    """Atenuación de una pared para una banda, con modelo de espesor.

    Modelo (aproximación lineal de ingeniería, V1):

        L = L_referencia(banda) * (espesor_actual / espesor_referencia)

    - ``espesor_actual``: ``wall.thickness_m`` o, si es None, el
      espesor de referencia del material.
    - Si el espesor actual == espesor de referencia => L = L_referencia.
    - Paredes con ``blocks_signal=False`` aportan 0 dB.

    Args:
        wall: Pared del dominio.
        band_id: Id de la banda (ej. "band_2_4").

    Returns:
        Atenuación en dB (no redondeada; la suma total se redondea).

    Raises:
        MaterialAttenuationError: si el material no tiene datos para la
            banda (p. ej. 6 GHz en el catálogo V1). No se inventan valores.
        ValueError: si espesor de referencia o espesor actual no son > 0.
    """
    if not wall.blocks_signal:
        return 0.0

    material = wall.material
    reference_loss = material.attenuation_for(band_id)

    if material.thickness_default_m <= 0:
        raise ValueError(
            f"Material '{material.id}': thickness_default_m debe ser > 0 "
            f"(got {material.thickness_default_m})."
        )

    actual_thickness = wall.effective_thickness
    if actual_thickness <= 0:
        raise ValueError(
            f"Wall '{wall.id}': thickness_m debe ser > 0 "
            f"(got {actual_thickness})."
        )

    return reference_loss * (actual_thickness / material.thickness_default_m)


def obstacle_loss_for_crossings(
    materials: Sequence[Material],
    band_id: str,
    wall_ids: Sequence[str] | None = None,
) -> ObstacleLoss:
    """Suma la atenuación de referencia de cada material (sin espesor).

    API de Fase 1 mantenida: usa la atenuación de referencia del
    material (sin escalar por espesor). Para paredes reales con
    espesor usar ``trace_walls``.

    Args:
        materials: Materiales atravesados en orden (puede estar vacío).
        band_id: Id de la banda (ej. "band_2_4").
        wall_ids: Ids de paredes correspondientes (opcional, para detalle).

    Returns:
        ObstacleLoss con total en dB, cantidad de crossings y desglose.

    Raises:
        MaterialAttenuationError: si un material no tiene atenuación
            configurada para la banda.
        ValueError: si wall_ids y materials no tienen la misma longitud.
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


def trace_walls(
    source: Point2D,
    target: Point2D,
    walls: Iterable[Wall],
    band_id: str,
) -> ObstacleTraceResult:
    """Trazado AP → punto: qué paredes se atraviesan, en qué orden y pérdida.

    Determinista: las paredes se evalúan contra el trayecto con la
    convención de cruce interior estricto (extremos no cuentan) y se
    ordenan por distancia desde el origen. Empates de distancia se
    rompen por ``wall.id`` para reproducibilidad total.

    Args:
        source: Posición del AP en metros.
        target: Punto de evaluación en metros.
        walls: Paredes candidatas del plano (plano del piso activo).
        band_id: Id de la banda (ej. "band_2_4"). Para 6 GHz, si el
            material no tiene datos, se propaga MaterialAttenuationError.

    Returns:
        ObstacleTraceResult con detalle por pared y atenuación total.

    Raises:
        MaterialAttenuationError: banda sin datos en algún material.
        ValueError: espesor inválido en alguna pared cruzada.
    """
    path = Segment2D(source, target)
    # (distancia, wall_id, wall, loss_db) — la atenuación se calcula una sola vez.
    candidates: list[tuple[float, str, Wall, float]] = []

    for wall in walls:
        if not wall.blocks_signal:
            continue
        if segment_crossing_parameters(path, wall.segment) is None:
            continue
        distance = crossing_distance_from_start(path, wall.segment)
        if distance is None:
            continue
        loss = wall_attenuation_db(wall, band_id)
        candidates.append((distance, wall.id, wall, loss))

    # Orden reproducible: distancia, luego id de pared.
    candidates.sort(key=lambda item: (item[0], item[1]))

    crossings: list[WallCrossing] = []
    total = 0.0
    for order, (distance, _wall_id, wall, loss) in enumerate(candidates):
        total += loss
        crossings.append(
            WallCrossing(
                wall=wall,
                material_id=wall.material.id,
                band_id=band_id,
                loss_db=loss,
                distance_from_source_m=round(distance, 6),
                order=order,
            )
        )

    return ObstacleTraceResult(
        source=source,
        target=target,
        band_id=band_id,
        walls_crossed=tuple(crossings),
        attenuation_db=round(total, 2),
    )


def trace_to_obstacle_loss(trace: ObstacleTraceResult) -> ObstacleLoss:
    """Convierte un trazado al contrato ObstacleLoss del link budget."""
    detail = tuple(
        CrossingLoss(
            material_id=c.material_id,
            band_id=c.band_id,
            loss_db=c.loss_db,
            wall_id=c.wall.id,
        )
        for c in trace.walls_crossed
    )
    return ObstacleLoss(
        total_db=trace.attenuation_db,
        crossings=trace.crossings_count,
        detail=detail,
    )
