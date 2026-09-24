"""Punto de entrada de Wi-Fi Planner V1 (fundación).

Fase 1: solo verifica que dominio, motor y configuración cargan
correctamente. NO incluye interfaz gráfica.

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
from core.geometry import Point2D
from core.project import Project
from engine import evaluate_link, wavelength_m


def main() -> int:
    print("=" * 70)
    print("WI-FI PLANNER V1 - FASE 1 (FUNDACION)")
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

    print("\nFase 1 OK. Motor RF centralizado y sin UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
