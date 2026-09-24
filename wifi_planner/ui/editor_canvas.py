"""Lienzo del editor 2D: dibuja el Project y gestiona la interacción.

La fuente de verdad es Session.project. El Canvas solo representa.
No contiene fórmulas RF.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.geometry import Point2D, Segment2D
from ui import theme
from ui.session import EditorSession, SelectionKind, Tool
from ui.viewport import Viewport


class EditorCanvas(tk.Canvas):
    """Canvas con herramientas: seleccionar, pared, AP, cliente.

    Snap sencillo: extremos de paredes + eje horizontal/vertical.
    Coordenadas del modelo siempre en metros (vía Viewport).
    """

    HIT_RADIUS_PX = 8
    SNAP_RADIUS_PX = 10

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
        from PIL import ImageTk

        x1, y1, _x2, _y2 = self.viewport.floor_rect_px
        self._heatmap_photo = ImageTk.PhotoImage(self._heatmap_image)
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

        # 3) Paredes
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

    def _draw_walls(self) -> None:
        vp = self.viewport
        selected = self.session.selection
        for wall in self.session.floor.walls:
            sx1, sy1 = vp.world_to_screen(wall.segment.start)
            sx2, sy2 = vp.world_to_screen(wall.segment.end)
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.WALL
                and selected.entity_id == wall.id
            )
            color = theme.WALL_SELECTED if is_sel else theme.WALL_COLOR
            width = 4 if is_sel else 3
            self.create_line(sx1, sy1, sx2, sy2, fill=color, width=width, capstyle="round")
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

    def _draw_aps_and_clients(self) -> None:
        vp = self.viewport
        selected = self.session.selection
        for ap in self.session.project.access_points:
            sx, sy = vp.world_to_screen(ap.position)
            is_sel = (
                selected is not None
                and selected.kind == SelectionKind.AP
                and selected.entity_id == ap.id
            )
            self._draw_ap(sx, sy, theme.AP_SELECTED if is_sel else theme.AP_COLOR, ap.id)

        for client in self.session.project.clients:
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
        """Leyenda de cobertura (umbrales del modelo, no mágicos)."""
        from ui.coverage_renderer import legend_rows

        rows = legend_rows(self.session.project.thresholds)
        x, y = 12, 12
        width, row_h = 148, 16
        height = 22 + row_h * len(rows) + 6

        self.create_rectangle(
            x, y, x + width, y + height,
            fill="#1a1a28", outline=theme.FLOOR_OUTLINE, stipple="gray50",
        )
        self.create_text(
            x + 8, y + 12, anchor="w",
            text="Cobertura Wi-Fi", fill=theme.FG, font=("Segoe UI", 9, "bold"),
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
        step_m = 1.0
        w, h = self.session.floor_width_m, self.session.floor_height_m
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

    def _draw_ap(self, x: float, y: float, color: str, label: str) -> None:
        # Marcas tipo antena
        for dx, dy in ((-10, -10), (10, -10), (-10, 10), (10, 10), (0, -12), (0, 12)):
            self.create_line(x, y, x + dx, y + dy, fill=color, width=1)
        r = 6
        self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=theme.BG_CANVAS)
        self.create_text(x, y + 18, text=label, fill=theme.TEXT_LABEL, font=("Segoe UI", 7))

    # ------------------------------------------------------------------
    # Snap
    # ------------------------------------------------------------------

    def _snap_world(self, world: Point2D) -> Point2D:
        """Snap a extremos de paredes y a ejes H/V desde el inicio del trazo."""
        vp = self.viewport
        # 1) Extremos existentes
        for wall in self.session.floor.walls:
            for endpoint in (wall.segment.start, wall.segment.end):
                ex, ey = vp.world_to_screen(endpoint)
                wx, wy = vp.world_to_screen(world)
                if (ex - wx) ** 2 + (ey - wy) ** 2 <= self.SNAP_RADIUS_PX ** 2:
                    return endpoint

        # 2) Ejes H/V respecto al inicio del trazo de pared
        start = self.session.wall_drag_start
        if start is not None:
            # Umbral en metros equivalente a SNAP_RADIUS_PX
            tol_m = self.SNAP_RADIUS_PX / max(vp.scale, 1e-9)
            if abs(world.y - start.y) <= tol_m and abs(world.x - start.x) > tol_m:
                return Point2D(world.x, start.y)  # horizontal
            if abs(world.x - start.x) <= tol_m and abs(world.y - start.y) > tol_m:
                return Point2D(start.x, world.y)  # vertical
        return world

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def _hit_test(self, world: Point2D):
        """Devuelve (SelectionKind, id) del elemento bajo el cursor o None."""
        vp = self.viewport
        wx, wy = vp.world_to_screen(world)
        radius = self.HIT_RADIUS_PX

        # APs y clientes primero (hit más preciso)
        for ap in reversed(self.session.project.access_points):
            ax, ay = vp.world_to_screen(ap.position)
            if (ax - wx) ** 2 + (ay - wy) ** 2 <= (radius + 4) ** 2:
                return SelectionKind.AP, ap.id
        for client in reversed(self.session.project.clients):
            cx, cy = vp.world_to_screen(client.position)
            if (cx - wx) ** 2 + (cy - wy) ** 2 <= radius ** 2:
                return SelectionKind.CLIENT, client.id

        # Paredes: distancia punto-segmento en píxeles
        for wall in reversed(self.session.floor.walls):
            sx, sy = vp.world_to_screen(wall.segment.start)
            ex, ey = vp.world_to_screen(wall.segment.end)
            if self._point_segment_dist_px(wx, wy, sx, sy, ex, ey) <= radius:
                return SelectionKind.WALL, wall.id
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

    def _on_motion(self, event) -> None:
        world = self._cursor_world(event)
        self.on_cursor(world.x, world.y)

        if self.session.tool == Tool.WALL and self.session.wall_drag_start is not None:
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

    def _on_press(self, event) -> None:
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
        if self._drag_ap_id or self._drag_client_id:
            self._drag_ap_id = None
            self._drag_client_id = None
            self.on_model_changed()

    def _on_delete_key(self, _event) -> str:
        if self.session.delete_selection():
            self.render_project()
            self.on_model_changed()
        return "break"
