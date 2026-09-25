"""Lienzo del editor 2D: dibuja el Project y gestiona la interacción.

La fuente de verdad es Session.project (Project + Floor activo); el
Canvas la consume como vista de solo lectura (session.geometry_view).
No contiene fórmulas RF.

Fase 8: dibuja espacios (zonas semitransparentes) y openings
(puertas/ventanas/pass-through) como huecos coloreados en las paredes.

Fase 9: dibuja obstáculos de mobiliario (footprints semisólidos entre
espacios y paredes) con herramienta de 2 clics, arrastre y selección
en el orden AP → Cliente → Opening → Obstáculo → Pared → Espacio.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.geometry import Point2D, Segment2D
from core.wall import group_openings_by_wall, wall_point_at_offset
from ui import theme
from ui.session import EditorSession, SelectionKind, Tool, snap_point_to_grid
from ui.viewport import Viewport

OPENING_COLORS = {
    "door": theme.DOOR_COLOR,
    "window": theme.WINDOW_COLOR,
    "pass_through": theme.PASS_THROUGH_COLOR,
}


class EditorCanvas(tk.Canvas):
    """Canvas con herramientas: seleccionar, pared, AP, cliente.

    Snap sencillo: extremos de paredes + eje horizontal/vertical.
    Coordenadas del modelo siempre en metros (vía Viewport).
    """

    HIT_RADIUS_PX = 8
    SNAP_RADIUS_PX = 10
    #: Factor de zoom por paso de rueda (Fase 14-E).
    ZOOM_STEP = 1.25

    def __init__(
        self,
        master,
        session: EditorSession,
        viewport: Viewport,
        on_model_changed: Callable[[], None],
        on_cursor: Callable[[float, float], None],
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", theme.BG_CANVAS)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, **kwargs)
        self.session = session
        self.viewport = viewport
        self.on_model_changed = on_model_changed
        self.on_cursor = on_cursor

        self._drag_ap_id: str | None = None
        self._drag_client_id: str | None = None
        # Fase 9: arrastre de obstáculo (id + desfase del cursor al corner).
        self._drag_obstacle_id: str | None = None
        self._drag_obstacle_offset: Point2D = Point2D(0.0, 0.0)
        # Fase 14-D: arrastre de pared (entera o por extremo) y de espacio.
        self._drag_wall_id: str | None = None
        self._drag_wall_offset: Point2D = Point2D(0.0, 0.0)
        self._drag_wall_endpoint: tuple[str, str] | None = None
        self._drag_space_id: str | None = None
        self._drag_space_offset: Point2D = Point2D(0.0, 0.0)
        # Fase 14-E: último punto del arrastre de pan (botón central).
        self._pan_last: tuple[float, float] | None = None
        self._preview_end: Point2D | None = None
        # Imagen PIL del heatmap (se re-aplica tras cada render completo).
        self._heatmap_image = None
        # Referencia viva a la PhotoImage de Tk (evita GC).
        self._heatmap_photo = None

        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        # Fase 14-E: zoom con rueda y pan con botón central.
        self.bind("<MouseWheel>", self._on_mousewheel)
        self.bind("<Button-4>", self._on_wheel_up)
        self.bind("<Button-5>", self._on_wheel_down)
        self.bind("<ButtonPress-2>", self._on_pan_press)
        self.bind("<B2-Motion>", self._on_pan_motion)
        self.bind("<ButtonRelease-2>", self._on_pan_release)
        self.bind("<Delete>", self._on_delete_key)
        self.bind("<BackSpace>", self._on_delete_key)
        self.focus_set()

    # ------------------------------------------------------------------
    # Configuración / render
    # ------------------------------------------------------------------

    def _on_configure(self, _event) -> None:
        self.viewport.set_canvas_size(self.winfo_width(), self.winfo_height())
        self.render_project()

    def clear_heatmap(self) -> None:
        """Elimina la capa del heatmap (resultado invalidado)."""
        self.delete("heatmap")
        self._heatmap_image = None
        self._heatmap_photo = None

    def reset_interaction(self) -> None:
        """Limpia el estado transitorio del puntero (cambio de documento)."""
        self._drag_ap_id = None
        self._drag_client_id = None
        self._drag_obstacle_id = None
        self._drag_wall_id = None
        self._drag_wall_endpoint = None
        self._drag_space_id = None
        self._pan_last = None
        self._preview_end = None

    def draw_heatmap(self, image) -> None:
        """Dibuja la imagen Pillow del heatmap bajo las entidades.

        Args:
            image: Imagen RGBA (PIL) del área del piso, o None para limpiar.
        """
        self._heatmap_image = image
        self._place_heatmap_item()

    def _place_heatmap_item(self) -> None:
        """Inserta la imagen del heatmap como capa intermedia y rebaja su z-order."""
        self.delete("heatmap")
        self._heatmap_photo = None
        if self._heatmap_image is None:
            return
        from PIL import Image, ImageTk

        x1, y1, x2, y2 = self.viewport.floor_rect_px
        # La imagen se generó a la escala del momento; al hacer zoom/pan
        # se reescala al rect del piso actual (Fase 14-E).
        target = (max(int(round(x2 - x1)), 1), max(int(round(y2 - y1)), 1))
        image = self._heatmap_image
        if image.size != target:
            image = image.resize(target, Image.BILINEAR)
        self._heatmap_photo = ImageTk.PhotoImage(image)
        # tag "heatmap": capa intermedia; no interfiere con hit-testing
        # (la selección usa coordenadas de mundo, no ids de Canvas).
        self.create_image(x1, y1, image=self._heatmap_photo, anchor="nw", tags=("heatmap",))
        self.tag_lower("heatmap")

    def render_project(self) -> None:
        """Redibuja todo el Canvas desde el Project (fuente de verdad).

        El heatmap (si existe) se conserva como imagen PIL y se re-coloca
        por encima del fondo, debajo de paredes/APs/clientes.
        """
        self.delete("all")
        self._heatmap_photo = None
        vp = self.viewport

        # Ajustar viewport al piso actual
        vp.set_world_size(self.session.floor_width_m, self.session.floor_height_m)

        # 1) Rejilla + rect del piso (fondo)
        self._draw_grid()
        self._draw_floor_rect()

        # 2) Heatmap (capa intermedia, bajo las entidades)
        self._place_heatmap_item()

        # 2b) Espacios (zonas organizativas, bajo las paredes)
        self._draw_spaces()

        # 2c) Obstáculos de mobiliario (Fase 9): sobre espacios, bajo
        # paredes (el plano estructural manda en la intersección visual).
        self._draw_obstacles()

        # 3) Paredes (con huecos de openings) + openings encima
        self._draw_walls()

        # Vista previa de pared en curso
        if self.session.tool == Tool.WALL and self.session.wall_drag_start is not None:
            if self._preview_end is not None:
                sx1, sy1 = vp.world_to_screen(self.session.wall_drag_start)
                sx2, sy2 = vp.world_to_screen(self._preview_end)
                self.create_line(
                    sx1, sy1, sx2, sy2,
                    fill=theme.WALL_PREVIEW, width=2, dash=(4, 3),
                )

        # Vista previa de espacio en curso (rect punteado entre 2 esquinas)
        if self.session.tool == Tool.SPACE and self.session.space_drag_start is not None:
            if self._preview_end is not None:
                sx1, sy1 = vp.world_to_screen(self.session.space_drag_start)
                sx2, sy2 = vp.world_to_screen(self._preview_end)
                self.create_rectangle(
                    min(sx1, sx2), min(sy1, sy2), max(sx1, sx2), max(sy1, sy2),
                    outline=theme.SPACE_PREVIEW, width=2, dash=(4, 3),
                )

        # Vista previa de obstáculo en curso (Fase 9, patrón de 2 clics)
        if (
            self.session.tool == Tool.OBSTACLE
            and self.session.obstacle_drag_start is not None
        ):
            if self._preview_end is not None:
                sx1, sy1 = vp.world_to_screen(self.session.obstacle_drag_start)
                sx2, sy2 = vp.world_to_screen(self._preview_end)
                self.create_rectangle(
                    min(sx1, sx2), min(sy1, sy2), max(sx1, sx2), max(sy1, sy2),
                    fill="", outline=theme.OBSTACLE_PREVIEW, width=2, dash=(4, 3),
                )

        # Fase 14-F: medición en curso (línea punteada + distancia en metros).
        if self.session.tool == Tool.MEASURE and self.session.measure_anchor is not None:
            cursor = self.session.measure_cursor or self.session.measure_anchor
            a = vp.world_to_screen(self.session.measure_anchor)
            b = vp.world_to_screen(cursor)
            self.create_line(
                a[0], a[1], b[0], b[1],
                fill=theme.MEASURE_COLOR, width=2, dash=(6, 4),
            )
            distance = self.session.measure_distance_m()
            if distance is not None:
                self.create_text(
                    (a[0] + b[0]) / 2.0,
                    (a[1] + b[1]) / 2.0 - 14,
                    text=f"{distance:.2f} m",
                    fill=theme.MEASURE_COLOR,
                    font=("Segoe UI", 10, "bold"),
                )

        # 4) APs / clientes (siempre visibles sobre el heatmap)
        self._draw_aps_and_clients()

        # 5) Leyenda de cobertura
        self._draw_legend()

    def _draw_floor_rect(self) -> None:
        vp = self.viewport
        x1, y1, x2, y2 = vp.floor_rect_px
        self.create_rectangle(
            x1, y1, x2, y2,
            fill=theme.FLOOR_FILL, outline=theme.FLOOR_OUTLINE, width=2,
        )
        w, h = self.session.floor_width_m, self.session.floor_height_m
        self.create_text(
            (x1 + x2) / 2, y1 - 14,
            text=f"{w:g} m", fill=theme.TEXT_DIM, font=("Segoe UI", 9),
        )
        self.create_text(
            x1 - 18, (y1 + y2) / 2,
            text=f"{h:g} m", fill=theme.TEXT_DIM, font=("Segoe UI", 9),
        )

    def _draw_spaces(self) -> None:
        """Espacios como rect semitransparente con nombre (fase 8)."""
        vp = self.viewport
        selected = self.session.selection
        view = self.session.geometry_view
        for space in view.spaces:
            rect = space.rect
            x1, y1 = vp.world_to_screen(Point2D(rect.x, rect.y))
            x2, y2 = vp.world_to_screen(Point2D(rect.x + rect.width, rect.y + rect.height))
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.SPACE
                and selected.entity_id == space.id
            )
            self.create_rectangle(
                min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2),
                fill=theme.SPACE_FILL,
                outline=theme.SPACE_SELECTED if is_sel else theme.SPACE_OUTLINE,
                width=3 if is_sel else 1,
                stipple="gray25",
            )
            self.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=space.name, fill=theme.TEXT_DIM, font=("Segoe UI", 8),
            )

    def _draw_obstacles(self) -> None:
        """Obstáculos de mobiliario (Fase 9): footprint semisólido + nombre."""
        vp = self.viewport
        selected = self.session.selection
        view = self.session.geometry_view
        for obstacle in view.obstacles:
            rect = obstacle.rect
            x1, y1 = vp.world_to_screen(Point2D(rect.x, rect.y))
            x2, y2 = vp.world_to_screen(
                Point2D(rect.x + rect.width, rect.y + rect.height)
            )
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.OBSTACLE
                and selected.entity_id == obstacle.id
            )
            self.create_rectangle(
                min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2),
                fill=theme.OBSTACLE_FILL,
                outline=theme.OBSTACLE_SELECTED if is_sel else theme.OBSTACLE_OUTLINE,
                width=3 if is_sel else 1,
                stipple="gray50",
            )
            self.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=obstacle.name, fill=theme.TEXT_LABEL, font=("Segoe UI", 8),
            )

    def _draw_walls(self) -> None:
        """Paredes con huecos a la altura de sus openings + marcas de opening.

        Los openings se dibujan como un segmento de color (puerta/ventana/
        pass-through) sobre el hueco; el resto de la pared es segmento sólido.
        """
        vp = self.viewport
        selected = self.session.selection
        view = self.session.geometry_view
        openings_by_wall = group_openings_by_wall(view.openings)
        for wall in view.walls:
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.WALL
                and selected.entity_id == wall.id
            )
            color = theme.WALL_SELECTED if is_sel else theme.WALL_COLOR
            width = 4 if is_sel else 3
            length = wall.segment.length

            # Segmentos sólidos: fuera de los huecos.
            covered = openings_by_wall.get(wall.id, ())
            cursor = 0.0
            for opening in covered:
                gap_start = max(opening.start_offset_m, 0.0)
                gap_end = min(opening.end_offset_m, length)
                if gap_start > cursor:
                    self._draw_wall_span(wall, cursor, gap_start, color, width)
                cursor = max(cursor, gap_end)
            if cursor < length:
                self._draw_wall_span(wall, cursor, length, color, width)

            # Marca de cada opening (encima del hueco).
            for opening in covered:
                is_open_sel = (
                    selected is not None
                    and selected.kind == SelectionKind.OPENING
                    and selected.entity_id == opening.id
                )
                o_color = (
                    theme.OPENING_SELECTED if is_open_sel
                    else OPENING_COLORS.get(opening.kind, theme.WALL_COLOR)
                )
                sx1, sy1 = vp.world_to_screen(
                    wall_point_at_offset(wall, opening.start_offset_m)
                )
                sx2, sy2 = vp.world_to_screen(
                    wall_point_at_offset(wall, opening.end_offset_m)
                )
                self.create_line(
                    sx1, sy1, sx2, sy2,
                    fill=o_color, width=5 if is_open_sel else 4,
                    capstyle="round",
                )

            # Etiqueta de material en el centro de la pared.
            mx, my = vp.world_to_screen(
                Point2D(
                    (wall.segment.start.x + wall.segment.end.x) / 2,
                    (wall.segment.start.y + wall.segment.end.y) / 2,
                )
            )
            self.create_text(
                mx, my - 10, text=wall.material.id,
                fill=theme.TEXT_DIM, font=("Segoe UI", 7),
            )

            if is_sel:
                # Manijas en los extremos: avisan de que se pueden arrastrar
                # (mismo radio que ``_hit_wall_endpoint``) — Fase 15.
                half = 4
                for endpoint in (wall.segment.start, wall.segment.end):
                    ex, ey = vp.world_to_screen(endpoint)
                    self.create_rectangle(
                        ex - half, ey - half, ex + half, ey + half,
                        fill=theme.ACCENT, outline=theme.BG_CANVAS, width=1,
                    )

    def _draw_wall_span(
        self, wall, from_m: float, to_m: float, color: str, width: int
    ) -> None:
        """Dibuja un tramo de pared entre dos offsets métricos."""
        vp = self.viewport
        start = wall_point_at_offset(wall, from_m)
        end = wall_point_at_offset(wall, to_m)
        sx1, sy1 = vp.world_to_screen(start)
        sx2, sy2 = vp.world_to_screen(end)
        self.create_line(sx1, sy1, sx2, sy2, fill=color, width=width, capstyle="round")

    def _draw_aps_and_clients(self) -> None:
        vp = self.viewport
        selected = self.session.selection
        view = self.session.geometry_view
        for ap in view.access_points:
            sx, sy = vp.world_to_screen(ap.position)
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.AP
                and selected.entity_id == ap.id
            )
            self._draw_ap(
                sx,
                sy,
                theme.AP_SELECTED if is_sel else theme.AP_COLOR,
                ap.id,
                subtitle=(
                    f"CH {ap.channel} · {ap.radio.channel_width_mhz:g} MHz"
                    if ap.channel is not None
                    else ""
                ),
            )
            if is_sel:
                # Anillo de selección: el cambio de tono solo no basta
                # para ver qué AP está activo (Fase 15).
                ring = 16
                self.create_oval(
                    sx - ring, sy - ring, sx + ring, sy + ring,
                    outline=theme.ACCENT, width=2, dash=(4, 3),
                )

        for client in view.clients:
            sx, sy = vp.world_to_screen(client.position)
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.CLIENT
                and selected.entity_id == client.id
            )
            r = 7 if is_sel else 5
            color = theme.CLIENT_SELECTED if is_sel else theme.CLIENT_COLOR
            self.create_oval(
                sx - r, sy - r, sx + r, sy + r,
                fill=color, outline=theme.BG_CANVAS, width=1,
            )
            self.create_text(
                sx, sy + 14, text=client.id,
                fill=theme.TEXT_LABEL, font=("Segoe UI", 7),
            )

    def _draw_legend(self) -> None:
        """Leyenda de cobertura/SNR (umbrales del modelo, no mágicos)."""
        from ui.coverage_renderer import legend_rows, legend_title

        metric = getattr(self.session, "heatmap_metric", "rssi")
        rows = legend_rows(self.session.project.thresholds, metric=metric)
        x, y = 12, 12
        width, row_h = 148, 16
        height = 22 + row_h * len(rows) + 6

        self.create_rectangle(
            x, y, x + width, y + height,
            fill="#1a1a28", outline=theme.FLOOR_OUTLINE, stipple="gray50",
        )
        self.create_text(
            x + 8, y + 12, anchor="w",
            text=legend_title(metric), fill=theme.FG, font=("Segoe UI", 9, "bold"),
        )
        yy = y + 26
        for row in rows:
            r, g, b = row["color"]
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            self.create_rectangle(x + 8, yy, x + 20, yy + 10, fill=hex_color, outline="")
            self.create_text(
                x + 26, yy + 5, anchor="w",
                text=f"{row['label']} {row['range']}",
                fill=theme.FG_DIM, font=("Segoe UI", 7),
            )
            yy += row_h

    def _draw_grid(self) -> None:
        vp = self.viewport
        step_m = self.session.grid_step_m
        w, h = self.session.floor_width_m, self.session.floor_height_m
        # Pasos muy finos con la vista alejada saturarían el lienzo:
        # se dobla el paso (solo visual) hasta un máximo razonable.
        while step_m > 0 and (w / step_m > 300 or h / step_m > 300):
            step_m *= 2
        x = 0.0
        while x <= w + 1e-9:
            sx1, sy1 = vp.world_to_screen(Point2D(x, 0))
            sx2, sy2 = vp.world_to_screen(Point2D(x, h))
            self.create_line(sx1, sy1, sx2, sy2, fill=theme.GRID_COLOR)
            x += step_m
        y = 0.0
        while y <= h + 1e-9:
            sx1, sy1 = vp.world_to_screen(Point2D(0, y))
            sx2, sy2 = vp.world_to_screen(Point2D(w, y))
            self.create_line(sx1, sy1, sx2, sy2, fill=theme.GRID_COLOR)
            y += step_m

    def _draw_ap(
        self, x: float, y: float, color: str, label: str, subtitle: str = ""
    ) -> None:
        # Marcas tipo antena
        for dx, dy in ((-10, -10), (10, -10), (-10, 10), (10, 10), (0, -12), (0, 12)):
            self.create_line(x, y, x + dx, y + dy, fill=color, width=1)
        r = 6
        self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=theme.BG_CANVAS)
        self.create_text(x, y + 18, text=label, fill=theme.TEXT_LABEL, font=("Segoe UI", 7))
        # Fase 10: canal/ancho SOLO si el AP tiene canal configurado (BU).
        if subtitle:
            self.create_text(
                x, y + 30, text=subtitle, fill=theme.TEXT_LABEL, font=("Segoe UI", 6)
            )

    # ------------------------------------------------------------------
    # Snap
    # ------------------------------------------------------------------

    def _snap_world(self, world: Point2D) -> Point2D:
        """Snap a extremos de paredes y a ejes H/V desde el inicio del trazo."""
        vp = self.viewport
        # 1) Extremos existentes
        for wall in self.session.geometry_view.walls:
            for endpoint in (wall.segment.start, wall.segment.end):
                ex, ey = vp.world_to_screen(endpoint)
                wx, wy = vp.world_to_screen(world)
                if (ex - wx) ** 2 + (ey - wy) ** 2 <= self.SNAP_RADIUS_PX ** 2:
                    return endpoint

        # 2) Ejes H/V respecto al inicio del trazo (pared, espacio u obstáculo)
        start = (
            self.session.wall_drag_start
            or self.session.space_drag_start
            or self.session.obstacle_drag_start
        )
        if start is not None:
            # Umbral en metros equivalente a SNAP_RADIUS_PX
            tol_m = self.SNAP_RADIUS_PX / max(vp.scale, 1e-9)
            if abs(world.y - start.y) <= tol_m and abs(world.x - start.x) > tol_m:
                return Point2D(world.x, start.y)  # horizontal
            if abs(world.x - start.x) <= tol_m and abs(world.y - start.y) > tol_m:
                return Point2D(start.x, world.y)  # vertical

        # 3) Rejilla (Fase 14-E): redondeo al paso configurado. Va después
        # de extremos/ejes para no deshacer esos snaps más precisos.
        if self.session.snap_to_grid:
            return snap_point_to_grid(world, self.session.grid_step_m)
        return world

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def _hit_wall_endpoint(self, world: Point2D, wall_id: str) -> str | None:
        """'start'/'end' si el cursor está sobre un extremo de la pared."""
        wall = self.session.find_wall(wall_id)
        if wall is None:
            return None
        vp = self.viewport
        wx, wy = vp.world_to_screen(world)
        for name, endpoint in (
            ("start", wall.segment.start),
            ("end", wall.segment.end),
        ):
            ex, ey = vp.world_to_screen(endpoint)
            if (ex - wx) ** 2 + (ey - wy) ** 2 <= self.SNAP_RADIUS_PX ** 2:
                return name
        return None

    def _hit_test(self, world: Point2D):
        """Devuelve (SelectionKind, id) del elemento bajo el cursor o None."""
        vp = self.viewport
        wx, wy = vp.world_to_screen(world)
        radius = self.HIT_RADIUS_PX
        view = self.session.geometry_view

        # APs y clientes primero (hit más preciso)
        for ap in reversed(view.access_points):
            ax, ay = vp.world_to_screen(ap.position)
            if (ax - wx) ** 2 + (ay - wy) ** 2 <= (radius + 4) ** 2:
                return SelectionKind.AP, ap.id
        for client in reversed(view.clients):
            cx, cy = vp.world_to_screen(client.position)
            if (cx - wx) ** 2 + (cy - wy) ** 2 <= radius ** 2:
                return SelectionKind.CLIENT, client.id

        # Openings ANTES que sus paredes (un hueco es un sub-elemento de la
        # pared; si el clic cae en el hueco, hay que seleccionar el opening).
        for opening in reversed(view.openings):
            wall = self.session.find_wall(opening.wall_id)
            if wall is None:
                continue
            sx, sy = vp.world_to_screen(
                wall_point_at_offset(wall, opening.start_offset_m)
            )
            ex, ey = vp.world_to_screen(
                wall_point_at_offset(wall, opening.end_offset_m)
            )
            if self._point_segment_dist_px(wx, wy, sx, sy, ex, ey) <= radius:
                return SelectionKind.OPENING, opening.id

        # Obstáculos (Fase 9): por encima de paredes/espacios porque
        # representan mobiliario a pie de plano; un AP/cliente siguen
        # mandando (hit más preciso arriba).
        for obstacle in reversed(view.obstacles):
            rect = obstacle.rect
            x1, y1 = vp.world_to_screen(Point2D(rect.x, rect.y))
            x2, y2 = vp.world_to_screen(
                Point2D(rect.x + rect.width, rect.y + rect.height)
            )
            if (
                min(x1, x2) - radius <= wx <= max(x1, x2) + radius
                and min(y1, y2) - radius <= wy <= max(y1, y2) + radius
            ):
                return SelectionKind.OBSTACLE, obstacle.id

        # Paredes: distancia punto-segmento en píxeles
        for wall in reversed(view.walls):
            sx, sy = vp.world_to_screen(wall.segment.start)
            ex, ey = vp.world_to_screen(wall.segment.end)
            if self._point_segment_dist_px(wx, wy, sx, sy, ex, ey) <= radius:
                return SelectionKind.WALL, wall.id

        # Espacios (rect): por debajo de paredes/openings (el plano es
        # organizativo; la geometría estructural manda).
        for space in reversed(view.spaces):
            rect = space.rect
            x1, y1 = vp.world_to_screen(Point2D(rect.x, rect.y))
            x2, y2 = vp.world_to_screen(
                Point2D(rect.x + rect.width, rect.y + rect.height)
            )
            if (
                min(x1, x2) - radius <= wx <= max(x1, x2) + radius
                and min(y1, y2) - radius <= wy <= max(y1, y2) + radius
            ):
                return SelectionKind.SPACE, space.id
        return None

    @staticmethod
    def _point_segment_dist_px(
        px: float, py: float, x1: float, y1: float, x2: float, y2: float
    ) -> float:
        dx, dy = x2 - x1, y2 - y1
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-12:
            return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
        qx, qy = x1 + t * dx, y1 + t * dy
        return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    def _cursor_world(self, event) -> Point2D:
        return self.viewport.screen_to_world(event.x, event.y)

    # ------------------------------------------------------------------
    # Zoom / pan (Fase 14-E): solo cambian la vista, nunca el modelo
    # ------------------------------------------------------------------

    def _zoom_by_at(self, factor: float, x_px: float, y_px: float) -> None:
        self.viewport.zoom_at(factor, x_px, y_px)
        self.render_project()

    def _on_mousewheel(self, event) -> None:
        if getattr(event, "delta", 0) == 0:
            return
        factor = self.ZOOM_STEP if event.delta > 0 else 1.0 / self.ZOOM_STEP
        self._zoom_by_at(factor, event.x, event.y)

    def _on_wheel_up(self, event) -> None:
        self._zoom_by_at(self.ZOOM_STEP, event.x, event.y)

    def _on_wheel_down(self, event) -> None:
        self._zoom_by_at(1.0 / self.ZOOM_STEP, event.x, event.y)

    def _on_pan_press(self, event) -> None:
        self._pan_last = (event.x, event.y)

    def _on_pan_motion(self, event) -> None:
        if self._pan_last is None:
            return
        dx = event.x - self._pan_last[0]
        dy = event.y - self._pan_last[1]
        self._pan_last = (event.x, event.y)
        self.viewport.pan_by(dx, dy)
        self.render_project()

    def _on_pan_release(self, _event) -> None:
        self._pan_last = None

    def _on_motion(self, event) -> None:
        world = self._cursor_world(event)
        self.on_cursor(world.x, world.y)

        # Fase 14-F: la medición sigue al cursor (en metros, con snap).
        if (
            self.session.tool == Tool.MEASURE
            and self.session.measure_anchor is not None
        ):
            self.session.set_measure_cursor(self._snap_world(world))
            self.render_project()

        if self.session.tool == Tool.WALL and self.session.wall_drag_start is not None:
            self._preview_end = self._snap_world(world)
            self.render_project()
        elif self.session.tool == Tool.SPACE and self.session.space_drag_start is not None:
            self._preview_end = self._snap_world(world)
            self.render_project()
        elif (
            self.session.tool == Tool.OBSTACLE
            and self.session.obstacle_drag_start is not None
        ):
            self._preview_end = self._snap_world(world)
            self.render_project()

        # Arrastre de AP / cliente: solo repinta el plano; el heatmap se
        # invalida en el modelo y se recalcula al soltar (debounce en App).
        if self._drag_ap_id:
            self.session.move_ap(self._drag_ap_id, self._snap_world(world))
            self.clear_heatmap()
            self.render_project()
        elif self._drag_client_id:
            self.session.move_client(self._drag_client_id, self._snap_world(world))
            self.render_project()
        elif self._drag_obstacle_id:
            # Mismo patrón que el AP: repinta sin heatmap durante el
            # arrastre; el modelo ya invalidó y App hace debounce.
            target = Point2D(
                world.x - self._drag_obstacle_offset.x,
                world.y - self._drag_obstacle_offset.y,
            )
            self.session.move_obstacle(self._drag_obstacle_id, target)
            self.clear_heatmap()
            self.render_project()
        # Fase 14-D: edición de pared (extremo o traslación) y espacios.
        elif self._drag_wall_endpoint is not None:
            wall_id, which = self._drag_wall_endpoint
            wall = self.session.find_wall(wall_id)
            if wall is not None:
                target = self._snap_world(world)
                start, end = wall.segment.start, wall.segment.end
                try:
                    self.session.set_wall_endpoints(
                        wall_id,
                        target if which == "start" else start,
                        start if which == "end" else end,
                    )
                except ValueError:
                    # Protección de openings: frame inválido, se ignora.
                    pass
                self.clear_heatmap()
                self.render_project()
        elif self._drag_wall_id:
            wall = self.session.find_wall(self._drag_wall_id)
            if wall is not None:
                new_start = Point2D(
                    world.x - self._drag_wall_offset.x,
                    world.y - self._drag_wall_offset.y,
                )
                delta = Point2D(
                    new_start.x - wall.segment.start.x,
                    new_start.y - wall.segment.start.y,
                )
                try:
                    self.session.move_wall(self._drag_wall_id, delta)
                except ValueError:
                    pass
                self.clear_heatmap()
                self.render_project()
        elif self._drag_space_id:
            space = next(
                (
                    item
                    for item in self.session.geometry_view.spaces
                    if item.id == self._drag_space_id
                ),
                None,
            )
            if space is not None:
                target_x = world.x - self._drag_space_offset.x
                target_y = world.y - self._drag_space_offset.y
                try:
                    self.session.move_space(
                        self._drag_space_id,
                        Point2D(target_x - space.rect.x, target_y - space.rect.y),
                    )
                except ValueError:
                    pass
                self.render_project()

    def _on_press(self, event) -> None:
        # Un press SIEMPRE arranca un gesto nuevo: si el release anterior
        # no llegó (ventana desactivada, doble click, etc.) cerramos el
        # gesto pendiente y descartamos los flags de arrastre viejos, para
        # que no secuestren este movimiento y se mueva otro objeto (F15).
        self.session.commit_edit()
        self.reset_interaction()
        world = self._snap_world(self._cursor_world(event))
        tool = self.session.tool

        if tool == Tool.SELECT:
            hit = self._hit_test(world)
            if hit is None:
                self.session.select(None, None)
                self.on_model_changed()
                return
            kind, entity_id = hit
            self.session.select(kind, entity_id)
            if kind == SelectionKind.AP:
                self._drag_ap_id = entity_id
            elif kind == SelectionKind.CLIENT:
                self._drag_client_id = entity_id
            elif kind == SelectionKind.OBSTACLE:
                obstacle = self.session.selected_obstacle()
                if obstacle is not None:
                    self._drag_obstacle_id = entity_id
                    self._drag_obstacle_offset = Point2D(
                        world.x - obstacle.rect.x, world.y - obstacle.rect.y
                    )
            elif kind == SelectionKind.WALL:
                # Fase 14-D: primero el extremo más cercano; si no, la
                # pared entera se traslada arrastrando.
                endpoint = self._hit_wall_endpoint(world, entity_id)
                if endpoint is not None:
                    self._drag_wall_endpoint = (entity_id, endpoint)
                else:
                    wall = self.session.selected_wall()
                    if wall is not None:
                        self._drag_wall_id = entity_id
                        self._drag_wall_offset = Point2D(
                            world.x - wall.segment.start.x,
                            world.y - wall.segment.start.y,
                        )
            elif kind == SelectionKind.SPACE:
                space = self.session.selected_space()
                if space is not None:
                    self._drag_space_id = entity_id
                    self._drag_space_offset = Point2D(
                        world.x - space.rect.x, world.y - space.rect.y
                    )
            if (
                self._drag_ap_id
                or self._drag_client_id
                or self._drag_obstacle_id
                or self._drag_wall_id
                or self._drag_wall_endpoint
                or self._drag_space_id
            ):
                # Fase 14.1: el arrastre completo será UN solo paso de undo.
                self.session.begin_edit()
            self.on_model_changed()
            return

        if tool == Tool.MEASURE:
            # Fase 14-F: cada clic fija un nuevo punto de partida.
            self.session.set_measure_anchor(world)
            self.render_project()
            self.on_model_changed()
            return

        if tool == Tool.WALL:
            if self.session.wall_drag_start is None:
                self.session.wall_drag_start = world
                self._preview_end = world
            else:
                try:
                    self.session.add_wall(self.session.wall_drag_start, world)
                except ValueError:
                    pass
                self.session.wall_drag_start = None
                self._preview_end = None
                # Permite seguir encadenando paredes desde el último punto
                # (se reinicia; el usuario vuelve a clicar).
            self.render_project()
            self.on_model_changed()
            return

        if tool == Tool.SPACE:
            # Dos clics como la pared: esquina inicial → esquina opuesta.
            if self.session.space_drag_start is None:
                self.session.space_drag_start = world
                self._preview_end = world
            else:
                try:
                    self.session.add_space(self.session.space_drag_start, world)
                except ValueError:
                    pass
                self.session.space_drag_start = None
                self._preview_end = None
            self.render_project()
            self.on_model_changed()
            return

        if tool == Tool.OBSTACLE:
            # Fase 9: mismo patrón de 2 clics que espacio/pared.
            if self.session.obstacle_drag_start is None:
                self.session.obstacle_drag_start = world
                self._preview_end = world
            else:
                try:
                    self.session.add_obstacle(
                        self.session.obstacle_drag_start, world
                    )
                except ValueError:
                    pass
                self.session.obstacle_drag_start = None
                self._preview_end = None
                # Mismo patrón que SPACE: se queda en la herramienta
                # para encadenar; Escape/SELECT para salir.
            self.render_project()
            self.on_model_changed()
            return

        if self.session.tool == Tool.AP:
            self.session.add_access_point(world)
            self.session.set_tool(Tool.SELECT)
            self.render_project()
            self.on_model_changed()
            return

        if tool == Tool.CLIENT:
            self.session.add_client(world)
            self.session.set_tool(Tool.SELECT)
            self.render_project()
            self.on_model_changed()
            return

    def _on_drag(self, _event) -> None:
        # El movimiento se procesa en _on_motion (B1-Motion también dispara Motion).
        pass

    def _on_release(self, _event) -> None:
        if (
            self._drag_ap_id
            or self._drag_client_id
            or self._drag_obstacle_id
            or self._drag_wall_id
            or self._drag_wall_endpoint
            or self._drag_space_id
        ):
            # Fase 14.1: cierra el gesto ⇒ UNA sola entrada de historial
            # para todo el movimiento (o ninguna si no hubo cambio real).
            self.session.commit_edit()
            self._drag_ap_id = None
            self._drag_client_id = None
            self._drag_obstacle_id = None
            self._drag_wall_id = None
            self._drag_wall_endpoint = None
            self._drag_space_id = None
            self.on_model_changed()

    def _on_delete_key(self, _event) -> str:
        if self.session.delete_selection():
            self.render_project()
            self.on_model_changed()
        return "break"
