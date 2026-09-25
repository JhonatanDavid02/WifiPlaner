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

# Fase 7: escala visual de SNR (dB) — MISMAS paletas, otra dirección:
# 0 dB (malo) → 45 dB (excelente). Solo presentación (decisión BA).
_SNR_SCALE_MIN = 0.0
_SNR_SCALE_MAX = 45.0

_SNR_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (90, 60, 90)),      # morado apagado (sin señal útil)
    (10.0, (200, 80, 80)),    # rojo
    (20.0, (230, 140, 70)),   # naranja
    (25.0, (230, 190, 80)),   # ámbar (umbral por defecto)
    (35.0, (150, 200, 80)),   # verde lima
    (45.0, (80, 200, 120)),   # verde brillante
)

DEFAULT_HEATMAP_ALPHA = 110  # 0–255; semitransparente sobre el plano

# Fase 11: escala visual de INTERFERENCIA (dBm, decisión CC). Dirección
# INVERTIDA respecto a RSSI: aquí más alto = PEOR. None (sin
# contribuidores) se colorea como el mínimo: «sin interferencia».
# Presentación pura: no son umbrales RF ni tocan el RSSI histórico.
_INTERFERENCE_SCALE_MIN = -95.0   # sin/nula → verde (buena)
_INTERFERENCE_SCALE_MAX = -30.0   # fuerte → rojo/morado (mala)

_INTERFERENCE_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (-95.0, (80, 200, 120)),    # verde brillante: sin interferencia
    (-85.0, (150, 200, 80)),    # verde lima: muy baja
    (-70.0, (230, 190, 80)),    # ámbar: baja
    (-55.0, (230, 140, 70)),    # naranja: alta
    (-40.0, (200, 80, 80)),     # rojo: muy alta
    (-30.0, (140, 50, 90)),     # morado apagado: extrema
)

# Métricas soportadas por el render (vista; la validación es aquí y en
# la sesión, nunca en el engine). El enum HeatmapMetric de F7 queda
# congelado por contrato; «interference» se añade SOLO a este registro
# (Fase 11, decisión CC).
HEATMAP_METRIC_INTERFERENCE = "interference"
HEATMAP_METRICS = ("rssi", "snr", HEATMAP_METRIC_INTERFERENCE)


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


def _stops_to_rgb(
    value: float,
    scale_min: float,
    scale_max: float,
    stops: tuple[tuple[float, tuple[int, int, int]], ...],
) -> tuple[int, int, int]:
    """Interpola ``value`` (ya acotado a la escala) entre paradas ordenadas."""
    v = max(scale_min, min(scale_max, float(value)))
    ordered = sorted(stops, key=lambda s: s[0])
    for i in range(len(ordered) - 1):
        a_v, a_rgb = ordered[i]
        b_v, b_rgb = ordered[i + 1]
        if a_v <= v <= b_v:
            return _lerp_color(a_v, a_rgb, b_v, b_rgb, v)
    if v <= ordered[0][0]:
        return ordered[0][1]
    return ordered[-1][1]


def rssi_to_rgb(rssi_dbm: float) -> tuple[int, int, int]:
    """Convierte RSSI (dBm) en un color RGB de la escala visual continua.

    No altera umbrales RF; solo presentación.
    """
    return _stops_to_rgb(rssi_dbm, _RSSI_SCALE_MIN, _RSSI_SCALE_MAX, _STOPS)


def rssi_to_color(rssi_dbm: float, alpha: int = DEFAULT_HEATMAP_ALPHA) -> tuple[int, int, int, int]:
    """RSSI → RGBA para la imagen del heatmap."""
    r, g, b = rssi_to_rgb(rssi_dbm)
    a = max(0, min(255, int(alpha)))
    return (r, g, b, a)


def snr_to_rgb(snr_db: float) -> tuple[int, int, int]:
    """Convierte SNR (dB) en un color RGB (escala 0–45 dB, Fase 7).

    No altera umbrales RF; solo presentación (misma paleta que RSSI).
    """
    return _stops_to_rgb(snr_db, _SNR_SCALE_MIN, _SNR_SCALE_MAX, _SNR_STOPS)


def snr_to_color(snr_db: float, alpha: int = DEFAULT_HEATMAP_ALPHA) -> tuple[int, int, int, int]:
    """SNR → RGBA para la imagen del heatmap."""
    r, g, b = snr_to_rgb(snr_db)
    a = max(0, min(255, int(alpha)))
    return (r, g, b, a)


def interference_to_rgb(interference_dbm: float | None) -> tuple[int, int, int]:
    """Interferencia agregada (dBm) → color RGB (Fase 11, decisión CC).

    Escala invertida (más alto = peor). ``None`` = sin contribuidores
    efectivos ⇒ color de «sin interferencia». Solo presentación.
    """
    value = _INTERFERENCE_SCALE_MIN if interference_dbm is None else interference_dbm
    return _stops_to_rgb(
        value, _INTERFERENCE_SCALE_MIN, _INTERFERENCE_SCALE_MAX, _INTERFERENCE_STOPS
    )


def interference_to_color(
    interference_dbm: float | None, alpha: int = DEFAULT_HEATMAP_ALPHA
) -> tuple[int, int, int, int]:
    """Interferencia (dBm o None) → RGBA para la imagen del heatmap."""
    r, g, b = interference_to_rgb(interference_dbm)
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


def legend_title(metric: str = "rssi") -> str:
    """Título de la leyenda según la métrica visible (Fase 7 + 11)."""
    if metric == "snr":
        return "SNR (dB)"
    if metric == "rssi":
        return "Cobertura Wi-Fi"
    if metric == HEATMAP_METRIC_INTERFERENCE:
        return "Interferencia (dBm)"
    raise ValueError(f"Métrica no soportada: {metric!r}")


def legend_rows(thresholds: CoverageThresholds, metric: str = "rssi") -> list[dict]:
    """Filas de leyenda usando los umbrales del modelo (no mágicos en UI).

    Cada fila: label, color RGB, rango legible en dBm (o dB para SNR).
    El denominador de los % de cobertura es: puntos totales del grid.

    - ``rssi``: 5 filas de calidad (idénticas a Fase 4/5, contrato).
    - ``snr``: 2 filas semánticas frente a ``snr_target_db`` (Fase 7).
    - ``interference``: bandas visuales de la escala F11 (paradas de
      ``_INTERFERENCE_STOPS``; NO son umbrales RF — decisión CC).
    """
    if metric == "snr":
        target = thresholds.snr_target_db
        return [
            {
                "label": "SNR objetivo",
                "color": (80, 200, 120),
                "range": f"≥ {target:g} dB",
            },
            {
                "label": "Por debajo",
                "color": (120, 70, 90),
                "range": f"< {target:g} dB",
            },
        ]
    if metric == HEATMAP_METRIC_INTERFERENCE:
        # Cortes alineados a _INTERFERENCE_STOPS (mismos colores).
        return [
            {
                "label": "Interferencia extrema",
                "color": (140, 50, 90),
                "range": "≥ -30 dBm",
            },
            {
                "label": "Interferencia muy alta",
                "color": (200, 80, 80),
                "range": "≥ -40 dBm",
            },
            {
                "label": "Interferencia alta",
                "color": (230, 140, 70),
                "range": "≥ -55 dBm",
            },
            {
                "label": "Interferencia baja",
                "color": (230, 190, 80),
                "range": "≥ -70 dBm",
            },
            {
                "label": "Sin interferencia",
                "color": (80, 200, 120),
                "range": "< -85 dBm",
            },
        ]
    if metric != "rssi":
        raise ValueError(f"Métrica no soportada: {metric!r}")
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
    metric: str = "rssi",
) -> Image.Image | None:
    """Construye la imagen RGBA del heatmap alineada al rect del piso.

    Cada evaluación se pinta como una celda centrada en su punto
    (metros → píxeles SOLO vía Viewport). El tamaño de celda por defecto
    es la resolución del grid si se infiere del espaciado, o un valor
    indicado por el llamador.

    Args:
        metric: ``"rssi"`` (default, Fase 4/5), ``"snr"`` (Fase 7) o
            ``"interference"`` (Fase 11); decide qué valor de cada
            evaluación se colorea.

    Returns:
        Imagen RGBA del tamaño del rect del piso en píxeles, o None si
        no hay evaluaciones.

    Raises:
        ValueError: si ``metric`` no es soportada.
    """
    if metric not in HEATMAP_METRICS:
        raise ValueError(f"Métrica no soportada: {metric!r}")
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

    if metric == "snr":
        color_fn = snr_to_color
    elif metric == HEATMAP_METRIC_INTERFERENCE:
        color_fn = interference_to_color
    else:
        color_fn = rssi_to_color
    for ev in evaluations:
        sx, sy = viewport.world_to_screen(ev.point)
        cx = sx - x1f
        cy = sy - y1f
        if metric == "snr":
            value = ev.snr_db
        elif metric == HEATMAP_METRIC_INTERFERENCE:
            # None ⇒ sin contribuidores (color de «sin interferencia»).
            value = ev.interference_dbm
        else:
            value = ev.rx_power_dbm
        color = color_fn(value, alpha=alpha)
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

    # Fase 7: bloque SNR solo si las stats lo traen (los resultados
    # sintéticos antiguos no lo tienen; la presencia es el contrato).
    if "snr_min_db" in stats:
        lines.extend(
            [
                "",
                "SNR (dB):",
                f"  mínimo: {stats['snr_min_db']:.2f} dB",
                f"  máximo: {stats['snr_max_db']:.2f} dB",
                f"  promedio: {stats['snr_avg_db']:.2f} dB",
                (
                    f"  ≥ objetivo {stats.get('snr_target_db', 0):g} dB: "
                    f"{100.0 * stats.get('snr_ratio', 0.0):.1f}% "
                    f"({int(stats.get('points_meeting_snr_target', 0))})"
                ),
            ]
        )

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
