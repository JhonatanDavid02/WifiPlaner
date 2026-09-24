"""Punto de entrada de Wi-Fi Planner V1.

Fase 1: fundación (dominio, motor RF, configuración).
Fase 2: geometría de paredes + atenuación integrada al link budget.
NO incluye interfaz gráfica.

Uso:
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permitir ejecución directa desde la raíz del paquete wifi_planner/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from core.band import FrequencyBand
from core.geometry import Point2D, Segment2D
from core.project import Project
from core.wall import Wall
from engine import evaluate_link, wavelength_m, trace_walls
from engine.simulator import simulate_coverage
from core.access_point import AccessPoint


def main() -> int:
    print("=" * 70)
    print("WI-FI PLANNER V1 - FASE 2 (GEOMETRIA RF + PAREDES)")
    print("=" * 70)

    cfg = load_config()
    radio = cfg["radio"]
    thresholds = cfg["thresholds"]
    bands = cfg["bands"]
    materials = cfg["materials"]

    project = Project(
        name="Demo Fundacion",
        bands=bands,
        materials=materials,
        radio=radio,
        thresholds=thresholds,
    )

    print(f"\nProyecto:        {project.name}")
    print(f"Unidad fisica:   {project.units}")
    print(f"Bandas:          {', '.join(b.name for b in project.bands)}")
    print(f"Materiales:      {len(project.materials)}")
    print(f"Potencia TX:     {radio.p_tx_dbm} dBm")
    print(f"Fade margin:     {radio.fade_margin_db} dB")
    print(f"RSSI objetivo:   > {thresholds.rssi_target_dbm} dBm (estricto)")
    print(f"UMBRAL SOM:      APROBADO >= {thresholds.som_aprobado_min_db} dB | "
          f"RIESGO >= {thresholds.som_riesgo_min_db} dB")

    band_24 = project.get_band("band_2_4")
    band_5 = project.get_band("band_5")

    print("\n-- Longitud de onda --")
    for band in (band_24, band_5):
        lam = wavelength_m(band.frequency_hz)
        print(f"  {band.name}: {lam * 100:.2f} cm")

    ap_pos = Point2D(0.0, 0.0)
    client_pos = Point2D(5.0, 0.0)

    print("\n-- Evaluacion de enlace (5 m, sin obstaculos) --")
    for band in (band_24, band_5):
        evaluation = evaluate_link(
            radio=project.radio,
            access_point_id="AP_DEMO",
            band_id=band.id,
            ap_position=ap_pos,
            client_position=client_pos,
            frequency_mhz=band.frequency_mhz,
            thresholds=project.thresholds,
        )
        print(
            f"  {band.name}: P_rx={evaluation.rx_power_dbm} dBm | "
            f"SOM={evaluation.som_db} dB | {evaluation.verdict.value} | "
            f"Calidad={evaluation.quality.value}"
        )

    # --- Fase 2: pared real en el trayecto AP (0,0) -> punto (10,0) ---
    drywall = project.get_material("drywall")
    concrete = project.get_material("concrete")
    wall_drywall = Wall(
        id="W_DRYWALL",
        segment=Segment2D(Point2D(5.0, -5.0), Point2D(5.0, 5.0)),
        material=drywall,
    )
    wall_concrete = Wall(
        id="W_CONCRETE",
        segment=Segment2D(Point2D(7.0, -5.0), Point2D(7.0, 5.0)),
        material=concrete,
    )
    walls = [wall_drywall, wall_concrete]
    point = Point2D(10.0, 0.0)

    print("\n-- Fase 2: trazado de paredes (AP (0,0) -> (10,0)) --")
    for band in (band_24, band_5):
        trace = trace_walls(ap_pos, point, walls, band.id)
        print(
            f"  {band.name}: {trace.crossings_count} pared(es) | "
            f"L_obstacles={trace.attenuation_db} dB | "
            f"orden={list(trace.wall_ids)}"
        )
        for crossing in trace.walls_crossed:
            print(
                f"    [{crossing.order}] {crossing.wall.id} "
                f"({crossing.material_id}) @ "
                f"{crossing.distance_from_source_m} m -> "
                f"{crossing.loss_db} dB"
            )

    print("\n-- Integracion en simulate_coverage (una pared drywall) --")
    ap = AccessPoint(id="AP_DEMO", position=ap_pos, radio=project.radio)
    result = simulate_coverage(
        project=project,
        access_point=ap,
        frequency_band=band_24,
        sample_points=[point],
        walls=[wall_drywall],
    )
    ev = result.evaluations[0]
    print(
        f"  2.4 GHz: FSPL={ev.path_loss_db} dB | "
        f"L_obstacles={ev.obstacle_loss_db} dB | "
        f"P_rx={ev.rx_power_dbm} dBm | SOM={ev.som_db} dB | "
        f"{ev.verdict.value}"
    )

    print("\nFase 2 OK. Geometria de paredes integrada al motor RF. Sin UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
