"""Simulador de cobertura.

Flujo por punto:

    distancia → FSPL → trace_walls (L_obstacles) → link_budget
        → P_rx / SOM / SNR → clasificación

Fase 4: la simulación espacial (heatmap) reutiliza esta misma función
pasando los puntos de ``CoverageGrid``. No hay fórmulas duplicadas.
La UI NUNCA ejecuta fórmulas; solo llama a este módulo y pinta resultados.
"""

from __future__ import annotations

import time
from typing import Sequence

from core.geometry import Point2D
from core.radio import allowed_channel_widths_mhz
from core.result import LinkEvaluation, ObstacleLoss, SimulationResult
from core.wall import Opening, Wall
from engine.link_budget import evaluate_link
from engine.obstacles import obstacle_loss_for_crossings, trace_to_obstacle_loss, trace_walls


def simulate_coverage(
    project,
    access_point,
    frequency_band,
    sample_points: list[Point2D] | None = None,
    obstacle_materials_by_point: dict[Point2D, list] | None = None,
    client: object | None = None,
    walls: Sequence[Wall] | None = None,
    openings: Sequence[Opening] | None = None,
) -> SimulationResult:
    """Simula la cobertura de un AP sobre uno o varios puntos.

    Args:
        project: Project (proporciona radio, thresholds y frecuencia base).
        access_point: AccessPoint a evaluar.
        frequency_band: FrequencyBand (2.4/5/6 GHz).
        sample_points: Puntos a evaluar en metros. Si es None y no hay
            client, se requiere al menos un sample point o client.
        obstacle_materials_by_point: {punto: [materiales atravesados]}.
            Ruta de Fase 1 (materials explícitos, sin geometría). Se usa
            solo si ``walls`` es None.
        client: ClientDevice opcional; su posición se añade a la evaluación
            y su sensibilidad sustituye a la del AP si se indica.
        walls: Paredes del plano en metros (Fase 2). Si se indican, el
            L_obstacles de cada punto se obtiene con ``trace_walls``
            (intersección real AP → punto). Tiene prioridad sobre
            ``obstacle_materials_by_point``.
        openings: Openings del plano (Fase 8). Solo se consultan en la
            ruta geométrica (cuando se pasan ``walls``); sustituyen la
            atenuación de la pared en los cruces que caen dentro de un
            hueco (decisión BG). Por defecto ninguno: resultado idéntico
            a Fase 2–7.

    Returns:
        SimulationResult con una LinkEvaluation por punto evaluado.

    Raises:
        ValueError: si no hay puntos que evaluar, o si el ancho de
            canal de la radio no es compatible con la banda (Fase 7:
            2.4 GHz admite 20/40 MHz; 5/6 GHz 20/40/80/160 MHz).
        MaterialAttenuationError: si una pared cruzada en sección sólida
            no tiene datos de atenuación para la banda (p. ej. 6 GHz).
    """
    if sample_points is None and client is None:
        raise ValueError(
            "Se requiere al menos sample_points o client para simular."
        )

    # Compatibilidad ancho de canal × banda (Fase 7, decisión AY).
    # El ancho NO entra en FSPL; solo se valida aquí, un único punto.
    allowed_widths = allowed_channel_widths_mhz(frequency_band.frequency_mhz)
    width = access_point.radio.channel_width_mhz
    if width not in allowed_widths:
        raise ValueError(
            f"Ancho de canal {width} MHz incompatible con la banda "
            f"{frequency_band.name} ({frequency_band.frequency_mhz:g} MHz); "
            f"permitidos: {', '.join(str(w) for w in allowed_widths)} MHz."
        )

    points: list[Point2D] = list(sample_points or [])
    if client is not None:
        points.append(client.position)

    if not points:
        raise ValueError("La lista de puntos de muestreo está vacía.")

    if obstacle_materials_by_point is None:
        obstacle_materials_by_point = {}

    walls_list: list[Wall] = list(walls) if walls is not None else []
    openings_list: list[Opening] = list(openings) if openings is not None else []
    use_geometry = walls is not None

    evaluations: list[LinkEvaluation] = []

    for point in points:
        if use_geometry:
            trace = trace_walls(
                source=access_point.position,
                target=point,
                walls=walls_list,
                band_id=frequency_band.id,
                openings=openings_list,
            )
            obstacle = trace_to_obstacle_loss(trace)
        else:
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
    snr_values = [e.snr_db for e in evaluations]
    quality_counts: dict[str, int] = {}
    for evaluation in evaluations:
        key = evaluation.quality.value
        quality_counts[key] = quality_counts.get(key, 0) + 1

    target = project.thresholds.rssi_target_dbm
    meets_count = sum(1 for e in evaluations if e.rssi_meets_target)
    snr_target = project.thresholds.snr_target_db
    snr_meets_count = sum(1 for e in evaluations if e.snr_meets_target)
    total = len(evaluations)

    # Porcentajes por clase. Denominador: puntos totales evaluados (grid).
    quality_percent = {
        key: round(100.0 * count / total, 2)
        for key, count in quality_counts.items()
    }

    return {
        "point_count": total,
        "rx_min_dbm": min(rx_values),
        "rx_max_dbm": max(rx_values),
        "rx_avg_dbm": round(sum(rx_values) / total, 2),
        "quality_counts": quality_counts,
        "quality_percent": quality_percent,
        "rssi_target_dbm": target,
        "points_meeting_target": meets_count,
        "coverage_ratio": round(meets_count / total, 4),
        # Fase 7: estadísticas de SNR (mismo ganador; sin promedios de AP).
        "snr_min_db": min(snr_values),
        "snr_max_db": max(snr_values),
        "snr_avg_db": round(sum(snr_values) / total, 2),
        "snr_target_db": snr_target,
        "points_meeting_snr_target": snr_meets_count,
        "snr_ratio": round(snr_meets_count / total, 4),
    }
