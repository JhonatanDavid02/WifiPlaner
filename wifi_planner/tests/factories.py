"""Fábricas compartidas de proyectos, escenarios y pipelines (Fase 14).

Proporcionan UNA sola fuente de construcción de proyectos de test para
que toda la suite (y la prueba arquitectónica A/B) use las mismas
entidades del dominio: ``Project``, ``Floor``, ``Wall``, ``Space``,
``AccessPoint`` y ``CoverageGrid``. No hay modelo ``Scenario``: los
"escenarios" son simples proyectos del dominio existente (F14).

Reglas:
- Solo entidades de ``core/`` y APIs de ``engine/`` (nada de Tkinter).
- Construcciones deterministas (mismos ids/coordenadas en cada corrida).
- ``run_rf_pipeline`` ejecuta la secuencia canónica F10 → F11 → F12 →
  F5 (+ F13 opcional) SIN ninguna rama por escenario: la misma función
  procesa cualquier edificio.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.access_point import AccessPoint
from core.channel import validate_channel_config
from core.geometry import Point2D, Segment2D
from core.project import Project
from core.space import Floor
from core.wall import Wall
from engine.channel_optimization import (
    OptimizationResult,
    OptimizationTarget,
    optimize_channels,
)
from engine.combine import combine_results
from engine.coverage_grid import CoverageGrid
from engine.interference import annotate_interference, emission_for_ap
from engine.simulator import SimulationResult, simulate_coverage
from engine.sinr import annotate_sinr

DEFAULT_BAND_ID = "band_2_4"


def make_session():
    """EditorSession con el proyecto por defecto (fábrica única de sesiones)."""
    from ui.session import EditorSession

    return EditorSession()


def make_project(name: str, width_m: float, height_m: float) -> Project:
    """Proyecto con un único piso de las dimensiones indicadas (metros)."""
    project = Project(name=name)
    project.floors = [
        Floor(id="FLOOR-001", name="Planta baja", width_m=width_m, height_m=height_m)
    ]
    return project


def floor_of(project: Project) -> Floor:
    """Piso del proyecto (los escenarios de test son de un piso)."""
    return project.floors[0]


def add_wall(
    project: Project,
    start: Point2D,
    end: Point2D,
    material_id: str = "drywall",
    thickness_m: float | None = None,
) -> Wall:
    """Añade una pared al piso con un id determinista."""
    floor = floor_of(project)
    wall = Wall(
        id=f"WALL-{len(floor.walls) + 1:03d}",
        segment=Segment2D(start, end),
        material=project.get_material(material_id),
        thickness_m=thickness_m,
    )
    floor.walls.append(wall)
    return wall


def add_ap(
    project: Project,
    x: float,
    y: float,
    channel: int = 6,
    band_id: str = DEFAULT_BAND_ID,
    name: str = "",
) -> AccessPoint:
    """Añade un AP con banda/canal válidos (triple F10 validado ya)."""
    band = project.get_band(band_id)
    validate_channel_config(band, channel, 20)
    ap = AccessPoint(
        id=f"AP-{len(project.access_points) + 1:03d}",
        position=Point2D(x, y),
        band_id=band_id,
        channel=channel,
        name=name,
    )
    project.access_points.append(ap)
    return ap


def scenario_a() -> Project:
    """Escenario A: 10 × 10 m, 2 paredes, 1 AP (canal 6, 2.4 GHz)."""
    project = make_project("Escenario A", 10.0, 10.0)
    # Pared vertical en x=4 con una abertura natural (hueco y∈[6,8]:
    # las dos paredes dejan paso, como un pasillo).
    add_wall(project, Point2D(4.0, 0.0), Point2D(4.0, 6.0), "drywall")
    add_wall(project, Point2D(4.0, 8.0), Point2D(4.0, 10.0), "concrete")
    add_ap(project, 2.0, 5.0, channel=6, name="AP A")
    return project


def scenario_b() -> Project:
    """Escenario B: 50 × 30 m, 20 paredes, 4 APs (canales 1/6/11/6)."""
    project = make_project("Escenario B", 50.0, 30.0)
    specs: list[tuple[Point2D, Point2D, str]] = []
    # 8 divisiones verticales de oficinas (x = 6, 12, ..., 48; y 0→12).
    for k in range(1, 9):
        specs.append((Point2D(6.0 * k, 0.0), Point2D(6.0 * k, 12.0), "drywall"))
    # Muros largos del ala sur y del corredor.
    specs.append((Point2D(0.0, 12.0), Point2D(50.0, 12.0), "brick"))
    specs.append((Point2D(0.0, 15.0), Point2D(50.0, 15.0), "brick"))
    # 6 divisiones verticales del ala norte (x = 4, 12, ..., 44; y 15→30).
    for k in range(1, 7):
        specs.append((Point2D(8.0 * k - 4.0, 15.0), Point2D(8.0 * k - 4.0, 30.0), "drywall"))
    # 4 muros interiores (acero/concreto) para atenuación fuerte.
    specs.append((Point2D(0.0, 6.0), Point2D(25.0, 6.0), "concrete"))
    specs.append((Point2D(25.0, 6.0), Point2D(50.0, 6.0), "concrete"))
    specs.append((Point2D(0.0, 21.0), Point2D(20.0, 21.0), "reinforced_concrete"))
    specs.append((Point2D(30.0, 21.0), Point2D(50.0, 21.0), "reinforced_concrete"))
    assert len(specs) == 20
    for start, end, material_id in specs:
        add_wall(project, start, end, material_id)
    # 4 APs: dos comparten canal 6 (interferencia real para F11/F12/F13).
    add_ap(project, 4.0, 4.0, channel=1, name="AP B1")
    add_ap(project, 20.0, 16.0, channel=6, name="AP B2")
    add_ap(project, 34.0, 4.0, channel=11, name="AP B3")
    add_ap(project, 46.0, 25.0, channel=6, name="AP B4")
    return project


def scenario_c() -> Project:
    """Escenario C (grande): 120 × 80 m, 36 paredes, 6 APs.

    Diseñado para comprobar escalabilidad con geometría grande; los
    tests lo evalúan a resolución gruesa para mantener la suite rápida.
    """
    project = make_project("Escenario C", 120.0, 80.0)
    specs: list[tuple[Point2D, Point2D, str]] = []
    # 12 crujías verticales cada 10 m (y 0→40): 12 paredes.
    for k in range(1, 13):
        specs.append((Point2D(10.0 * k, 0.0), Point2D(10.0 * k, 40.0), "drywall"))
    # Muro largo que parte el edificio en dos mitades: 1 pared.
    specs.append((Point2D(0.0, 40.0), Point2D(120.0, 40.0), "brick"))
    # 12 crujías verticales del ala norte desplazadas: 12 paredes.
    for k in range(1, 13):
        specs.append((Point2D(10.0 * k - 5.0, 40.0), Point2D(10.0 * k - 5.0, 80.0), "drywall"))
    # 6 muros horizontales interiores: 6 paredes.
    for k in range(1, 4):
        specs.append((Point2D(0.0, 10.0 * k), Point2D(60.0, 10.0 * k), "concrete"))
    for k in range(1, 4):
        specs.append((Point2D(60.0, 50.0 + 10.0 * (k - 1)), Point2D(120.0, 50.0 + 10.0 * (k - 1)), "concrete"))
    # 5 muros fuertes de refuerzo: 5 paredes (12+1+12+6+5 = 36).
    specs.append((Point2D(30.0, 0.0), Point2D(30.0, 40.0), "reinforced_concrete"))
    specs.append((Point2D(90.0, 0.0), Point2D(90.0, 40.0), "reinforced_concrete"))
    specs.append((Point2D(35.0, 40.0), Point2D(35.0, 80.0), "reinforced_concrete"))
    specs.append((Point2D(85.0, 40.0), Point2D(85.0, 80.0), "reinforced_concrete"))
    specs.append((Point2D(0.0, 70.0), Point2D(120.0, 70.0), "reinforced_concrete"))
    assert len(specs) == 36
    for start, end, material_id in specs:
        add_wall(project, start, end, material_id)
    # 6 APs con canales repartidos (2× por canal en 2.4 GHz).
    add_ap(project, 5.0, 5.0, channel=1, name="AP C1")
    add_ap(project, 55.0, 5.0, channel=6, name="AP C2")
    add_ap(project, 110.0, 5.0, channel=11, name="AP C3")
    add_ap(project, 5.0, 60.0, channel=6, name="AP C4")
    add_ap(project, 55.0, 60.0, channel=11, name="AP C5")
    add_ap(project, 110.0, 60.0, channel=1, name="AP C6")
    return project


def grid_for(project: Project, resolution_m: float = 0.5) -> CoverageGrid:
    """CoverageGrid del piso del proyecto (bounds del dominio)."""
    floor = floor_of(project)
    return CoverageGrid(
        width_m=floor.width_m, height_m=floor.height_m, resolution_m=resolution_m
    )


@dataclass(frozen=True)
class PipelineOutcome:
    """Resultados de una corrida completa sobre un escenario.

    Attributes:
        grid: Malla de puntos usada.
        base_results: ``{ap_id: SimulationResult}`` crudos (F10).
        f11_results: Resultados anotados con interferencia (F11).
        f12_results: Resultados anotados con SINR (F12).
        combined: Heatmap combinado por MAX RSSI (F5).
        optimization: Resultado de F13 (o ``None`` si optimize=False).
    """

    grid: CoverageGrid
    base_results: dict
    f11_results: tuple
    f12_results: tuple
    combined: SimulationResult
    optimization: OptimizationResult | None


def run_rf_pipeline(
    project: Project,
    band_id: str = DEFAULT_BAND_ID,
    resolution_m: float = 0.5,
    optimize: bool = True,
) -> PipelineOutcome:
    """Secuencia canónica F10 → F11 → F12 → F5 (+ F13) sin ramas.

    Esta función es idéntica para CUALQUIER proyecto: no existe ninguna
    referencia al escenario. Es la prueba de fuego de que el motor es
    independiente del edificio (F14-A).
    """
    floor = floor_of(project)
    band = project.get_band(band_id)
    grid = grid_for(project, resolution_m)
    points = grid.points()

    # F10: simulación por AP sobre el MISMO grid con la geometría real.
    base_results: dict = {}
    for ap in project.access_points:
        base_results[ap.id] = simulate_coverage(
            project=project,
            access_point=ap,
            frequency_band=band,
            sample_points=points,
            walls=floor.walls,
            openings=floor.openings,
            obstacles=floor.obstacles,
        )
    results = [base_results[ap_id] for ap_id in sorted(base_results)]

    # F11: emisiones (APs con canal) + anotación de interferencia.
    emissions = {}
    for ap in project.access_points:
        emission = emission_for_ap(ap, band)
        if emission is not None:
            emissions[ap.id] = emission
    f11 = annotate_interference(results, emissions)

    # F12: SINR sobre los resultados ya anotados (después de F11).
    f12 = annotate_sinr(f11, project.thresholds)

    # F5: combinación por MAX RSSI (misma banda en todos los escenarios).
    combined = f12[0] if len(f12) == 1 else combine_results(f12)

    # F13: optimización de canales (semilla = asignación actual).
    optimization = None
    if optimize:
        targets = [
            OptimizationTarget(
                ap_id=ap.id,
                band=band,
                width_mhz=ap.radio.channel_width_mhz,
                current_channel=ap.channel,
            )
            for ap in project.access_points
            if ap.channel is not None
        ]
        optimization = optimize_channels(targets, base_results, project.thresholds)

    return PipelineOutcome(
        grid=grid,
        base_results=base_results,
        f11_results=tuple(f11),
        f12_results=tuple(f12),
        combined=combined,
        optimization=optimization,
    )


__all__ = [
    "DEFAULT_BAND_ID",
    "PipelineOutcome",
    "add_ap",
    "add_wall",
    "floor_of",
    "grid_for",
    "make_project",
    "make_session",
    "run_rf_pipeline",
    "scenario_a",
    "scenario_b",
    "scenario_c",
]
