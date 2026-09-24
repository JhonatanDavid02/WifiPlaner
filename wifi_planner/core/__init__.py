"""Modelo de dominio del Wi-Fi Planner.

Este paquete define entidades puras del dominio: geometría en metros,
materiales, bandas, configuración de radio, puntos de acceso y resultados.

Reglas:
- No importa tkinter, PIL ni ningún módulo de interfaz gráfica.
- No contiene fórmulas de radiofrecuencia (viven en engine/).
- Todas las coordenadas físicas están en metros.
"""

from core.geometry import Point2D, Rect, Segment2D
from core.band import FrequencyBand
from core.material import Material
from core.radio import RadioConfiguration
from core.access_point import AccessPoint
from core.client import ClientDevice
from core.wall import Wall, Opening
from core.obstacle import Obstacle
from core.space import Space, Floor
from core.project import Project, CoverageThresholds
from core.result import (
    QualityClass,
    LinkEvaluation,
    SimulationResult,
    ObstacleLoss,
)

__all__ = [
    "Point2D",
    "Rect",
    "Segment2D",
    "FrequencyBand",
    "Material",
    "RadioConfiguration",
    "AccessPoint",
    "ClientDevice",
    "Wall",
    "Opening",
    "Obstacle",
    "Space",
    "Floor",
    "Project",
    "CoverageThresholds",
    "QualityClass",
    "LinkEvaluation",
    "SimulationResult",
    "ObstacleLoss",
]
