"""Render del heatmap de cobertura (solo UI).

Recibe ``SimulationResult`` del engine y lo convierte en una imagen
Pillow semitransparente alineada al ``Viewport``. No contiene fórmulas
RF: solo presentación (color, alpha, capas, leyenda).

Aviso (obligatorio en la UI y en docs):
el heatmap es una ESTIMACIÓN predictiva del modelo configurado;
no es una simulación electromagnética completa ni sustituye mediciones.
"""

from __future__ import annotations

from typing import Sequence

from PIL import Image, ImageDraw

from core.project import CoverageThresholds
from core.result import QualityClass, SimulationResult
from ui.viewport import Viewport

# Escala visual continua (no modifica umbrales RF).
# De RSSI fuerte → débil. Valores de referencia de la escala de color.
_RSSI_SCALE_MIN = -90.0  # sin cobertura / muy débil
_RSSI_SCALE_MAX = -30.0  # excelente

# Paradas de color (RGB): fuerte → débil
_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-30.0, (80, 200, 120)),    # verde brillante
    (-50.0, (150, 200, 80)),    # verde lima
    (-67.0, (230, 190, 80)),    # ámbar
    (-75.0, (230, 140, 70)),    # naranja
    (-85.0, (200, 80, 80)),     # rojo
    (-90.0, (90, 60, 90)),      # morado apagado
)

DEFAULT_HEATMAP_ALPHA = 110  # 0–255; semitransparente sobre el plano


def _lerp_color(rssi_a: float, rgb_a, rssi_b: float, rgb_b: float, rssi: float) -> tuple[int, int, int]:
    if rssi_b == rssi_a:
        return rgb_a
    t = (rssi - rssi_a) / (rssi_b - rssi_a)
    t = max(0.0, min(1.0, t))
    return (
        int(round(rgb_a[0] + (rgb_b[0] - rgb_a[0]) * t)),
        int(round(rgb_a[1] + (rgb_b[1] - rgb_a[1]) * t)),
        int(round(rgb_a[2] + (rgb_b[2] - rgb_a[2]) * t)),
    )


def rssi_to_rgb(rssi_dbm: float) -> tuple[int, int, int]:
    """Convierte RSSI (dBm) en un color RGB de la escala visual continua.

    No altera umbrales RF; solo presentación.
    """
    rssi = max(_RSSI_SCALE_MIN, min(_RSSI_SCALE_MAX, float(rssi_dbm)))
    # _STOPS ordenado de fuerte (-30) a débil (-90): invertir recorrido
    stops = sorted(_STOPS, key=lambda s: s[0])  # -90 … -30
    # Recorrer de débil a fuerte o al revés: interpolar entre vecinos
    for i in range(len(stops) - 1):
        a_rssi, a_rgb = stops[i]
        b_rssi, b_rgb = stops[i + 1]
        if a_rssi <= rssi <= b_rssi:
            return _lerp_color(a_rssi, a_rgb, b_rssi, b_rgb, rssi)
    # Fuera de rangos (no debería ocurrir tras clamp)
    if rssi <= stops[0][0]:
        return stops[0][1]
    return stops[-1][1]


def rssi_to_color(rssi_dbm: float, alpha: int = DEFAULT_HEATMAP_ALPHA) -> tuple[int, int, int, int]:
    """RSSI → RGBA para la imagen del heatmap."""
    r, g, b = rssi_to_rgb(rssi_dbm)
    a = max(0, min(255, int(alpha)))
    return (r, g, b, a)


def quality_color(quality: QualityClass) -> tuple[int, int, int]:
    """Color de la leyenda para una clase de calidad (más plano)."""
    mapping = {
        QualityClass.EXCELLENT: (80, 200, 120),
        QualityClass.GOOD: (180, 200, 80),
        QualityClass.REGULAR: (230, 190, 80),
        QualityClass.WEAK: (230, 120, 70),
        QualityClass.NO_COVERAGE: (120, 70, 90),
    }
    return mapping.get(quality, (150, 150, 150))


def legend_rows(thresholds: CoverageThresholds) -> list[dict]:
    """Filas de leyenda usando los umbrales del modelo (no mágicos en UI).

    Cada fila: label, color RGB, rango legible en dBm.
    El denominador de los % de cobertura es: puntos totales del grid.
    """
    return [
        {
            "label": QualityClass.EXCELLENT.value,
            "color": quality_color(QualityClass.EXCELLENT),
            "range": f"≥ {thresholds.excellent_min_dbm:g} dBm",
        },
        {
            "label": QualityClass.GOOD.value,
            "color": quality_color(QualityClass.GOOD),
            "range": (
                f"≥ {thresholds.good_min_dbm:g} dBm"
            ),
        },
        {
            "label": QualityClass.REGULAR.value,
            "color": quality_color(QualityClass.REGULAR),
            "range": f"≥ {thresholds.regular_min_dbm:g} dBm",
        },
        {
            "label": QualityClass.WEAK.value,
            "color": quality_color(QualityClass.WEAK),
            "range": f"≥ {thresholds.weak_min_dbm:g} dBm",
        },
        {
            "label": QualityClass.NO_COVERAGE.value,
            "color": quality_color(QualityClass.NO_COVERAGE),
            "range": f"< {thresholds.weak_min_dbm:g} dBm",
        },
    ]


def build_heatmap_image(
    result: SimulationResult,
    viewport: Viewport,
    alpha: int = DEFAULT_HEATMAP_ALPHA,
    cell_size_m: float | None = None,
) -> Image.Image | None:
    """Construye la imagen RGBA del heatmap alineada al rect del piso.

    Cada evaluación se pinta como una celda centrada en su punto
    (metros → píxeles SOLO vía Viewport). El tamaño de celda por defecto
    es la resolución del grid si se infiere del espaciado, o un valor
    indicado por el llamador.

    Returns:
        Imagen RGBA del tamaño del rect del piso en píxeles, o None si
        no hay evaluaciones.
    """
    evaluations = result.evaluations
    if not evaluations:
        return None

    x1f, y1f, x2f, y2f = viewport.floor_rect_px
    img_w = max(1, int(round(x2f - x1f)))
    img_h = max(1, int(round(y2f - y1f)))
    image = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Inferir paso del grid a partir de las evaluaciones (eje x o y)
    if cell_size_m is None:
        cell_size_m = _infer_cell_size(evaluations)

    half_px = max(1.0, viewport.world_to_screen_len(cell_size_m) / 2.0)

    for ev in evaluations:
        sx, sy = viewport.world_to_screen(ev.point)
        cx = sx - x1f
        cy = sy - y1f
        color = rssi_to_color(ev.rx_power_dbm, alpha=alpha)
        draw.rectangle(
            (cx - half_px, cy - half_px, cx + half_px, cy + half_px),
            fill=color,
        )
    return image


def _infer_cell_size(evaluations: Sequence) -> float:
    """Estima la separación en metros entre muestras vecinas del grid."""
    xs = sorted({round(e.point.x, 6) for e in evaluations})
    ys = sorted({round(e.point.y, 6) for e in evaluations})
    deltas: list[float] = []
    for series in (xs, ys):
        for a, b in zip(series, series[1:]):
            d = b - a
            if d > 1e-9:
                deltas.append(d)
    if not deltas:
        return 0.5
    return min(deltas)


def stats_text(result: SimulationResult) -> str:
    """Estadísticas básicas. Denominador de %: puntos totales del grid.

    Si el resultado es combinado (Fase 5), añade dominancia por AP
    (puntos dominados / total) cuando ``ap_dominance_percent`` existe.
    """
    stats = result.stats or {}
    n = stats.get("point_count", len(result.evaluations))
    if not n:
        return "Sin puntos simulados."

    lines = [
        f"Puntos del grid: {n}",
        f"RSSI mínimo: {stats.get('rx_min_dbm', 0):.2f} dBm",
        f"RSSI máximo: {stats.get('rx_max_dbm', 0):.2f} dBm",
        f"RSSI promedio: {stats.get('rx_avg_dbm', 0):.2f} dBm",
        "",
        "% del total de puntos del grid:",
    ]
    quality_counts = stats.get("quality_counts", {}) or {}
    order = [
        QualityClass.EXCELLENT.value,
        QualityClass.GOOD.value,
        QualityClass.REGULAR.value,
        QualityClass.WEAK.value,
        QualityClass.NO_COVERAGE.value,
    ]
    for label in order:
        count = int(quality_counts.get(label, 0))
        pct = 100.0 * count / n
        lines.append(f"  {label}: {pct:.1f}% ({count})")

    # Fase 5: dominancia del AP mejor en cada punto (cobertura combinada).
    dominance = stats.get("ap_dominance_percent") or {}
    counts = stats.get("ap_dominance_counts") or {}
    if dominance:
        lines.append("")
        lines.append("AP dominante (mejor RSSI por punto):")
        for ap_id in sorted(dominance.keys()):
            pct = dominance[ap_id]
            count = int(counts.get(ap_id, 0))
            lines.append(f"  {ap_id}: {pct:.1f}% ({count})")
    return "\n".join(lines)


def client_link_summary(client_evals: Sequence) -> list[str]:
    """Resumen breve por cliente (si hay evaluaciones en su posición)."""
    lines: list[str] = []
    for ev in client_evals:
        lines.append(
            f"{ev.access_point_id} @ cliente: RSSI {ev.rx_power_dbm:.1f} dBm | "
            f"SOM {ev.som_db:.1f} dB | {ev.quality.value}"
        )
    return lines
