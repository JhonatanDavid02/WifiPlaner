"""Ventana principal de Wi-Fi Planner (Fase 6: editor + heatmap + archivos)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.material import MaterialAttenuationError
from persistence import ProjectFormatError
from ui import theme
from ui.coverage_renderer import build_heatmap_image
from ui.dialogs import RFSettingsDialog, ProjectDimensionsDialog
from ui.editor_canvas import EditorCanvas
from ui.panels import PropertiesPanel, Toolbar
from ui.panels.toolbar import BAND_LABEL_BY_ID
from ui.session import EditorSession, HEATMAP_ALL_APS, Tool
from ui.viewport import Viewport

# Debounce del heatmap (ms). El valor es configurable por instancia.
HEATMAP_DEBOUNCE_MS = 150

# Filtros del diálogo de archivos de proyecto.
FILE_TYPES = [
    ("Proyecto Wi-Fi Planner", "*.json"),
    ("Todos los archivos", "*.*"),
]


class WifiPlannerApp(tk.Tk):
    """Editor 2D + heatmap. Project = fuente de verdad; Canvas = pintura."""

    def __init__(
        self,
        session: EditorSession | None = None,
        heatmap_debounce_ms: int = HEATMAP_DEBOUNCE_MS,
    ) -> None:
        super().__init__()
        self.title("Wi-Fi Planner")
        self.geometry("1180x760")
        self.minsize(960, 640)
        self.configure(bg=theme.BG)

        self.session = session if session is not None else EditorSession()
        self.viewport = Viewport(
            world_width_m=self.session.floor_width_m,
            world_height_m=self.session.floor_height_m,
        )
        self._heatmap_debounce_ms = int(heatmap_debounce_ms)
        self._heatmap_after_id = None

        self._apply_theme()
        self._build_menu()
        self._build_layout()
        self._bind_keys()
        self._update_title()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._initial_render)
        self.after(80, self._schedule_heatmap)

    # ------------------------------------------------------------------
    # Menú Archivo (Fase 6: persistencia local)
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Nuevo", accelerator="Ctrl+N", command=self._on_file_new
        )
        file_menu.add_command(
            label="Abrir…", accelerator="Ctrl+O", command=self._on_file_open
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Guardar", accelerator="Ctrl+S", command=self._on_file_save
        )
        file_menu.add_command(
            label="Guardar como…",
            accelerator="Ctrl+Shift+S",
            command=self._on_file_save_as,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_close)
        menubar.add_cascade(label="Archivo", menu=file_menu)
        self.config(menu=menubar)

    def _on_file_new(self) -> None:
        if not self._confirm_discard_changes():
            return
        self.session.new_project()
        self._after_document_change()

    def _on_file_open(self) -> None:
        if not self._confirm_discard_changes():
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Abrir proyecto",
            filetypes=FILE_TYPES,
        )
        if not path:
            return
        try:
            self.session.open_project(path)
        except (ProjectFormatError, OSError) as exc:
            # El proyecto actual queda intacto (open_project es atómico).
            messagebox.showerror("Abrir proyecto", str(exc), parent=self)
            return
        self._after_document_change()

    def _on_file_save(self) -> None:
        self._save_interactive()

    def _on_file_save_as(self) -> None:
        self._save_as_interactive()

    def _confirm_discard_changes(self) -> bool:
        """True si el usuario permite continuar (guardó o descartó)."""
        if not self.session.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Cambios sin guardar",
            "El proyecto tiene cambios sin guardar.\n¿Desea guardarlos?",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self._save_interactive()
        return True

    def _save_interactive(self) -> bool:
        """Guarda en la ruta actual (o pide ruta). True si se guardó."""
        if self.session.project_path is None:
            return self._save_as_interactive()
        try:
            self.session.save_project()
        except (ProjectFormatError, OSError) as exc:
            messagebox.showerror("Guardar proyecto", str(exc), parent=self)
            return False
        self._update_title()
        return True

    def _save_as_interactive(self) -> bool:
        """Pide ruta y guarda. True si el usuario completó la guarda."""
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar proyecto como",
            defaultextension=".json",
            filetypes=FILE_TYPES,
        )
        if not path:
            return False
        try:
            self.session.save_project_as(path)
        except (ProjectFormatError, OSError) as exc:
            messagebox.showerror("Guardar proyecto", str(exc), parent=self)
            return False
        self._update_title()
        return True

    def _after_document_change(self) -> None:
        """Reajusta la UI tras cargar/crear un proyecto (sin estado parcial)."""
        self.viewport.set_world_size(
            self.session.floor_width_m, self.session.floor_height_m
        )
        self.toolbar.set_band_label(
            BAND_LABEL_BY_ID.get(self.session.band_id, "2.4 GHz")
        )
        self.toolbar.set_resolution_value(self.session.grid_resolution_m)
        self.toolbar.set_heatmap_enabled(self.session.heatmap_enabled)
        self.toolbar.set_metric(self.session.heatmap_metric)
        self.toolbar._tool_var.set(self.session.tool.value)
        self._refresh_ap_selector()
        self.properties.refresh()
        # Sin residuo del documento anterior: el heatmap (imagen) y el
        # estado de arrastre pertenecen al proyecto que se acaba de salir.
        self.canvas.clear_heatmap()
        self.canvas.reset_interaction()
        self.render_project()
        self._update_status_coords(None, None)
        self._update_title()
        self._schedule_heatmap()

    def _update_title(self) -> None:
        dirty = " *" if self.session.dirty else ""
        self.title(f"{self.session.project.name}{dirty}")

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
        self.toolbar = Toolbar(
            self,
            on_tool=self._on_tool,
            on_band=self._on_band,
            on_simulate=self._on_simulate,
            on_dimensions=self._on_dimensions,
            on_delete=self._on_delete,
            on_resolution=self._on_resolution,
            on_heatmap_toggle=self._on_heatmap_toggle,
            on_heatmap_ap=self._on_heatmap_ap,
            on_heatmap_metric=self._on_heatmap_metric,
            on_rf_settings=self._on_rf_settings,
        )
        self.toolbar.pack(fill="x", padx=6, pady=(6, 2))
        self._refresh_ap_selector()

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

        self.status = ttk.Label(
            self,
            text="X: — m    Y: — m    |    Heatmap: pendiente",
            style="StatusBar.TLabel",
            anchor="w",
        )
        self.status.pack(fill="x", padx=6, pady=(2, 6))

    def _bind_keys(self) -> None:
        self.bind("<Escape>", self._on_escape)

        # Atajos de archivo (menú Archivo).
        self.bind("<Control-n>", lambda _e: self._on_file_new())
        self.bind("<Control-o>", lambda _e: self._on_file_open())
        self.bind("<Control-s>", lambda _e: self._on_file_save())
        self.bind("<Control-Shift-S>", lambda _e: self._on_file_save_as())

        def make_tool_handler(tool: Tool):
            def handler(event):
                widget = event.widget
                if isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
                    return None
                # Ctrl (+ Shift): no robar Ctrl+S / Ctrl+N / Ctrl+O.
                if event.state & 0x0004:
                    return None
                self._set_tool(tool)
                return "break"

            return handler

        self.bind("s", make_tool_handler(Tool.SELECT))
        self.bind("w", make_tool_handler(Tool.WALL))
        self.bind("a", make_tool_handler(Tool.AP))
        self.bind("c", make_tool_handler(Tool.CLIENT))
        self.bind("e", make_tool_handler(Tool.SPACE))

    def _initial_render(self) -> None:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w > 1 and h > 1:
            self.viewport.set_canvas_size(w, h)
        self.render_project()
        self.properties.refresh()

    def _on_close(self) -> None:
        if not self._confirm_discard_changes():
            return
        if self._heatmap_after_id is not None:
            try:
                self.after_cancel(self._heatmap_after_id)
            except tk.TclError:
                pass
            self._heatmap_after_id = None
        self.destroy()

    # ------------------------------------------------------------------
    # Callbacks de UI
    # ------------------------------------------------------------------

    def _set_tool(self, tool: Tool) -> None:
        self.session.set_tool(tool)
        self.toolbar._tool_var.set(tool.value)
        self.render_project()

    def _on_tool(self, tool: Tool) -> None:
        self.session.set_tool(tool)
        self.render_project()

    def _on_band(self, band_id: str) -> None:
        self.session.set_band(band_id)  # invalida heatmap si cambió
        self._update_title()
        self._schedule_heatmap()

    def _on_resolution(self, resolution_m: float) -> None:
        try:
            self.session.set_grid_resolution(resolution_m)
        except ValueError as exc:
            messagebox.showwarning("Resolución", str(exc), parent=self)
            return
        self._update_title()
        self._schedule_heatmap()

    def _on_heatmap_toggle(self, enabled: bool) -> None:
        self.session.set_heatmap_enabled(enabled)
        if enabled:
            self._schedule_heatmap()
        else:
            self.canvas.clear_heatmap()
            self.properties.show_heatmap_text("Heatmap desactivado.")

    def _on_heatmap_ap(self, ap_ref: str) -> None:
        """Selector de AP del heatmap: combinado (Todos) o individual."""
        try:
            self.session.set_heatmap_ap(ap_ref)
        except KeyError as exc:
            messagebox.showwarning("AP", str(exc), parent=self)
            self._refresh_ap_selector()
            return
        self._refresh_ap_selector()
        self._schedule_heatmap()

    def _on_heatmap_metric(self, metric: str) -> None:
        """Métrica del heatmap (RSSI/SNR): invalida y repinta el resultado."""
        try:
            self.session.set_heatmap_metric(metric)
        except ValueError as exc:
            messagebox.showwarning("Métrica", str(exc), parent=self)
            return
        self.toolbar.set_metric(self.session.heatmap_metric)
        self._schedule_heatmap()

    def _on_rf_settings(self) -> None:
        """Diálogo de configuración RF global (Fase 7)."""
        radio = self.session.project.radio
        thresholds = self.session.project.thresholds

        def apply(
            noise_floor_dbm: float,
            snr_target_db: float,
            rssi_target_dbm: float,
            wifi_standard: str,
            channel_width_mhz: int,
        ) -> None:
            try:
                self.session.apply_rf_settings(
                    noise_floor_dbm=noise_floor_dbm,
                    snr_target_db=snr_target_db,
                    rssi_target_dbm=rssi_target_dbm,
                    wifi_standard=wifi_standard,
                    channel_width_mhz=channel_width_mhz,
                )
            except ValueError as exc:
                messagebox.showerror("Configuración RF", str(exc), parent=self)
                return
            self.properties.refresh()
            self._update_title()
            self._schedule_heatmap()

        RFSettingsDialog(
            self,
            noise_floor_dbm=radio.noise_floor_dbm,
            snr_target_db=thresholds.snr_target_db,
            rssi_target_dbm=thresholds.rssi_target_dbm,
            wifi_standard=radio.wifi_standard,
            channel_width_mhz=radio.channel_width_mhz,
            on_apply=apply,
        )

    def _refresh_ap_selector(self) -> None:
        """Sincroniza la combobox de AP con el modelo (etiquetas legibles)."""
        ids = [c for c in self.session.ap_choices_for_heatmap() if c != HEATMAP_ALL_APS]
        labels = ["Todos los AP"] + ids
        if self.session.heatmap_ap_id == HEATMAP_ALL_APS:
            current_label = "Todos los AP"
        else:
            current_label = self.session.heatmap_ap_id
            if current_label not in labels:
                current_label = "Todos los AP"
        self.toolbar.set_ap_choices(labels, current=current_label)

    def _on_delete(self) -> None:
        if self.session.delete_selection():
            self.render_project()
            self.properties.refresh()
            self._schedule_heatmap()

    def _on_dimensions(self) -> None:
        def apply(w: float, h: float) -> None:
            self.session.set_floor_dimensions(w, h)
            self.viewport.set_world_size(w, h)
            self.render_project()
            self._update_status_coords(None, None)
            self._update_title()
            self._schedule_heatmap()

        ProjectDimensionsDialog(
            self,
            width_m=self.session.floor_width_m,
            height_m=self.session.floor_height_m,
            on_apply=apply,
        )

    def _on_simulate(self) -> None:
        """Simulación puntual (resumen) + heatmap del grid."""
        try:
            self.session.run_simulation(self.session.band_id)
        except MaterialAttenuationError as exc:
            self.session.last_simulation_error = (
                "No hay datos de atenuación de materiales para esta banda.\n"
                f"Detalle: {exc}\n"
                "(no se inventan valores ni hay fallback a 5 GHz)."
            )
            self.properties.show_simulation_text(self.session.last_simulation_error)
            self.properties.show_heatmap_text(self.session.last_simulation_error)
            self.session.last_heatmap_error = self.session.last_simulation_error
            self.canvas.clear_heatmap()
            return
        except ValueError as exc:
            messagebox.showinfo("Simulación", str(exc), parent=self)
            return
        self.properties.show_simulation_text(self.session.simulation_summary_text())
        self._schedule_heatmap()

    def _on_cursor(self, x_m: float, y_m: float) -> None:
        self._update_status_coords(x_m, y_m)

    def _update_status_coords(self, x_m: float | None, y_m: float | None) -> None:
        if x_m is None or y_m is None:
            coords = "X: — m    Y: — m"
        else:
            coords = f"X: {x_m:.2f} m    Y: {y_m:.2f} m"
        scale = self.viewport.scale
        dims = f"{self.session.floor_width_m:g} × {self.session.floor_height_m:g} m"
        heat = "sí" if self.session.heatmap_enabled else "no"
        if self.session.heatmap_dirty and self.session.heatmap_enabled:
            heat = "recalculando…"
        elif self.session.last_heatmap is not None and not self.session.heatmap_dirty:
            heat = "actualizado"
        self.status.configure(
            text=f"{coords}    |    Espacio: {dims}    |    "
            f"Escala: {scale:.1f} px/m | Res. grid: {self.session.grid_resolution_m:g} m | "
            f"Heatmap: {heat} | Herramienta: {self.session.tool.value}"
        )

    def _on_escape(self, _event=None) -> str:
        self.session.wall_drag_start = None
        self.session.space_drag_start = None
        self.session.select(None, None)
        self._set_tool(Tool.SELECT)
        self.properties.refresh()
        return "break"

    def _on_model_changed(self) -> None:
        """Modelo cambió => redibujar + refrescar + programar heatmap."""
        self.render_project()
        self.properties.refresh()
        self.toolbar._tool_var.set(self.session.tool.value)
        self._refresh_ap_selector()
        self._update_title()
        self._schedule_heatmap()

    # ------------------------------------------------------------------
    # Heatmap (debounce + engine + renderer)
    # ------------------------------------------------------------------

    def _schedule_heatmap(self) -> None:
        """Debounce: evita recalcular en cada evento de un arrastre."""
        if not self.session.heatmap_enabled:
            self.canvas.clear_heatmap()
            return
        if self._heatmap_after_id is not None:
            try:
                self.after_cancel(self._heatmap_after_id)
            except tk.TclError:
                pass
            self._heatmap_after_id = None
        self.session.invalidate_heatmap()
        self._update_status_coords(None, None)
        self.properties.show_heatmap_text("Calculando cobertura...")
        self._heatmap_after_id = self.after(
            self._heatmap_debounce_ms, self._run_heatmap_now
        )

    def _run_heatmap_now(self) -> None:
        self._heatmap_after_id = None
        if not self.session.heatmap_enabled:
            self.canvas.clear_heatmap()
            return
        try:
            result = self.session.run_heatmap()
        except MaterialAttenuationError as exc:
            self.session.last_heatmap_error = (
                "No hay datos de atenuación de materiales "
                "para la banda seleccionada (p. ej. 6 GHz).\n"
                f"Detalle: {exc}"
            )
            self.canvas.clear_heatmap()
            self.render_project()
            self.properties.show_heatmap_text(self.session.last_heatmap_error)
            self._update_status_coords(None, None)
            return
        except ValueError as exc:
            # Sin AP u otro error de modelo: no es fatal para el editor
            self.session.last_heatmap_error = str(exc)
            self.canvas.clear_heatmap()
            self.render_project()
            self.properties.show_heatmap_text(str(exc))
            self._update_status_coords(None, None)
            return

        # Render: metros → píxeles solo vía Viewport
        image = build_heatmap_image(
            result,
            self.viewport,
            cell_size_m=self.session.grid_resolution_m,
            metric=self.session.heatmap_metric,
        )
        self.canvas.draw_heatmap(image)
        # render_project re-aplica la capa heatmap bajo paredes/APs
        self.render_project()
        self.properties.show_heatmap_text(self.session.heatmap_stats_text())
        clients = self.session.client_rssi_lines()
        if clients:
            self.properties.append_heatmap_text("\nClientes:\n" + "\n".join(clients))
        self._update_status_coords(None, None)

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
