"""Pérdida por obstáculos: trazado de paredes y de mobiliario.

Fase 2: la geometria real AP → punto se traza contra las paredes del
plano y cada cruce aporta la atenuación de su material (con modelo de
espesor). El resultado estructurado conserva el detalle por pared.

Fase 8: si un cruce cae dentro de la unión de los openings de la
pared, ese cruce aporta el override del hueco (0 dB si no hay datos)
**en lugar de** la atenuación del material (decisión BG: reemplazo,
nunca suma; ver ``group_openings_by_wall``).

Fase 9: los obstáculos de mobiliario (``core.obstacle.Obstacle``,
footprints rectangulares) se trazan con la MISMA primitiva de
intersección que las paredes (``segment_crossing_parameters`` contra
los cuatro bordes del ``Rect``). Un obstáculo cruzado aporta su
pérdida **independiente** — nunca se suma con la pared que lo contiene
ni con un opening (decisión BN: sin doble atenuación por construcción).

Flujo:

    source/target
        → intersección con cada pared (engine.intersection)
        → ¿cruce dentro de un opening? → pérdida del hueco (o 0 dB)
          ↳ si no: atenuación por material y espesor (wall_attenuation_db)
        → intersección con los bordes de cada obstáculo
          ↳ ≥1 cruce de borde ⇒ un solo atravesamiento (obstacle_attenuation_db)
        → orden canónico (distancia, tipo, id) → suma reproducible
        → ObstacleTraceResult → ObstacleLoss (contrato del link budget)

Fórmulas:

    L_total = Σ L_cruce_i  +  Σ L_obstáculo_j   (en orden canónico)
    L_cruce = L_wall(banda, espesor)  si es sección sólida
            = override(banda) o 0 dB   si cae en un opening
    L_obstáculo = override(banda)      si el obstáculo lo define
                = L_material(banda)    si no (referencia, sin espesor)

El escalado lineal de espesor es una aproximación de ingeniería para el
modelo predictivo V1, NO una simulación electromagnética. Los obstáculos
usan la atenuación de referencia del material sin escalar (el footprint
no es un espesor de pared; decisión BM).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from core.geometry import EPSILON_GEOMETRY, Point2D, Rect, Segment2D
from core.material import Material
from core.obstacle import Obstacle
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
        obstacle_id: Id del obstáculo de mobiliario asociado (Fase 9,
            si aplica); la pérdida es la del objeto, independiente de
            paredes y openings.
    """

    material_id: str
    band_id: str
    loss_db: float
    wall_id: str | None = None
    opening_id: str | None = None
    obstacle_id: str | None = None


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
        order: Índice 0-based dentro de las paredes del trayecto
            (reproducible; con obstáculos el orden fusionado vive en la
            suma de ``attenuation_db``, decisión BN).
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
class ObstacleCrossing:
    """Cruce de un obstáculo de mobiliario en un trazado AP → punto.

    Attributes:
        obstacle: Obstáculo atravesado (referencia al dominio).
        material_id: Id del material del obstáculo.
        band_id: Id de la banda evaluada.
        loss_db: Atenuación de este cruce en dB (override del objeto o
            atenuación de referencia del material — decisión BM).
        distance_from_source_m: Distancia desde el origen hasta la
            primera entrada en el footprint.
        order: Índice 0-based dentro de los obstáculos del trayecto.
    """

    obstacle: Obstacle
    material_id: str
    band_id: str
    loss_db: float
    distance_from_source_m: float
    order: int


@dataclass(frozen=True)
class ObstacleTraceResult:
    """Resultado estructurado del trazado AP → punto.

    Attributes:
        source: Origen del trayecto (AP) en metros.
        target: Destino del trayecto (punto) en metros.
        band_id: Id de la banda evaluada.
        walls_crossed: Paredes atravesadas, ordenadas por distancia
            desde el origen (empate roto por wall.id para reproducibilidad).
        attenuation_db: Pérdida total en dB (suma en orden canónico
            fusionado paredes + obstáculos; decisión BN).
        obstacles_crossed: Obstáculos de mobiliario atravesados (Fase 9),
            ordenados por distancia (empate roto por obstacle.id).
    """

    source: Point2D
    target: Point2D
    band_id: str
    walls_crossed: tuple[WallCrossing, ...]
    attenuation_db: float
    obstacles_crossed: tuple[ObstacleCrossing, ...] = ()

    @property
    def wall_ids(self) -> tuple[str, ...]:
        return tuple(c.wall.id for c in self.walls_crossed)

    @property
    def obstacle_ids(self) -> tuple[str, ...]:
        return tuple(c.obstacle.id for c in self.obstacles_crossed)

    @property
    def crossings_count(self) -> int:
        """Atravesamientos totales (paredes + obstáculos)."""
        return len(self.walls_crossed) + len(self.obstacles_crossed)


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


def obstacle_attenuation_db(obstacle: Obstacle, band_id: str) -> float:
    """Pérdida de un obstáculo de mobiliario para una banda (Fase 9).

    Semántica (decisión BM — Modelo C con precedencia explícita):

    - Si ``attenuation_override_db`` define la banda, ese valor
      **sustituye** al de referencia del material (nunca se suman).
    - Si no, se usa ``material.attenuation_for(band)`` — la atenuación
      de referencia del catálogo, **sin** escalar por espesor (el
      footprint no es un espesor de pared; decisión BM).

    Args:
        obstacle: Obstáculo del dominio.
        band_id: Id de la banda (ej. "band_2_4").

    Returns:
        Atenuación en dB (no redondeada).

    Raises:
        MaterialAttenuationError: la banda no está en el override ni en
            el material (p. ej. 6 GHz en el catálogo V1). No se
            inventan valores: el comportamiento es idéntico al de las
            paredes sólidas.
    """
    if band_id in obstacle.attenuation_override_db:
        return float(obstacle.attenuation_override_db[band_id])
    return obstacle.material.attenuation_for(band_id)


def _path_bbox_overlaps_rect(path: Segment2D, rect: Rect) -> bool:
    """Descarte rápido por cajas envolventes (solo admite candidatos).

    Conservador: si las cajas no se solapan NO puede haber cruce de
    borde; si se solapan se continúa con la intersección exacta. No
    cambia la semántica, solo evita 4 intersecciones por obstáculo
    claramente fuera de ruta.
    """
    min_x = min(path.start.x, path.end.x)
    max_x = max(path.start.x, path.end.x)
    min_y = min(path.start.y, path.end.y)
    max_y = max(path.start.y, path.end.y)
    return not (
        max_x < rect.x - EPSILON_GEOMETRY
        or min_x > rect.x + rect.width + EPSILON_GEOMETRY
        or max_y < rect.y - EPSILON_GEOMETRY
        or min_y > rect.y + rect.height + EPSILON_GEOMETRY
    )


def _obstacle_candidates(
    path: Segment2D, obstacles: Iterable[Obstacle], band_id: str
) -> list[tuple[float, str, Obstacle, float]]:
    """Candidatos de obstáculo cruzados: (distancia cruda, id, obstáculo, pérdida).

    Un obstáculo se considera atravesado si el trayecto tiene **al menos
    un cruce interior estricto** con sus cuatro bordes (misma convención
    que las paredes: extremos y tangencias no cuentan — decisión BN).
    El rect es convexo, así que el trayecto cruza 1 o 2 bordes: se
    registra UN SOLO atravesamiento con la menor distancia (la entrada).

    Orden canónico: ``(distancia, obstacle.id)`` — independiente del
    orden de inserción o del orden del JSON.
    """
    candidates: list[tuple[float, str, Obstacle, float]] = []
    for obstacle in obstacles:
        if not obstacle.blocks_signal:
            continue
        if not _path_bbox_overlaps_rect(path, obstacle.rect):
            continue
        best_t: float | None = None
        for edge in obstacle.rect.edge_segments():
            params = segment_crossing_parameters(path, edge)
            if params is None:
                continue
            t = params[0]
            if best_t is None or t < best_t:
                best_t = t
        if best_t is None:
            continue
        loss = obstacle_attenuation_db(obstacle, band_id)
        candidates.append((best_t * path.length, obstacle.id, obstacle, loss))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates


def trace_obstacles(
    source: Point2D,
    target: Point2D,
    obstacles: Iterable[Obstacle],
    band_id: str,
) -> tuple[ObstacleCrossing, ...]:
    """Trazado de obstáculos de mobiliario AP → punto (Fase 9).

    Determinista e independiente de la lista de entrada: los cruces se
    ordenan por ``(distancia, obstacle.id)``. Sin obstáculos o sin
    cruces devuelve la tupla vacía (el resultado de paredes no cambia).

    Raises:
        MaterialAttenuationError: un obstáculo cruzado no tiene datos
            para la banda (p. ej. 6 GHz) ni override de esa banda.
    """
    path = Segment2D(source, target)
    crossings: list[ObstacleCrossing] = []
    for order, (distance, _oid, obstacle, loss) in enumerate(
        _obstacle_candidates(path, obstacles, band_id)
    ):
        crossings.append(
            ObstacleCrossing(
                obstacle=obstacle,
                material_id=obstacle.material.id,
                band_id=band_id,
                loss_db=loss,
                distance_from_source_m=round(distance, 6),
                order=order,
            )
        )
    return tuple(crossings)


def trace_walls(
    source: Point2D,
    target: Point2D,
    walls: Iterable[Wall],
    band_id: str,
    openings: Iterable[Opening] = (),
    obstacles: Iterable[Obstacle] = (),
) -> ObstacleTraceResult:
    """Trazado AP → punto: qué paredes y obstáculos se atraviesan, en qué orden y pérdida.

    Determinista: las paredes se evalúan contra el trayecto con la
    convención de cruce interior estricto (extremos no cuentan) y se
    ordenan por distancia desde el origen. Empates de distancia se
    rompen primero por tipo (pared antes que obstáculo) y después por
    ``id`` para reproducibilidad total, con lo que la suma flotante es
    idéntica sin importar el orden de las listas de entrada.

    Fase 8: si el cruce cae dentro de un opening de la pared (unión de
    los huecos, intervalo cerrado con ε), la pérdida de ese cruce es el
    override por banda del hueco — 0 dB si no hay datos — y **sustituye**
    a la del material (decisión BG). Un cruce en hueco no consulta el
    catálogo de materiales: 6 GHz atraviesa huecos con 0 dB, y los
    cruces sólidos siguen lanzando ``MaterialAttenuationError`` como
    antes. Sin ``openings`` el resultado es idéntico al de Fase 2–7.

    Fase 9: ``obstacles`` aporta los obstáculos de mobiliario cruzados
    (un atravesamiento por obstáculo, decisión BN). Sus pérdidas se
    suman a las de las paredes en el orden canónico; un opening sigue
    reemplazando SOLO la pérdida de su sección de pared (el obstáculo
    es independiente — sin doble atenuación por construcción). Sin
    ``obstacles`` el resultado es idéntico al de Fase 2–8.

    Args:
        source: Posición del AP en metros.
        target: Punto de evaluación en metros.
        walls: Paredes candidatas del plano (plano del piso activo).
        band_id: Id de la banda (ej. "band_2_4"). Para 6 GHz, si el
            material no tiene datos, se propaga MaterialAttenuationError.
        openings: Openings del plano (Fase 8). Solo se usan para las
            paredes cruzadas; por defecto ninguno.
        obstacles: Obstáculos del plano (Fase 9); por defecto ninguno.

    Returns:
        ObstacleTraceResult con detalle por cruce (``opening_id`` si el
        cruce cayó en un hueco), los obstáculos cruzados
        (``obstacles_crossed``) y la atenuación total.

    Raises:
        MaterialAttenuationError: banda sin datos en algún material de
            una sección sólida o de un obstáculo cruzado.
        ValueError: espesor inválido en alguna pared cruzada sólida.
    """
    path = Segment2D(source, target)
    grouped = group_openings_by_wall(openings)
    # (distancia, wall_id, wall, loss_db, opening_id) — cada pérdida se
    # calcula una sola vez por pared cruzada.
    wall_candidates: list[tuple[float, str, Wall, float, str | None]] = []

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
        wall_candidates.append((distance, wall.id, wall, loss, opening_id))

    # Fase 9: obstáculos con la MISMA semántica de cruce y su propia
    # atenuación (reutiliza el candidato ya ordenado por (dist, id)).
    obstacle_candidates = _obstacle_candidates(path, obstacles, band_id)

    # Orden fusionado canónico: (distancia, tipo —pared(0) antes que
    # obstáculo(1)—, id). Sin obstáculos equivale exactamente a ordenar
    # por (distancia, wall.id), así que la regresión es byte-idéntica.
    merged: list[tuple[float, int, str, tuple]] = [
        (distance, 0, wall_id, ("wall", wall, loss, opening_id))
        for distance, wall_id, wall, loss, opening_id in wall_candidates
    ]
    merged += [
        (distance, 1, obstacle_id, ("obstacle", obstacle, loss))
        for distance, obstacle_id, obstacle, loss in obstacle_candidates
    ]
    merged.sort(key=lambda item: (item[0], item[1], item[2]))

    crossings: list[WallCrossing] = []
    obstacle_crossings: list[ObstacleCrossing] = []
    total = 0.0
    for distance, _rank, _entity_id, payload in merged:
        total += payload[2]
        if payload[0] == "wall":
            _tag, wall, loss, opening_id = payload
            crossings.append(
                WallCrossing(
                    wall=wall,
                    material_id=wall.material.id,
                    band_id=band_id,
                    loss_db=loss,
                    distance_from_source_m=round(distance, 6),
                    order=len(crossings),
                    opening_id=opening_id,
                )
            )
        else:
            _tag, obstacle, loss = payload
            obstacle_crossings.append(
                ObstacleCrossing(
                    obstacle=obstacle,
                    material_id=obstacle.material.id,
                    band_id=band_id,
                    loss_db=loss,
                    distance_from_source_m=round(distance, 6),
                    order=len(obstacle_crossings),
                )
            )

    return ObstacleTraceResult(
        source=source,
        target=target,
        band_id=band_id,
        walls_crossed=tuple(crossings),
        attenuation_db=round(total, 2),
        obstacles_crossed=tuple(obstacle_crossings),
    )


def trace_to_obstacle_loss(trace: ObstacleTraceResult) -> ObstacleLoss:
    """Convierte un trazado al contrato ObstacleLoss del link budget.

    El desglose agrupa primero las paredes (orden Fase 2–8 intacto) y
    después los obstáculos (Fase 9); ``crossings`` cuenta los
    atravesamientos totales. Sin obstáculos el resultado es idéntico al
    de Fase 8.
    """
    detail = [
        CrossingLoss(
            material_id=c.material_id,
            band_id=c.band_id,
            loss_db=c.loss_db,
            wall_id=c.wall.id,
            opening_id=c.opening_id,
        )
        for c in trace.walls_crossed
    ]
    detail += [
        CrossingLoss(
            material_id=c.material_id,
            band_id=c.band_id,
            loss_db=c.loss_db,
            obstacle_id=c.obstacle.id,
        )
        for c in trace.obstacles_crossed
    ]
    return ObstacleLoss(
        total_db=trace.attenuation_db,
        crossings=trace.crossings_count,
        detail=tuple(detail),
    )
