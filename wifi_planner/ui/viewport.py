"""Conversión metros ↔ píxeles (EXCLUSIVO de la capa UI).

El modelo de dominio almacena SIEMPRE metros. Los píxeles solo existen
aquí y en el Canvas. La escala es isotrópica: 1 metro = N píxeles en
ambos ejes (corrige el escalado anisotrópico del legacy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.geometry import Point2D

#: Límites del zoom (multiplicador sobre el ajuste al lienzo) — Fase 14-E.
MIN_ZOOM: float = 0.1
MAX_ZOOM: float = 20.0


@dataclass
class Viewport:
    """Convierte coordenadas del mundo (metros) a pantalla (píxeles).

    Origen del mundo: esquina superior izquierda del área del piso;
    X crece a la derecha, Y crece hacia abajo (misma orientación que
    Canvas de Tk). Escala uniforme en X e Y.

    Attributes:
        world_width_m: Ancho del espacio físico en metros (> 0).
        world_height_m: Alto del espacio físico en metros (> 0).
        canvas_width_px: Ancho actual del lienzo en píxeles.
        canvas_height_px: Alto actual del lienzo en píxeles.
        margin_px: Margen en píxeles alrededor del rectángulo del piso.
        zoom: Multiplicador de escala (1.0 = ajuste al lienzo; Fase 14-E).
        pan_x_px: Desplazamiento horizontal de la vista en píxeles.
        pan_y_px: Desplazamiento vertical de la vista en píxeles.
    """

    world_width_m: float = 12.0
    world_height_m: float = 8.0
    canvas_width_px: int = 800
    canvas_height_px: int = 600
    margin_px: int = 40
    zoom: float = 1.0
    pan_x_px: float = 0.0
    pan_y_px: float = 0.0

    def __post_init__(self) -> None:
        self._validate_world()
        self._validate_zoom()

    def _validate_world(self) -> None:
        if self.world_width_m <= 0 or self.world_height_m <= 0:
            raise ValueError(
                "Dimensiones del mundo deben ser > 0 metros "
                f"(got {self.world_width_m} x {self.world_height_m})."
            )

    def _validate_zoom(self) -> None:
        if not math.isfinite(self.zoom) or self.zoom <= 0:
            raise ValueError(f"Zoom debe ser finito y > 0 (got {self.zoom}).")

    def set_world_size(self, width_m: float, height_m: float) -> None:
        """Actualiza el tamaño físico (metros)."""
        if width_m <= 0 or height_m <= 0:
            raise ValueError(
                f"Dimensiones inválidas: {width_m} x {height_m} m."
            )
        self.world_width_m = float(width_m)
        self.world_height_m = float(height_m)

    def set_canvas_size(self, width_px: int, height_px: int) -> None:
        """Actualiza el tamaño del lienzo en píxeles (> 0)."""
        if width_px <= 0 or height_px <= 0:
            raise ValueError(
                f"Tamaño de lienzo inválido: {width_px} x {height_px}."
            )
        self.canvas_width_px = int(width_px)
        self.canvas_height_px = int(height_px)

    @property
    def scale(self) -> float:
        """Píxeles por metro (misma escala en X e Y). > 0."""
        usable_w = max(self.canvas_width_px - 2 * self.margin_px, 1)
        usable_h = max(self.canvas_height_px - 2 * self.margin_px, 1)
        scale_x = usable_w / self.world_width_m
        scale_y = usable_h / self.world_height_m
        return min(scale_x, scale_y) * self.zoom

    @property
    def origin_x_px(self) -> float:
        """Píxeles X del origen del mundo (0 m)."""
        drawn_w = self.world_width_m * self.scale
        return (self.canvas_width_px - drawn_w) / 2.0 + self.pan_x_px

    @property
    def origin_y_px(self) -> float:
        """Píxeles Y del origen del mundo (0 m)."""
        drawn_h = self.world_height_m * self.scale
        return (self.canvas_height_px - drawn_h) / 2.0 + self.pan_y_px

    # ------------------------------------------------------------------
    # Zoom / pan (Fase 14-E)
    # ------------------------------------------------------------------

    def zoom_at(self, factor: float, x_px: float, y_px: float) -> None:
        """Zoom multiplicativo manteniendo fijo el punto bajo el cursor.

        El ``factor`` se aplica al zoom actual y el resultado se recorta
        a ``[MIN_ZOOM, MAX_ZOOM]``. El desplazamiento (pan) se ajusta para
        que ``screen_to_world(x_px, y_px)`` devuelva el mismo punto que
        antes del zoom.

        Raises:
            ValueError: si el factor no es finito o es ≤ 0.
        """
        factor = float(factor)
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError(f"Factor de zoom inválido: {factor}.")
        new_zoom = min(max(self.zoom * factor, MIN_ZOOM), MAX_ZOOM)
        if new_zoom == self.zoom:
            return
        anchor = self.screen_to_world(x_px, y_px)
        self.zoom = new_zoom
        sx, sy = self.world_to_screen(anchor)
        self.pan_x_px += x_px - sx
        self.pan_y_px += y_px - sy

    def pan_by(self, dx_px: float, dy_px: float) -> None:
        """Desplaza la vista en píxeles (arrastrar botón central).

        Raises:
            ValueError: si los desplazamientos no son finitos.
        """
        dx, dy = float(dx_px), float(dy_px)
        if not (math.isfinite(dx) and math.isfinite(dy)):
            raise ValueError(f"Pan no finito: ({dx_px}, {dy_px}).")
        self.pan_x_px += dx
        self.pan_y_px += dy

    def reset_view(self) -> None:
        """Vista normal: zoom 1× (ajuste al lienzo) y pan en cero."""
        self.zoom = 1.0
        self.pan_x_px = 0.0
        self.pan_y_px = 0.0

    @property
    def floor_rect_px(self) -> tuple[float, float, float, float]:
        """Rect del piso en pantalla: (x1, y1, x2, y2)."""
        x1 = self.origin_x_px
        y1 = self.origin_y_px
        x2 = x1 + self.world_width_m * self.scale
        y2 = y1 + self.world_height_m * self.scale
        return (x1, y1, x2, y2)

    def world_to_screen(self, point: Point2D) -> tuple[float, float]:
        """Metros → píxeles (tuple x, y)."""
        sx = self.origin_x_px + point.x * self.scale
        sy = self.origin_y_px + point.y * self.scale
        return (sx, sy)

    def screen_to_world(self, x_px: float, y_px: float) -> Point2D:
        """Píxeles → metros (Point2D)."""
        x_m = (x_px - self.origin_x_px) / self.scale
        y_m = (y_px - self.origin_y_px) / self.scale
        return Point2D(x_m, y_m)

    def world_to_screen_len(self, length_m: float) -> float:
        """Longitud en metros → píxeles (misma escala que ejes)."""
        return length_m * self.scale
