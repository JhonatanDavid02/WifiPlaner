"""Vista de solo lectura de la geometría del piso activo (Fase 14-C).

``GeometryView`` NO es un modelo de escenario paralelo: es una proyección
inmutable de ``Project`` + ``Floor`` (la única fuente de verdad) que el
Canvas consume para pintar y hacer hit-testing sin alcanzar a las listas
internas del documento.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from core.access_point import AccessPoint
from core.client import ClientDevice
from core.obstacle import Obstacle
from core.space import Floor, Space
from core.wall import Opening, Wall


@dataclass(frozen=True)
class GeometryView:
    """Instantánea congelada de la geometría visible (tuplas, no listas).

    Los elementos ``Wall``/``Opening``/``Obstacle`` ya son inmutables en
    core; aquí además se copian las listas a tuplas, de modo que una vista
    capturada no cambia aunque el documento siga editándose.
    """

    floor_id: str
    width_m: float | None
    height_m: float | None
    spaces: tuple[Space, ...]
    walls: tuple[Wall, ...]
    openings: tuple[Opening, ...]
    obstacles: tuple[Obstacle, ...]
    access_points: tuple[AccessPoint, ...]
    clients: tuple[ClientDevice, ...]


def build_geometry_view(
    floor: Floor,
    access_points: Iterable[AccessPoint],
    clients: Iterable[ClientDevice],
) -> GeometryView:
    """Construye la vista del piso dado (los AP/clientes son del proyecto).

    Args:
        floor: Piso cuya geometría se proyecta (piso activo).
        access_points: APs del proyecto (v1: compartidos entre pisos).
        clients: Clientes del proyecto (v1: compartidos entre pisos).
    """
    return GeometryView(
        floor_id=floor.id,
        width_m=floor.width_m,
        height_m=floor.height_m,
        spaces=tuple(floor.spaces),
        walls=tuple(floor.walls),
        openings=tuple(floor.openings),
        obstacles=tuple(floor.obstacles),
        access_points=tuple(access_points),
        clients=tuple(clients),
    )
