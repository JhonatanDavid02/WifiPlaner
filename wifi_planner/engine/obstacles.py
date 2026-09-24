"""Pérdida por obstáculos: trazado de paredes y suma de atenuaciones.

Fase 2: la geometria real AP → punto se traza contra las paredes del
plano y cada cruce aporta la atenuación de su material (con modelo de
espesor). El resultado estructurado conserva el detalle por pared.

Fase 8: si un cruce cae dentro de la unión de los openings de la
pared, ese cruce aporta el override del hueco (0 dB si no hay datos)
**en lugar de** la atenuación del material (decisión BG: reemplazo,
nunca suma; ver ``group_openings_by_wall``).

Flujo:

    source/target
        → intersección con cada pared (engine.intersection)
        → ¿cruce dentro de un opening? → pérdida del hueco (o 0 dB)
          ↳ si no: atenuación por material y espesor (wall_attenuation_db)
        → ObstacleTraceResult (orden reproducible + total)
        → ObstacleLoss (contrato del link budget)

Fórmulas:

    L_total = Σ L_cruce_i
    L_cruce = L_wall(banda, espesor)  si es sección sólida
            = override(banda) o 0 dB   si cae en un opening

El escalado lineal de espesor es una aproximación de ingeniería para el
modelo predictivo V1, NO una simulación electromagnética.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from core.geometry import EPSILON_GEOMETRY, Point2D, Segment2D
from core.material import Material
from core.result import ObstacleLoss
from core.wall import Opening, Wall, group_openings_by_wall
from engine.intersection import segment_crossing_parameters


@dataclass(frozen=True)
class CrossingLoss:
    """Atenuación de un único atravesamiento de material.

    Attributes:
        material_id: Id del material atravesado.
        band_id: Id de la banda evaluada.
        loss_db: Atenuación en dB.
        wall_id: Id de la pared asociada (si aplica).
        opening_id: Id del opening cubriendo el cruce (Fase 8, si
            aplica); la pérdida es entonces un reemplazo (0 dB o el
            override del hueco), no la del material.
    """

    material_id: str
    band_id: str
    loss_db: float
    wall_id: str | None = None
    opening_id: str | None = None


@dataclass(frozen=True)
class WallCrossing:
    """Cruce de una pared en un trazado AP → punto.

    Attributes:
        wall: Pared atravesada (referencia al dominio).
        material_id: Id del material de la pared.
        band_id: Id de la banda evaluada.
        loss_db: Atenuación de este cruce en dB (material con espesor,
            o el valor del opening si el cruce cae en un hueco).
        distance_from_source_m: Distancia desde el origen hasta el cruce.
        order: Índice 0-based en el orden del trayecto (reproducible).
        opening_id: Id del opening que cubre el cruce, o None si es
            sección sólida (Fase 8).
    """

    wall: Wall
    material_id: str
    band_id: str
    loss_db: float
    distance_from_source_m: float
    order: int
    opening_id: str | None = None


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


def _opening_at_distance(
    openings: Sequence[Opening], distance_m: float
) -> Opening | None:
    """Opening (ya en orden canónico) que cubre ``distance_m``, o None.

    Intervalo cerrado con tolerancia geométrica: los extremos del hueco
    pertenecen al hueco (decisión BG). ``openings`` debe venir ordenada
    por ``(start_offset_m, id)`` — ``group_openings_by_wall`` lo garantiza
    sin importar el orden de inserción.
    """
    for opening in openings:
        if (
            opening.start_offset_m - EPSILON_GEOMETRY
            <= distance_m
            <= opening.end_offset_m + EPSILON_GEOMETRY
        ):
            return opening
    return None


def trace_walls(
    source: Point2D,
    target: Point2D,
    walls: Iterable[Wall],
    band_id: str,
    openings: Iterable[Opening] = (),
) -> ObstacleTraceResult:
    """Trazado AP → punto: qué paredes se atraviesan, en qué orden y pérdida.

    Determinista: las paredes se evalúan contra el trayecto con la
    convención de cruce interior estricto (extremos no cuentan) y se
    ordenan por distancia desde el origen. Empates de distancia se
    rompen por ``wall.id`` para reproducibilidad total.

    Fase 8: si el cruce cae dentro de un opening de la pared (unión de
    los huecos, intervalo cerrado con ε), la pérdida de ese cruce es el
    override por banda del hueco — 0 dB si no hay datos — y **sustituye**
    a la del material (decisión BG). Un cruce en hueco no consulta el
    catálogo de materiales: 6 GHz atraviesa huecos con 0 dB, y los
    cruces sólidos siguen lanzando ``MaterialAttenuationError`` como
    antes. Sin ``openings`` el resultado es idéntico al de Fase 2–7.

    Args:
        source: Posición del AP en metros.
        target: Punto de evaluación en metros.
        walls: Paredes candidatas del plano (plano del piso activo).
        band_id: Id de la banda (ej. "band_2_4"). Para 6 GHz, si el
            material no tiene datos, se propaga MaterialAttenuationError.
        openings: Openings del plano (Fase 8). Solo se usan para las
            paredes cruzadas; por defecto ninguno.

    Returns:
        ObstacleTraceResult con detalle por cruce (``opening_id`` si el
        cruce cayó en un hueco) y atenuación total.

    Raises:
        MaterialAttenuationError: banda sin datos en algún material de
            una sección sólida cruzada.
        ValueError: espesor inválido en alguna pared cruzada sólida.
    """
    path = Segment2D(source, target)
    grouped = group_openings_by_wall(openings)
    # (distancia, wall_id, wall, loss_db, opening_id) — cada pérdida se
    # calcula una sola vez por pared cruzada.
    candidates: list[tuple[float, str, Wall, float, str | None]] = []

    for wall in walls:
        if not wall.blocks_signal:
            continue
        params = segment_crossing_parameters(path, wall.segment)
        if params is None:
            continue
        t, u = params
        distance = t * path.length

        opening = None
        wall_openings = grouped.get(wall.id)
        if wall_openings:
            crossing_distance_m = u * wall.segment.length
            opening = _opening_at_distance(wall_openings, crossing_distance_m)

        if opening is not None:
            # Reemplazo (BG): nunca material + opening.
            loss = float(opening.attenuation_override_db.get(band_id, 0.0))
            opening_id: str | None = opening.id
        else:
            loss = wall_attenuation_db(wall, band_id)
            opening_id = None
        candidates.append((distance, wall.id, wall, loss, opening_id))

    # Orden reproducible: distancia, luego id de pared.
    candidates.sort(key=lambda item: (item[0], item[1]))

    crossings: list[WallCrossing] = []
    total = 0.0
    for order, (distance, _wall_id, wall, loss, opening_id) in enumerate(candidates):
        total += loss
        crossings.append(
            WallCrossing(
                wall=wall,
                material_id=wall.material.id,
                band_id=band_id,
                loss_db=loss,
                distance_from_source_m=round(distance, 6),
                order=order,
                opening_id=opening_id,
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
            opening_id=c.opening_id,
        )
        for c in trace.walls_crossed
    )
    return ObstacleLoss(
        total_db=trace.attenuation_db,
        crossings=trace.crossings_count,
        detail=detail,
    )
