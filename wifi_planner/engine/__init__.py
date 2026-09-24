"""Motor de simulación RF.

Contiene los cálculos de propagación, presupuesto de enlace,
pérdida por obstáculos, clasificación de calidad y simulación.

Reglas:
- No importa tkinter, PIL ni ningún módulo de interfaz gráfica.
- Funciones puras y deterministas siempre que sea posible.
- Sin valores mágicos: los umbrales y parámetros llegan por parámetro
  o desde config/.
"""

from engine.propagation import wavelength_m, path_loss_fspl_db
from engine.link_budget import (
    link_budget,
    system_operating_margin,
    signal_to_noise_ratio,
    evaluate_link,
)
from engine.intersection import (
    segments_cross,
    segment_crossing_parameters,
    crossing_distance_from_start,
    crossing_point,
)
from engine.obstacles import (
    obstacle_loss_for_crossings,
    obstacle_attenuation_db,
    wall_attenuation_db,
    trace_walls,
    trace_obstacles,
    trace_to_obstacle_loss,
    CrossingLoss,
    WallCrossing,
    ObstacleCrossing,
    ObstacleTraceResult,
)
from engine.classifier import (
    classify_quality,
    meets_rssi_target,
    meets_snr_target,
    rf_diagnostic,
    classify_som,
)
from engine.coverage_grid import CoverageGrid, MAX_GRID_POINTS, MIN_RESOLUTION_M
from engine.simulator import simulate_coverage
from engine.combine import combine_results

__all__ = [
    "wavelength_m",
    "path_loss_fspl_db",
    "link_budget",
    "system_operating_margin",
    "signal_to_noise_ratio",
    "evaluate_link",
    "segments_cross",
    "segment_crossing_parameters",
    "crossing_distance_from_start",
    "crossing_point",
    "obstacle_loss_for_crossings",
    "obstacle_attenuation_db",
    "wall_attenuation_db",
    "trace_walls",
    "trace_obstacles",
    "trace_to_obstacle_loss",
    "CrossingLoss",
    "WallCrossing",
    "ObstacleCrossing",
    "ObstacleTraceResult",
    "classify_quality",
    "meets_rssi_target",
    "meets_snr_target",
    "rf_diagnostic",
    "classify_som",
    "CoverageGrid",
    "MAX_GRID_POINTS",
    "MIN_RESOLUTION_M",
    "simulate_coverage",
    "combine_results",
]
