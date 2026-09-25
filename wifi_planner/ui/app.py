"""Ventana principal de Wi-Fi Planner (Fase 6: editor + heatmap + archivos)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.material import MaterialAttenuationError
from persistence import ProjectFormatError
from ui import theme
from ui.coverage_renderer import build_heatmap_image
from ui.dialogs import (
    ChannelOptimizationDialog,
    ProjectDimensionsDialog,
    RFSettingsDialog,
)
from ui.editor_canvas import EditorCanvas
from ui.panels import PropertiesPanel, Toolbar
from ui.panels.toolbar import BAND_LABEL_BY_ID
from ui.session import (
    DEFAULT_FLOOR_HEIGHT_M,
    DEFAULT_FLOOR_WIDTH_M,
    GRID_STEP_CHOICES,
    EditorSession,
    HEATMAP_ALL_APS,
    SelectionKind,
    Tool,
)
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
        # Última selección sincronizada con el selector de cobertura (F15).
        self._last_selection_key: tuple | None = None

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

        # Menú Editar (Fase 14-G): deshacer/rehacer por snapshots.
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(
            label="Deshacer", accelerator="Ctrl+Z", command=self._on_undo
        )
        edit_menu.add_command(
            label="Rehacer", accelerator="Ctrl+Y", command=self._on_redo
        )
        edit_menu.add_separator()
        edit_menu.add_command(label="Eliminar", command=self._on_delete)
        menubar.add_cascade(label="Editar", menu=edit_menu)

        # Menú Ver (Fase 14-E): zoom, pan (botón central) y rejilla.
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Acercar", accelerator="Ctrl++", command=self._on_zoom_in
        )
        view_menu.add_command(
            label="Alejar", accelerator="Ctrl+-", command=self._on_zoom_out
        )
        view_menu.add_command(
            label="Vista normal", accelerator="Ctrl+0", command=self._on_zoom_reset
        )
        view_menu.add_separator()
        self._snap_var = tk.BooleanVar(value=self.session.snap_to_grid)
        view_menu.add_checkbutton(
            label="Ajustar a rejilla",
            variable=self._snap_var,
            command=self._on_snap_toggle,
        )
        self._grid_step_var = tk.DoubleVar(value=self.session.grid_step_m)
        for step in GRID_STEP_CHOICES:
            view_menu.add_radiobutton(
                label=f"Paso de rejilla {step:g} m",
                variable=self._grid_step_var,
                value=step,
                command=self._on_grid_step,
            )
        menubar.add_cascade(label="Ver", menu=view_menu)
        self.config(menu=menubar)

    def _on_file_new(self) -> None:
        if not self._confirm_discard_changes():
            return
        # El usuario elige las dimensiones: nada de 12×8 implícito (14-B).
        ProjectDimensionsDialog(
            self,
            width_m=DEFAULT_FLOOR_WIDTH_M,
            height_m=DEFAULT_FLOOR_HEIGHT_M,
            on_apply=self._create_new_project,
        )

    def _create_new_project(self, width_m: float, height_m: float) -> None:
        try:
            self.session.new_project(width_m=width_m, height_m=height_m)
        except ValueError as exc:
            messagebox.showerror("Proyecto nuevo", str(exc), parent=self)
            return
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
        # Documento nuevo = vista normal (zoom/pan de lo anterior no aplica).
        self.viewport.reset_view()
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
            on_optimize=self._on_optimize_channels,
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
        # Atajos de zoom (menú Ver, Fase 14-E).
        self.bind("<Control-plus>", lambda _e: self._on_zoom_in())
        self.bind("<Control-equal>", lambda _e: self._on_zoom_in())
        self.bind("<Control-minus>", lambda _e: self._on_zoom_out())
        self.bind("<Control-0>", lambda _e: self._on_zoom_reset())
        # Atajos de editar (menú Editar, Fase 14-G).
        self.bind("<Control-z>", lambda _e: self._on_undo())
        self.bind("<Control-y>", lambda _e: self._on_redo())
        self.bind("<Control-Shift-Z>", lambda _e: self._on_redo())

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
        # Fase 9: "o" = Objeto/obstáculo (sin conflicto con Ctrl+O:
        # el handler ignora la tecla con Ctrl pulsado).
        self.bind("o", make_tool_handler(Tool.OBSTACLE))
        # Fase 14-F: "m" = Medir distancias en metros.
        self.bind("m", make_tool_handler(Tool.MEASURE))

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
        """Diálogo de configuración RF global (Fase 7 + Fase 12)."""
        radio = self.session.project.radio
        thresholds = self.session.project.thresholds

        def apply(
            noise_floor_dbm: float,
            snr_target_db: float,
            rssi_target_dbm: float,
            wifi_standard: str,
            channel_width_mhz: int,
            sinr_target_db: float,
        ) -> None:
            try:
                self.session.apply_rf_settings(
                    noise_floor_dbm=noise_floor_dbm,
                    snr_target_db=snr_target_db,
                    rssi_target_dbm=rssi_target_dbm,
                    wifi_standard=wifi_standard,
                    channel_width_mhz=channel_width_mhz,
                    sinr_target_db=sinr_target_db,
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
            sinr_target_db=thresholds.sinr_target_db,
            on_apply=apply,
        )

    def _on_optimize_channels(self) -> None:
        """Propuesta de canales de la banda activa (Fase 13).

        La optimización NO modifica el proyecto: solo calcula la
        propuesta y la presenta en su diálogo (decisión CM). Cualquier
        error controlado (banda/candidatos inválidos, sin datos de
        materiales) se muestra aquí; nada queda a medias.
        """
        try:
            result = self.session.optimize_channels()
        except MaterialAttenuationError:
            messagebox.showinfo(
                "Optimización de canales",
                "No hay datos de atenuación de materiales para esta banda "
                "(no se inventan valores ni hay fallback).",
                parent=self,
            )
            return
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Optimización de canales", str(exc), parent=self)
            return

        def apply(result_) -> None:
            applied = self.session.apply_channel_assignment(
                result_.optimized_assignment
            )
            if not applied:
                return
            self.properties.refresh()
            self._update_title()
            self._schedule_heatmap()

        ChannelOptimizationDialog(
            self, result=result, on_apply=apply
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

    # ------------------------------------------------------------------
    # Editar (Fase 14-G): deshacer / rehacer
    # ------------------------------------------------------------------

    def _on_undo(self) -> None:
        if self.session.undo():
            self._on_model_changed()

    def _on_redo(self) -> None:
        if self.session.redo():
            self._on_model_changed()

    # ------------------------------------------------------------------
    # Ver (Fase 14-E): zoom / rejilla
    # ------------------------------------------------------------------

    def _zoom_viewport(self, factor: float) -> None:
        """Zoom al centro del lienzo (la rueda hace zoom al cursor)."""
        vp = self.viewport
        vp.zoom_at(factor, vp.canvas_width_px / 2.0, vp.canvas_height_px / 2.0)
        self.canvas.render_project()
        self._update_status_coords(None, None)

    def _on_zoom_in(self) -> None:
        self._zoom_viewport(EditorCanvas.ZOOM_STEP)

    def _on_zoom_out(self) -> None:
        self._zoom_viewport(1.0 / EditorCanvas.ZOOM_STEP)

    def _on_zoom_reset(self) -> None:
        self.viewport.reset_view()
        self.canvas.render_project()
        self._update_status_coords(None, None)

    def _on_snap_toggle(self) -> None:
        self.session.set_snap_to_grid(self._snap_var.get())

    def _on_grid_step(self) -> None:
        try:
            self.session.set_grid_step(float(self._grid_step_var.get()))
        except ValueError as exc:
            messagebox.showerror("Rejilla", str(exc), parent=self)
            return
        self.canvas.render_project()

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
        # Fase 11: el panel del AP muestra su bloque de interferencia.
        self.properties.refresh()
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
            f"Escala: {scale:.1f} px/m | Zoom: {self.viewport.zoom:.0%} | "
            f"Res. grid: {self.session.grid_resolution_m:g} m | "
            f"Heatmap: {heat} | Herramienta: {self.session.tool.value}"
        )

    def _on_escape(self, _event=None) -> str:
        self.session.wall_drag_start = None
        self.session.space_drag_start = None
        self.session.obstacle_drag_start = None
        # Fase 14.1: Escape cancela el arrastre en curso (sin historial).
        self.session.cancel_edit()
        self.canvas.reset_interaction()
        self.session.select(None, None)
        self._set_tool(Tool.SELECT)
        self.properties.refresh()
        return "break"

    def _on_model_changed(self) -> None:
        """Modelo cambió => redibujar + refrescar + programar heatmap."""
        self.render_project()
        self.properties.refresh()
        self.toolbar._tool_var.set(self.session.tool.value)
        # Fase 14.2: la banda activa puede cambiar al editar un AP; la
        # toolbar debe reflejar siempre la banda real de la simulación.
        self.toolbar.set_band_label(
            BAND_LABEL_BY_ID.get(self.session.band_id, "2.4 GHz")
        )
        # Fase 15: si la selección es un AP, la cobertura mostrada es la suya.
        self._sync_heatmap_ap_with_selection()
        self._refresh_ap_selector()
        self._update_title()
        self._schedule_heatmap()

    def _sync_heatmap_ap_with_selection(self) -> None:
        """Al seleccionar un AP se muestra SU cobertura (Fase 15).

        El selector «AP:» de la toolbar es la fuente del ámbito del
        heatmap; aquí solo se cambia cuando la selección pasa a ser un
        AP concreto, para que «cada AP muestre su área de cobertura» sin
        pisar la elección manual del usuario en cualquier otro caso.
        """
        selection = self.session.selection
        key = None if selection is None else (selection.kind, selection.entity_id)
        if key == self._last_selection_key:
            return
        self._last_selection_key = key
        if selection is None or selection.kind != SelectionKind.AP:
            return
        if self.session.heatmap_ap_id == selection.entity_id:
            return
        try:
            self.session.set_heatmap_ap(selection.entity_id)
        except KeyError:
            return
        self._refresh_ap_selector()
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
            message = str(exc)
            if "bandas distintas" in message:
                # Fase 14.2: el heatmap combinado es por banda (contrato
                # F5 intacto); traducimos el error a una acción clara.
                message = (
                    "No se puede combinar el heatmap: hay APs configurados\n"
                    "en bandas distintas.\n\n"
                    "Opciones:\n"
                    "• Selecciona cada AP y ponlos en la misma banda\n"
                    "  (Configuración RF del AP → Banda → Aplicar), o\n"
                    "• Elige un AP concreto en el selector «AP:» de la\n"
                    "  barra superior para verlo por separado.\n\n"
                    f"Detalle: {message}"
                )
            self.session.last_heatmap_error = message
            self.canvas.clear_heatmap()
            self.render_project()
            self.properties.show_heatmap_text(message)
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
        # Fase 11: el panel del AP muestra su bloque de interferencia
        # (el heatmap con métrica «interference» anota los resultados).
        self.properties.refresh()
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
