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
    Tool,
)
from ui.viewport import Viewport

# Debounce del heatmap (ms). El valor es configurable por instancia.
HEATMAP_DEBOUNCE_MS = 150

# ---------------------------------------------------------------------------
# Fase 15.1: OVERLAY de la cobertura del AP seleccionado (capa visual).
#
# Paleta deliberadamente DISTINTA del heatmap de fondo (verde → ámbar →
# rojo): cian → violeta. Así se ve que es una capa añadida encima del
# fondo estático, no una versión recoloreada del propio fondo.
#
# La capa se construye con los RSSI que ya calculó el motor y con los
# umbrales CONFIGURADOS del proyecto (−50 / −67 / −75 / −85 dBm por
# defecto): no hay fórmula RF nueva ni círculo artificial.
# ---------------------------------------------------------------------------
AP_COVERAGE_RGB: tuple[tuple[int, int, int], ...] = (
    (40, 190, 80),    # ≥ excelente_min_dbm  (verde)
    (160, 235, 170),  # ≥ good_min_dbm      (verde muy clarito)
    (250, 210, 50),   # ≥ regular_min_dbm   (amarillo)
    (235, 60, 60),    # ≥ weak_min_dbm      (rojo)
)
#: Celdas SIN señal (RSSI < weak_min_dbm): gris claro para que se vea
#: exactamente dónde no llega el AP (la zona de cobertura es la que NO
#: es gris).
AP_COVERAGE_NO_SIGNAL_RGB = (205, 205, 205)
AP_COVERAGE_NO_SIGNAL_ALPHA = 110
#: Opacidad del relleno según el RSSI de cada celda: LA ZONA SE
#: «ENCIENDE» ALREDEDOR DEL AP y se desdibuja hacia los bordes, de modo
#: que el heatmap de fondo se sigue viendo fuera de la zona fuerte (al
#: hacer click no "cambia" el fondo) pero la cobertura se distingue.
AP_COVERAGE_ALPHA_MIN = 40
AP_COVERAGE_ALPHA_MAX = 165
#: Borde de cada zona de calidad: separa excelente/bueno/aceptable/débil.
AP_COVERAGE_ZONE_EDGE = (6, 12, 24, 255)
AP_COVERAGE_ZONE_EDGE_WIDTH = 3
#: Límite de la cobertura (RSSI < weak_min_dbm): blanco y grueso, la
#: zona «corta» exactamente donde el motor dice que no hay señal.
AP_COVERAGE_LIMIT = (255, 255, 255, 255)
AP_COVERAGE_LIMIT_WIDTH = 4


def _ap_coverage_rank(rx_power_dbm: float, thresholds) -> int | None:
    """Banda de calidad del RSSI según los umbrales configurados (F15.1).

    Returns:
        0..3 (de mejor a peor banda) o ``None`` si el RSSI está por
        debajo de ``weak_min_dbm`` ⇒ sin señal: la celda se pinta en
        **gris claro** y su borde es el límite del alcance del AP.
    """
    if rx_power_dbm >= thresholds.excellent_min_dbm:
        return 0
    if rx_power_dbm >= thresholds.good_min_dbm:
        return 1
    if rx_power_dbm >= thresholds.regular_min_dbm:
        return 2
    if rx_power_dbm >= thresholds.weak_min_dbm:
        return 3
    return None


def _ap_coverage_alpha(
    rx_power_dbm: float, floor_dbm: float, peak_dbm: float, thresholds
) -> int:
    """Opacidad de la celda dentro del RANGO de RSSI del propio AP.

    La celda más floja de ese AP pinta ``AP_COVERAGE_ALPHA_MIN`` (casi
    transparente: el heatmap de fondo se sigue viendo) y la más fuerte
    ``AP_COVERAGE_ALPHA_MAX`` (zona encendida). El resultado es una capa
    centrada en el AP que NO disimula el fondo fuera de su área fuerte.

    Solo presenta: no hay fórmula RF aquí, el RSSI ya lo calculó el
    motor; los extremos del rango salen de sus propias ``evaluations``.
    """
    span = peak_dbm - floor_dbm
    if rx_power_dbm <= floor_dbm or span <= 0:
        return AP_COVERAGE_ALPHA_MIN
    ratio = (rx_power_dbm - floor_dbm) / span
    ratio = 0.0 if ratio < 0.0 else (1.0 if ratio > 1.0 else ratio)
    # Nunca por debajo del mínimo ya en la banda «débil»: el límite de
    # cobertura lo marca el trazo blanco, no la opacidad.
    floor_ratio = 0.0
    if span > 0 and thresholds.weak_min_dbm > floor_dbm:
        floor_ratio = (thresholds.weak_min_dbm - floor_dbm) / span
    ratio = max(ratio, min(floor_ratio, 1.0))
    span_alpha = AP_COVERAGE_ALPHA_MAX - AP_COVERAGE_ALPHA_MIN
    return int(round(AP_COVERAGE_ALPHA_MIN + span_alpha * ratio))


def build_ap_coverage_overlay(result, viewport, thresholds, cell_size_m: float):
    """Capa SELECTED_AP_COVERAGE: la cobertura visual del AP seleccionado.

    Flujo (conexión única con el motor que ya existe):

        CoverageGrid → evaluations → rx_power_dbm
            → clasificación RSSI (umbrales configurados)
            → celdas de la cobertura → esta imagen

    * **relleno** de cada celda del CoverageGrid con su banda de
      calidad y una opacidad que crece con el RSSI:
      **verde** = excelente, **verde muy clarito** = buena,
      **amarillo** = regular, **rojo** = débil y **gris claro** = sin
      señal (RSSI < ``weak_min_dbm``);
    * **borde oscuro** entre zonas de calidad distintas;
    * **límite blanco y grueso** donde se pasa de tener señal a no
      tenerla: la forma la pone el motor (paredes y obstáculos generan
      cortes irregulares).

    Nada más: sin líneas decorativas ni retículas. Es una capa aparte:
    seleccionar no invalida ni sustituye el heatmap de fondo (el gris de
    «sin señal» tapa el plano SOLO en las celdas donde el motor no da
    señal). No hay radio, distancia ni fórmula: la forma sale de los
    RSSI que devuelve ``simulate_coverage`` con la banda y las paredes
    del AP.

    Args:
        result: ``SimulationResult`` de **un** solo AP.
        viewport: usado solo para metros → píxeles (igual que el fondo).
        thresholds: ``CoverageThresholds`` del proyecto.
        cell_size_m: resolución del grid (tamaño de celda en metros).

    Returns:
        Imagen RGBA, o ``None`` si no hay evaluaciones.
    """
    evaluations = result.evaluations
    if not evaluations:
        return None

    from PIL import Image, ImageDraw

    x1f, y1f, x2f, y2f = viewport.floor_rect_px
    img_w = max(1, int(round(x2f - x1f)))
    img_h = max(1, int(round(y2f - y1f)))
    image = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    half_px = max(1.0, viewport.world_to_screen_len(cell_size_m) / 2.0)

    floor_dbm = min(evaluation.rx_power_dbm for evaluation in evaluations)
    peak_dbm = max(evaluation.rx_power_dbm for evaluation in evaluations)

    # 1) Relleno: una celda por punto del CoverageGrid. Banda de
    #    calidad con opacidad creciente hacia el AP; sin señal ⇒ gris.
    cells: list[tuple[float, float, int, float, float]] = []
    for evaluation in evaluations:
        sx, sy = viewport.world_to_screen(evaluation.point)
        cx, cy = sx - x1f, sy - y1f
        rank = _ap_coverage_rank(evaluation.rx_power_dbm, thresholds)
        cells.append(
            (cx, cy, -1 if rank is None else rank,
             evaluation.point.x, evaluation.point.y)
        )
        rect = (cx - half_px, cy - half_px, cx + half_px, cy + half_px)
        if rank is not None:
            draw.rectangle(
                rect,
                fill=(
                    *AP_COVERAGE_RGB[rank],
                    _ap_coverage_alpha(
                        evaluation.rx_power_dbm, floor_dbm, peak_dbm, thresholds
                    ),
                ),
            )
        else:
            draw.rectangle(
                rect,
                fill=(*AP_COVERAGE_NO_SIGNAL_RGB, AP_COVERAGE_NO_SIGNAL_ALPHA),
            )

    # 2) Aristas entre celdas vecinas: borde entre zonas de calidad o
    #    límite de la cobertura. No se dibuja nada más.
    rows: dict[float, list] = {}
    cols: dict[float, list] = {}
    for cx, cy, rank, point_x, point_y in cells:
        rows.setdefault(round(point_y, 6), []).append((cx, cy, rank))
        cols.setdefault(round(point_x, 6), []).append((cx, cy, rank))

    def edge_kind(first, second) -> str | None:
        """Clase de arista entre dos celdas vecinas (o None si no hay)."""
        if first[2] == second[2]:
            return None
        if first[2] < 0 or second[2] < 0:
            return "limit"      # cobertura ↔ fuera de cobertura
        return "zone"           # cambio de banda de calidad

    STYLES = {
        "zone": (AP_COVERAGE_ZONE_EDGE, AP_COVERAGE_ZONE_EDGE_WIDTH),
        "limit": (AP_COVERAGE_LIMIT, AP_COVERAGE_LIMIT_WIDTH),
    }

    def paint(run, vertical: bool, wanted: str) -> None:
        run.sort(key=lambda cell: cell[0 if vertical else 1])
        for first, second in zip(run, run[1:]):
            if edge_kind(first, second) != wanted:
                continue
            color, width = STYLES[wanted]
            if vertical:  # arista vertical entre columnas vecinas
                mid = (first[0] + second[0]) / 2.0
                draw.line(
                    (mid, first[1] - half_px, mid, first[1] + half_px),
                    fill=color, width=width,
                )
            else:         # arista horizontal entre filas vecinas
                mid = (first[1] + second[1]) / 2.0
                draw.line(
                    (first[0] - half_px, mid, first[0] + half_px, mid),
                    fill=color, width=width,
                )

    # El límite de la cobertura va el último: es lo que tiene que verse
    # con más fuerza.
    for wanted in ("zone", "limit"):
        for run in rows.values():
            paint(run, True, wanted)
        for run in cols.values():
            paint(run, False, wanted)
    return image

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
        # Imagen del resaltado (Fase 15.1) y el resultado RF del que se
        # construyó: si sigue siendo el mismo, no se vuelve a dibujar.
        self._ap_coverage_source = None
        self._ap_coverage_image = None

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
            # theme.STYLE_MAP mezcla opciones escalares (p. ej. padding)
            # con especificaciones de estado (listas de (estado, valor)).
            # Las primeras van a `configure` y las segundas a `map`:
            # pasar una lista a `configure` NO lanza error, pero guarda
            # la cadena literal "{active #…}" como COLOR, Tk no la
            # reconoce (TclError: unknown color name) y el widget se
            # pinta en negro ⇒ botones/etiquetas ilegibles.
            scalar = {
                k: v for k, v in opts.items()
                if not (isinstance(v, list) and v and isinstance(v[0], tuple))
            }
            states = {
                k: v for k, v in opts.items()
                if isinstance(v, list) and v and isinstance(v[0], tuple)
            }
            try:
                if scalar:
                    style.configure(name, **scalar)
            except tk.TclError:
                pass
            try:
                if states:
                    style.map(name, **states)
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
        # La banda activa cambia la simulación puntual si el AP no
        # tiene banda propia: el panel se repone solo.
        self._refresh_simulation_if_band_changed()
        # Y el estado de los clientes (RSSI a otra frecuencia): el
        # indicador del plano y el panel de información se refrescan ya,
        # sin esperar al recálculo del heatmap.
        self.render_project()
        self.properties.refresh()

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
            # La cobertura del AP seleccionado NO depende del heatmap:
            # se refresca en lugar de borrarse (Fase 15.1). render_project
            # re-coloca la capa POR DEBAJO de paredes/APs (draw_ap_coverage
            # recrea el item y quedaría el último si no se reordena).
            self._refresh_ap_coverage()
            self.render_project()
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
        """Métrica visual del heatmap (RSSI/SNR/interferencia/SINR).

        Es una vista: NO se recalcula el RF. Las evaluaciones de
        ``last_heatmap`` son las mismas con cualquier métrica (otro
        color, otro valor por punto), así que se reconstruye SOLO la
        imagen. Si todavía no hay resultado válido se programa el
        cálculo normal.
        """
        try:
            self.session.set_heatmap_metric(metric)
        except ValueError as exc:
            messagebox.showerror("Métrica", str(exc), parent=self)
            return
        self.toolbar.set_metric(self.session.heatmap_metric)
        if not self._recolor_heatmap():
            self._schedule_heatmap()

    def _recolor_heatmap(self) -> bool:
        """Repinta el heatmap con la métrica elegida, SIN ejecutar el RF.

        Usa ``last_heatmap`` ya calculado (mismo resultado, distinta
        paleta/valor) y actualiza el panel de texto.

        Returns:
            True si había resultado válido y ya está repintado; False si
            aún hay que recalcular (heatmap apagado, sin resultado o
            documento modificado).
        """
        session = self.session
        if (not session.heatmap_enabled
                or session.last_heatmap is None
                or session.heatmap_dirty):
            return False
        image = build_heatmap_image(
            session.last_heatmap,
            self.viewport,
            cell_size_m=session.grid_resolution_m,
            metric=session.heatmap_metric,
        )
        if image is None:
            return False
        self.canvas.draw_heatmap(image)
        self.render_project()
        self.properties.show_heatmap_text(session.heatmap_stats_text())
        clients = session.client_rssi_lines()
        if clients:
            self.properties.append_heatmap_text(
                "\nClientes:\n" + "\n".join(clients)
            )
        return True

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
        # Fase 15.1: el heatmap de fondo SOLO se recalcula si el documento
        # cambió. Una selección nueva (o cualquier cambio de vista) solo
        # refresca la capa de resaltado del AP elegido: el fondo queda
        # exactamente igual.
        background_changed = (
            self.session.heatmap_dirty or self.session.last_heatmap is None
        )
        self._refresh_ap_selector()
        self._update_title()
        self._schedule_heatmap(background=background_changed)
        # El panel «Simulación» guarda los números de una corrida: si la
        # banda efectiva ya no es la de esa corrida, se repite para que
        # no muestre RSSI de otra banda (refresco silencioso).
        self._refresh_simulation_if_band_changed()

    # ------------------------------------------------------------------
    # Simulación puntual (panel «Simulación / Heatmap»)
    # ------------------------------------------------------------------

    def _simulation_band_now(self) -> str | None:
        """Id de banda que tendría HOY la simulación puntual guardada.

        Se resuelve contra el AP de ESA corrida (no contra la selección
        actual): su banda configurada manda sobre la activa (Fase 10).
        """
        session = self.session
        sim = session.last_simulation
        if sim is None or not sim.evaluations:
            return None
        ap_id = sim.evaluations[0].access_point_id
        ap = None
        for candidate in session.project.access_points:
            if candidate.id == ap_id:
                ap = candidate
                break
        if ap is None and session.project.access_points:
            ap = session.project.access_points[0]
        if ap is None:
            return None
        return session.resolve_band_for_ap(ap, session.band_id).id

    def _refresh_simulation_if_band_changed(self) -> None:
        """Repite la simulación puntual si cambió la banda (panel vivo).

        Solo si YA había una simulación (nunca se crea una como efecto
        secundario) y sin diálogos: el objetivo es que «Banda», «RSSI
        mínimo/máximo», etc. del panel correspondan siempre a la
        configuración actual del AP.
        """
        session = self.session
        sim = session.last_simulation
        if sim is None or sim.band_id == self._simulation_band_now():
            return
        try:
            session.run_simulation(session.band_id)
        except MaterialAttenuationError as exc:
            session.last_simulation_error = str(exc)
            self.properties.show_simulation_text(str(exc))
            return
        except ValueError:
            return
        self.properties.show_simulation_text(session.simulation_summary_text())

    # ------------------------------------------------------------------
    # Heatmap (debounce + engine + renderer)
    # ------------------------------------------------------------------

    def _schedule_heatmap(self, *, background: bool = True) -> None:
        """Debounce: evita recalcular en cada evento de un arrastre.

        Args:
            background: False (Fase 15.1) marca que el heatmap de fondo
                NO está obsoleto: solo se refrescará la capa de
                resaltado del AP seleccionado, sin volver a ejecutar el
                pipeline F10→F12 ni sustituir la imagen del fondo.
        """
        if not self.session.heatmap_enabled:
            # Sin heatmap NO hay fondo, pero la cobertura del AP
            # seleccionado sigue existiendo: es una capa independiente.
            self.canvas.clear_heatmap()
            self._refresh_ap_coverage()
            self.render_project()
            return
        if self._heatmap_after_id is not None:
            try:
                self.after_cancel(self._heatmap_after_id)
            except tk.TclError:
                pass
            self._heatmap_after_id = None
        if background:
            self.session.invalidate_heatmap()
            self._update_status_coords(None, None)
            self.properties.show_heatmap_text("Calculando cobertura...")
        self._heatmap_after_id = self.after(
            self._heatmap_debounce_ms, self._run_heatmap_now
        )

    def _refresh_ap_coverage(self) -> None:
        """Resaltado de la cobertura del AP seleccionado (Fase 15.1).

        Calcula los RSSI **reales** de ese AP (mismo grid, misma
        geometría y misma banda resuelta que el heatmap) y los pinta como
        capa aparte. No toca ``session.last_heatmap`` ni el ámbito «AP:»
        del fondo: si no hay AP seleccionado, solo se quita el resaltado.

        La cobertura viene CACHEADA de la sesión (ver
        ``EditorSession.selected_ap_coverage``): mientras no cambie la RF
        se reutiliza el resultado **y** la imagen ya construida, de modo
        que seleccionar un AP, volver a él o desactivar el heatmap no
        ejecutan ``simulate_coverage``.
        """
        image = None
        source = None
        try:
            result = self.session.selected_ap_coverage()
            if result is not None:
                if (result is self._ap_coverage_source
                        and self._ap_coverage_image is not None):
                    # Mismo resultado RF que la imagen actual: nada que
                    # recalcular ni que redibujar (solo re-colocar).
                    source, image = result, self._ap_coverage_image
                else:
                    source = result
                    image = build_ap_coverage_overlay(
                        result,
                        self.viewport,
                        self.session.project.thresholds,
                        self.session.grid_resolution_m,
                    )
        except (MaterialAttenuationError, KeyError, ValueError):
            # Banda sin materiales / AP inexistente: sin resaltado.
            source, image = None, None
        self._ap_coverage_source = source
        self._ap_coverage_image = image
        self.canvas.draw_ap_coverage(image)

    def _run_heatmap_now(self) -> None:
        self._heatmap_after_id = None
        if not self.session.heatmap_enabled:
            self.canvas.clear_heatmap()
            # El overlay del AP seleccionado no depende del heatmap.
            self._refresh_ap_coverage()
            self.render_project()
            return
        # Fase 15.1: primero el resaltado del AP seleccionado; el fondo
        # solo se recalcula si el documento lo exige (ver _schedule_heatmap).
        self._refresh_ap_coverage()
        if not self.session.heatmap_dirty:
            self.render_project()
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
