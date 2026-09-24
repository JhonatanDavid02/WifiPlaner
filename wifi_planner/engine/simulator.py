"""Simulador de cobertura.

Fase 1: simulación de un punto (AP → punto evaluado).
La simulación sobre cuadrícula (grid/heatmap) llega en Fase 4,
pero este módulo ya expone la interfaz que consumirá la UI:

    simulate_coverage(project, access_point, frequency_band) -> SimulationResult

La UI NUNCA ejecuta fórmulas; solo llama a este módulo y pinta resultados.
"""

from __future__ import annotations

import time

from core.geometry import Point2D
from core.result import LinkEvaluation, ObstacleLoss, SimulationResult
from engine.link_budget import evaluate_link
from engine.obstacles import obstacle_loss_for_crossings


def simulate_coverage(
    project,
    access_point,
    frequency_band,
    sample_points: list[Point2D] | None = None,
    obstacle_materials_by_point: dict[Point2D, list] | None = None,
    client: object | None = None,
) -> SimulationResult:
    """Simula la cobertura de un AP sobre uno o varios puntos.

    Args:
        project: Project (proporciona radio, thresholds y frecuencia base).
        access_point: AccessPoint a evaluar.
        frequency_band: FrequencyBand (2.4/5/6 GHz).
        sample_points: Puntos a evaluar en metros. Si es None y no hay
            client, se evalúa el propio centro del AP no es válido
            (distancia 0) => se requiere al menos un sample point o client.
        obstacle_material_by_point: {punto: [materiales atravesados]}.
            En Fase 1 la geometría real de paredes aún no se traza;
            esta estructura permite pruebas y llegará completa en Fase 2.
        client: ClientDevice opcional; su posición se añade a la evaluación
            y su sensibilidad sustituye a la del AP si se indica.

    Returns:
        SimulationResult con una LinkEvaluation por punto evaluado.

    Raises:
        ValueError: si no hay puntos que evaluar.
    """
    if sample_points is None and client is None:
        raise ValueError(
            "Se requiere al menos sample_points o client para simular."
        )

    points: list[Point2D] = list(sample_points or [])
    if client is not None:
        points.append(client.position)

    if not points:
        raise ValueError("La lista de puntos de muestreo está vacía.")

    if obstacle_materials_by_point is None:
        obstacle_materials_by_point = {}

    evaluations: list[LinkEvaluation] = []

    for point in points:
        materials = obstacle_materials_by_point.get(point, [])
        obstacle = obstacle_loss_for_crossings(
            materials=materials,
            band_id=frequency_band.id,
        )

        # Sensibilidad: la del cliente si se usa un client, si no la del radio.
        radio = access_point.radio
        if client is not None and hasattr(client, "sensitivity_dbm"):
            from dataclasses import replace

            radio = replace(radio, sensitivity_dbm=client.sensitivity_dbm)

        evaluation = evaluate_link(
            radio=radio,
            access_point_id=access_point.id,
            band_id=frequency_band.id,
            ap_position=access_point.position,
            client_position=point,
            frequency_mhz=frequency_band.frequency_mhz,
            thresholds=project.thresholds,
            obstacle_loss=obstacle,
        )
        evaluations.append(evaluation)

    stats = _compute_stats(evaluations, project)

    return SimulationResult(
        project_name=project.name,
        band_id=frequency_band.id,
        evaluations=tuple(evaluations),
        generated_at=time.time(),
        stats=stats,
    )


def _compute_stats(evaluations: list[LinkEvaluation], project) -> dict:
    """Estadísticas agregadas simples del resultado."""
    if not evaluations:
        return {}

    rx_values = [e.rx_power_dbm for e in evaluations]
    quality_counts: dict[str, int] = {}
    for evaluation in evaluations:
        key = evaluation.quality.value
        quality_counts[key] = quality_counts.get(key, 0) + 1

    target = project.thresholds.rssi_target_dbm
    meets_count = sum(1 for e in evaluations if e.rssi_meets_target)

    return {
        "point_count": len(evaluations),
        "rx_min_dbm": min(rx_values),
        "rx_max_dbm": max(rx_values),
        "rx_avg_dbm": round(sum(rx_values) / len(rx_values), 2),
        "quality_counts": quality_counts,
        "rssi_target_dbm": target,
        "points_meeting_target": meets_count,
        "coverage_ratio": round(meets_count / len(evaluations), 4),
    }
