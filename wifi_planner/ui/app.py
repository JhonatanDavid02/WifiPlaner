"""Ventana principal de Wi-Fi Planner (Fase 3: editor 2D)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core.material import MaterialAttenuationError
from ui import theme
from ui.dialogs import ProjectDimensionsDialog
from ui.editor_canvas import EditorCanvas
from ui.panels import PropertiesPanel, Toolbar
from ui.session import EditorSession, Tool
from ui.viewport import Viewport


class WifiPlannerApp(tk.Tk):
    """Editor 2D: Project es la fuente de verdad; Canvas solo pinta."""

    def __init__(self, session: EditorSession | None = None) -> None:
        super().__init__()
        self.title("Wi-Fi Planner")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(bg=theme.BG)

        self.session = session if session is not None else EditorSession()
        self.viewport = Viewport(
            world_width_m=self.session.floor_width_m,
            world_height_m=self.session.floor_height_m,
        )

        self._apply_theme()
        self._build_layout()
        self._bind_keys()

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, self._initial_render)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        for name, opts in theme.STYLE_MAP.items():
            try:
                style.configure(name, **opts)
            except tk.TclError:
                pass
        # Radiobutton legible en tema oscuro
        style.configure(
            "TRadiobutton",
            background=theme.BG,
            foreground=theme.FG,
            focuscolor=theme.BG,
        )
        style.map(
            "TRadiobutton",
            background=[("active", theme.BG), ("!active", theme.BG)],
            foreground=[("active", theme.ACCENT), ("!active", theme.FG)],
        )

    def _build_layout(self) -> None:
        # Toolbar arriba
        self.toolbar = Toolbar(
            self,
            on_tool=self._on_tool,
            on_band=self._on_band,
            on_simulate=self._on_simulate,
            on_dimensions=self._on_dimensions,
            on_delete=self._on_delete,
        )
        self.toolbar.pack(fill="x", padx=6, pady=(6, 2))

        # Centro: canvas + panel derecho
        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True, padx=6, pady=2)

        self.canvas = EditorCanvas(
            middle,
            session=self.session,
            viewport=self.viewport,
            on_model_changed=self._on_model_changed,
            on_cursor=self._on_cursor,
        )
        self.canvas.pack(side="left", fill="both", expand=True)

        self.properties = PropertiesPanel(
            middle,
            session=self.session,
            on_changed=self._on_model_changed,
            on_simulate=self._on_simulate,
        )
        self.properties.pack(side="right", fill="y", padx=(6, 0))

        # Barra de estado: coordenadas en metros
        self.status = ttk.Label(
            self,
            text="X: — m    Y: — m    |    Escala: — px/m    |    Fuente de verdad: Project (metros)",
            style="StatusBar.TLabel",
            anchor="w",
        )
        self.status.pack(fill="x", padx=6, pady=(2, 6))

    def _bind_keys(self) -> None:
        self.bind("<Escape>", self._on_escape)

        def make_tool_handler(tool: Tool):
            def handler(event):
                widget = event.widget
                # No robar atajos mientras se escribe en un campo de texto
                if isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
                    return None
                self._set_tool(tool)
                return "break"

            return handler

        self.bind("s", make_tool_handler(Tool.SELECT))
        self.bind("w", make_tool_handler(Tool.WALL))
        self.bind("a", make_tool_handler(Tool.AP))
        self.bind("c", make_tool_handler(Tool.CLIENT))

    def _initial_render(self) -> None:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w > 1 and h > 1:
            self.viewport.set_canvas_size(w, h)
        self.render_project()
        self.properties.refresh()

    # ------------------------------------------------------------------
    # Callbacks de UI
    # ------------------------------------------------------------------

    def _set_tool(self, tool: Tool) -> None:
        self.session.set_tool(tool)
        # Sincronizar radiobuttons de la toolbar
        self.toolbar._tool_var.set(tool.value)
        self.render_project()

    def _on_tool(self, tool: Tool) -> None:
        self.session.set_tool(tool)
        self.render_project()

    def _on_band(self, band_id: str) -> None:
        self.session.band_id = band_id

    def _on_delete(self) -> None:
        if self.session.delete_selection():
            self.render_project()
            self.properties.refresh()

    def _on_dimensions(self) -> None:
        def apply(w: float, h: float) -> None:
            self.session.set_floor_dimensions(w, h)
            self.viewport.set_world_size(w, h)
            self.render_project()
            self._update_status_coords(None, None)

        ProjectDimensionsDialog(
            self,
            width_m=self.session.floor_width_m,
            height_m=self.session.floor_height_m,
            on_apply=apply,
        )

    def _on_simulate(self) -> None:
        try:
            self.session.run_simulation(self.session.band_id)
        except MaterialAttenuationError as exc:
            self.session.last_simulation_error = (
                f"Banda sin datos de atenuación:\n{exc}\n"
                "(no se inventan valores; usa 2.4 o 5 GHz)."
            )
            self.properties.show_simulation_text(self.session.last_simulation_error)
            return
        except ValueError as exc:
            messagebox.showinfo("Simulación", str(exc), parent=self)
            return
        self.properties.show_simulation_text(self.session.simulation_summary_text())

    def _on_cursor(self, x_m: float, y_m: float) -> None:
        self._update_status_coords(x_m, y_m)

    def _update_status_coords(self, x_m: float | None, y_m: float | None) -> None:
        if x_m is None or y_m is None:
            coords = "X: — m    Y: — m"
        else:
            coords = f"X: {x_m:.2f} m    Y: {y_m:.2f} m"
        scale = self.viewport.scale
        dims = f"{self.session.floor_width_m:g} × {self.session.floor_height_m:g} m"
        self.status.configure(
            text=f"{coords}    |    Espacio: {dims}    |    "
            f"Escala: {scale:.1f} px/m (uniforme)    |    "
            f"Herramienta: {self.session.tool.value}"
        )

    def _on_escape(self, _event=None) -> str:
        self.session.wall_drag_start = None
        self.session.select(None, None)
        self._set_tool(Tool.SELECT)
        self.properties.refresh()
        return "break"

    def _on_model_changed(self) -> None:
        """Modelo actualizado => redibujar Canvas + refrescar propiedades."""
        self.render_project()
        self.properties.refresh()
        # Radiobuttons de herramienta pueden estar desfasados tras create+select
        self.toolbar._tool_var.set(self.session.tool.value)

    # ------------------------------------------------------------------
    # Render (fuente de verdad: Project)
    # ------------------------------------------------------------------

    def render_project(self) -> None:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w > 1 and h > 1:
            self.viewport.set_canvas_size(w, h)
        self.viewport.set_world_size(
            self.session.floor_width_m, self.session.floor_height_m
        )
        self.canvas.render_project()


def run_app(session: EditorSession | None = None) -> int:
    """Arranca el bucle de eventos de Tk. Devuelve 0 al cerrar."""
    app = WifiPlannerApp(session=session)
    app.mainloop()
    return 0
