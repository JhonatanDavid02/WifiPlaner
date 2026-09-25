"""Panel de propiedades del elemento seleccionado + resumen de simulación.

Fase 8: añade edición de espacios (nombre/función) y de aperturas
(tipo/offsets) + creación de aperturas desde la pared seleccionada.

Fase 9: añade el marco «Objeto» (nombre/tipo/material/override por
banda) para obstáculos de mobiliario. El override se escribe como
``band_id=dB`` separado por comas o punto y coma (p. ej.
``band_5=6, band_2_4=4``); sustituye —nunca suma— la pérdida de
referencia del material (decisión BM).

Fase 10: añade el marco «Radio del AP» (banda/canal/ancho + frecuencia
derivada). Las listas de canales y anchos vienen del catálogo único de
``core/channel.py`` / la regla de familia F7 (decisión BQ): la UI no
duplica tablas de frecuencias. El canal NO altera RSSI; la validación
del triple vive en la sesión (decisión BT).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from core.channel import (
    channel_for_band,
    channel_numbers_for_frequency,
    default_channel,
)
from core.obstacle import OBSTACLE_KINDS
from core.radio import (
    WIFI_STANDARDS,
    allowed_channel_widths_mhz,
    wifi_generation,
)
from core.wall import OPENING_KINDS
from ui.session import EditorSession, SelectionKind


def ap_config_unchanged(
    ap,
    *,
    band_id: str,
    channel: int,
    width_mhz: int,
    p_tx_dbm: float,
    wifi_standard: str,
) -> bool:
    """True si el formulario coincide exactamente con el AP del modelo.

    Función pura (sin Tk) usada por «Aplicar» para no crear una entrada
    de historial sin efecto cuando el usuario no cambió nada (Fase 14.2).
    No muta ``ap`` ni la sesión.
    """
    return (
        ap.band_id == band_id
        and ap.channel == channel
        and ap.radio.channel_width_mhz == width_mhz
        and ap.radio.p_tx_dbm == p_tx_dbm
        and ap.radio.wifi_standard == wifi_standard
    )


class PropertiesPanel(ttk.Frame):
    """Muestra y edita propiedades del elemento seleccionado.

    No contiene fórmulas RF: lee/escribe el modelo vía EditorSession.
    """

    def __init__(
        self,
        master,
        session: EditorSession,
        on_changed: Callable[[], None],
        on_simulate: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, width=280, **kwargs)
        self.pack_propagate(False)
        self._session = session
        self._on_changed = on_changed
        self._on_simulate = on_simulate
        self._suppress = False

        self._build()

    def _build(self) -> None:
        # --- Selección ---
        sel_box = ttk.LabelFrame(self, text="Selección", padding=8)
        sel_box.pack(fill="x", padx=8, pady=(8, 4))

        self._info = tk.Text(
            sel_box, height=8, wrap="word", state="disabled",
            bg="#12121c", fg="#e0e0e0", relief="flat", font=("Segoe UI", 9),
        )
        self._info.pack(fill="x")

        # --- Configuración RF del AP (F10: banda/canal/ancho por AP) ---
        self._ap_radio_box = ttk.LabelFrame(
            self, text="Configuración RF del AP", padding=8
        )
        ap_radio_box = self._ap_radio_box
        ap_radio_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(ap_radio_box, text="Banda:").grid(row=0, column=0, sticky="w")
        self._ap_band_var = tk.StringVar()
        self._ap_band_combo = ttk.Combobox(
            ap_radio_box, textvariable=self._ap_band_var, state="readonly", width=16
        )
        self._ap_band_combo.grid(row=0, column=1, sticky="ew", pady=2)
        self._ap_band_combo.bind("<<ComboboxSelected>>", self._ap_band_selected)

        ttk.Label(ap_radio_box, text="Canal:").grid(row=1, column=0, sticky="w")
        self._ap_channel_var = tk.StringVar()
        self._ap_channel_combo = ttk.Combobox(
            ap_radio_box, textvariable=self._ap_channel_var, state="readonly", width=16
        )
        self._ap_channel_combo.grid(row=1, column=1, sticky="ew", pady=2)
        self._ap_channel_combo.bind("<<ComboboxSelected>>", self._ap_channel_selected)

        ttk.Label(ap_radio_box, text="Ancho (MHz):").grid(row=2, column=0, sticky="w")
        self._ap_width_var = tk.StringVar()
        self._ap_width_combo = ttk.Combobox(
            ap_radio_box, textvariable=self._ap_width_var, state="readonly", width=16
        )
        self._ap_width_combo.grid(row=2, column=1, sticky="ew", pady=2)

        ttk.Label(ap_radio_box, text="Frecuencia:").grid(row=3, column=0, sticky="w")
        self._ap_freq_var = tk.StringVar(value="—")
        ttk.Label(ap_radio_box, textvariable=self._ap_freq_var).grid(
            row=3, column=1, sticky="w", pady=2
        )

        ttk.Label(ap_radio_box, text="Estándar:").grid(row=4, column=0, sticky="w")
        self._ap_standard_var = tk.StringVar()
        self._ap_standard_combo = ttk.Combobox(
            ap_radio_box,
            textvariable=self._ap_standard_var,
            values=list(WIFI_STANDARDS),
            state="readonly",
            width=16,
        )
        self._ap_standard_combo.grid(row=4, column=1, sticky="ew", pady=2)

        ttk.Label(ap_radio_box, text="Potencia TX (dBm):").grid(
            row=5, column=0, sticky="w"
        )
        self._ap_ptx_var = tk.StringVar()
        ttk.Entry(ap_radio_box, textvariable=self._ap_ptx_var, width=16).grid(
            row=5, column=1, sticky="ew", pady=2
        )

        # Aviso de coherencia al cambiar de banda (canal/ancho ajustados).
        self._ap_hint_var = tk.StringVar(value="")
        # AP al que pertenece el aviso mostrado (None = sin aviso).
        self._ap_hint_for: str | None = None
        ttk.Label(
            ap_radio_box, textvariable=self._ap_hint_var, wraplength=230
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        apply_row = ttk.Frame(ap_radio_box)
        apply_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._ap_apply_btn = ttk.Button(
            apply_row, text="Aplicar", command=self._ap_apply
        )
        self._ap_apply_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._ap_reset_btn = ttk.Button(
            apply_row, text="Restablecer", command=self._ap_reset
        )
        self._ap_reset_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))
        ap_radio_box.columnconfigure(1, weight=1)
        self._refresh_ap_bands()

        # --- Pared: material / espesor ---
        wall_box = ttk.LabelFrame(self, text="Pared", padding=8)
        wall_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(wall_box, text="Material:").grid(row=0, column=0, sticky="w")
        self._material_var = tk.StringVar()
        self._material_combo = ttk.Combobox(
            wall_box, textvariable=self._material_var, state="readonly", width=18
        )
        self._material_combo.grid(row=0, column=1, sticky="ew", pady=2)
        self._material_combo.bind("<<ComboboxSelected>>", self._material_selected)

        ttk.Label(wall_box, text="Espesor (m):").grid(row=1, column=0, sticky="w")
        self._thickness_var = tk.StringVar()
        self._thickness_entry = ttk.Entry(wall_box, textvariable=self._thickness_var, width=12)
        self._thickness_entry.grid(row=1, column=1, sticky="ew", pady=2)
        self._thickness_entry.bind("<FocusOut>", self._thickness_apply)
        self._thickness_entry.bind("<Return>", self._thickness_apply)

        ttk.Button(wall_box, text="Aplicar espesor", command=self._thickness_apply).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        # Fase 8: openings creados desde la pared seleccionada (BI).
        ttk.Label(wall_box, text="Aperturas:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self._opening_count_var = tk.StringVar(value="0")
        ttk.Label(wall_box, textvariable=self._opening_count_var).grid(
            row=3, column=1, sticky="w", pady=(6, 0)
        )
        btn_row = ttk.Frame(wall_box)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._add_door_btn = ttk.Button(
            btn_row, text="+ Puerta", command=lambda: self._add_opening("door")
        )
        self._add_door_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self._add_window_btn = ttk.Button(
            btn_row, text="+ Ventana", command=lambda: self._add_opening("window")
        )
        self._add_window_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))
        wall_box.columnconfigure(1, weight=1)

        # --- Espacio (fase 8: zonas, sin RF — BH) ---
        space_box = ttk.LabelFrame(self, text="Espacio", padding=8)
        space_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(space_box, text="Nombre:").grid(row=0, column=0, sticky="w")
        self._space_name_var = tk.StringVar()
        self._space_name_entry = ttk.Entry(
            space_box, textvariable=self._space_name_var, width=18
        )
        self._space_name_entry.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(space_box, text="Función:").grid(row=1, column=0, sticky="w")
        self._space_function_var = tk.StringVar()
        self._space_function_entry = ttk.Entry(
            space_box, textvariable=self._space_function_var, width=18
        )
        self._space_function_entry.grid(row=1, column=1, sticky="ew", pady=2)

        self._space_apply_btn = ttk.Button(
            space_box, text="Aplicar espacio", command=self._space_apply
        )
        self._space_apply_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        space_box.columnconfigure(1, weight=1)

        # --- Apertura (fase 8: offsets métricos sobre la pared — BG) ---
        opening_box = ttk.LabelFrame(self, text="Apertura", padding=8)
        opening_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(opening_box, text="Tipo:").grid(row=0, column=0, sticky="w")
        self._opening_kind_var = tk.StringVar()
        self._opening_kind_combo = ttk.Combobox(
            opening_box,
            textvariable=self._opening_kind_var,
            values=list(OPENING_KINDS),
            state="readonly",
            width=16,
        )
        self._opening_kind_combo.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(opening_box, text="Inicio (m):").grid(row=1, column=0, sticky="w")
        self._opening_start_var = tk.StringVar()
        self._opening_start_entry = ttk.Entry(
            opening_box, textvariable=self._opening_start_var, width=10
        )
        self._opening_start_entry.grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(opening_box, text="Fin (m):").grid(row=2, column=0, sticky="w")
        self._opening_end_var = tk.StringVar()
        self._opening_end_entry = ttk.Entry(
            opening_box, textvariable=self._opening_end_var, width=10
        )
        self._opening_end_entry.grid(row=2, column=1, sticky="ew", pady=2)

        self._opening_apply_btn = ttk.Button(
            opening_box, text="Aplicar apertura", command=self._opening_apply
        )
        self._opening_apply_btn.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        opening_box.columnconfigure(1, weight=1)

        # --- Objeto (fase 9: mobiliario con footprint y pérdida — BL/BM) ---
        obstacle_box = ttk.LabelFrame(self, text="Objeto", padding=8)
        obstacle_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(obstacle_box, text="Nombre:").grid(row=0, column=0, sticky="w")
        self._obstacle_name_var = tk.StringVar()
        self._obstacle_name_entry = ttk.Entry(
            obstacle_box, textvariable=self._obstacle_name_var, width=18
        )
        self._obstacle_name_entry.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(obstacle_box, text="Tipo:").grid(row=1, column=0, sticky="w")
        self._obstacle_kind_var = tk.StringVar()
        self._obstacle_kind_combo = ttk.Combobox(
            obstacle_box,
            textvariable=self._obstacle_kind_var,
            values=list(OBSTACLE_KINDS),
            state="readonly",
            width=16,
        )
        self._obstacle_kind_combo.grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(obstacle_box, text="Material:").grid(row=2, column=0, sticky="w")
        self._obstacle_material_var = tk.StringVar()
        self._obstacle_material_combo = ttk.Combobox(
            obstacle_box, textvariable=self._obstacle_material_var, state="readonly",
            width=18,
        )
        self._obstacle_material_combo.grid(row=2, column=1, sticky="ew", pady=2)
        self._obstacle_material_combo.bind(
            "<<ComboboxSelected>>", self._obstacle_apply
        )

        ttk.Label(obstacle_box, text="Override (band=dB):").grid(
            row=3, column=0, sticky="w"
        )
        self._obstacle_override_var = tk.StringVar()
        self._obstacle_override_entry = ttk.Entry(
            obstacle_box, textvariable=self._obstacle_override_var, width=18
        )
        self._obstacle_override_entry.grid(row=3, column=1, sticky="ew", pady=2)

        self._obstacle_apply_btn = ttk.Button(
            obstacle_box, text="Aplicar objeto", command=self._obstacle_apply
        )
        self._obstacle_apply_btn.grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        obstacle_box.columnconfigure(1, weight=1)

        # --- Coordenadas AP / Cliente ---
        pos_box = ttk.LabelFrame(self, text="Posición (m)", padding=8)
        pos_box.pack(fill="x", padx=8, pady=4)

        ttk.Label(pos_box, text="X:").grid(row=0, column=0, sticky="w")
        self._x_var = tk.StringVar()
        ttk.Entry(pos_box, textvariable=self._x_var, width=10).grid(
            row=0, column=1, sticky="ew", pady=2
        )
        ttk.Label(pos_box, text="Y:").grid(row=1, column=0, sticky="w")
        self._y_var = tk.StringVar()
        ttk.Entry(pos_box, textvariable=self._y_var, width=10).grid(
            row=1, column=1, sticky="ew", pady=2
        )
        ttk.Button(pos_box, text="Aplicar posición", command=self._position_apply).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )
        pos_box.columnconfigure(1, weight=1)

        # --- Simulación + Heatmap ---
        sim_box = ttk.LabelFrame(self, text="Simulación / Heatmap", padding=8)
        sim_box.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        ttk.Button(sim_box, text="Ejecutar simulación", command=self._on_simulate).pack(
            fill="x", pady=(0, 6)
        )
        self._sim_text = tk.Text(
            sim_box, height=6, wrap="word", state="disabled",
            bg="#12121c", fg="#98c379", relief="flat", font=("Consolas", 9),
        )
        self._sim_text.pack(fill="x")

        ttk.Label(sim_box, text="Heatmap (grid):").pack(anchor="w", pady=(8, 2))
        self._heat_text = tk.Text(
            sim_box, height=12, wrap="word", state="disabled",
            bg="#12121c", fg="#4f9cf9", relief="flat", font=("Consolas", 9),
        )
        self._heat_text.pack(fill="both", expand=True)

        # Fase 14.2: orden canónico de los bloques. «Selección» y
        # «Simulación / Heatmap» son siempre visibles; los demás solo
        # cuando el elemento seleccionado corresponde, para que el panel
        # quepa en pantalla y el usuario vea qué puede editar.
        self._frames: list[tuple[str, ttk.LabelFrame, dict]] = [
            ("sel", sel_box, dict(fill="x", padx=8, pady=(8, 4))),
            ("ap", self._ap_radio_box, dict(fill="x", padx=8, pady=4)),
            ("wall", wall_box, dict(fill="x", padx=8, pady=4)),
            ("space", space_box, dict(fill="x", padx=8, pady=4)),
            ("opening", opening_box, dict(fill="x", padx=8, pady=4)),
            ("obstacle", obstacle_box, dict(fill="x", padx=8, pady=4)),
            ("pos", pos_box, dict(fill="x", padx=8, pady=4)),
            (
                "sim",
                sim_box,
                dict(fill="both", expand=True, padx=8, pady=(4, 8)),
            ),
        ]
        self._visible_frames: set[str] = set()

        self._refresh_materials()
        self.refresh()

    def _update_frame_visibility(self, kind) -> None:
        """Muestra solo los bloques relevantes para el elemento elegido.

        Presentación pura: no toca el modelo. Solo repackea cuando
        cambia el conjunto visible (evita parpadeos en cada refresh).
        """
        wanted = {"sel", "sim"}
        if kind == SelectionKind.AP:
            wanted |= {"ap", "pos"}
        elif kind == SelectionKind.WALL:
            wanted |= {"wall", "pos"}
        elif kind == SelectionKind.SPACE:
            wanted |= {"space", "pos"}
        elif kind == SelectionKind.OPENING:
            wanted |= {"opening"}
        elif kind == SelectionKind.OBSTACLE:
            wanted |= {"obstacle", "pos"}
        elif kind == SelectionKind.CLIENT:
            wanted |= {"pos"}

        if wanted == self._visible_frames:
            return
        for _name, widget, _kwargs in self._frames:
            widget.pack_forget()
        for name, widget, kwargs in self._frames:
            if name in wanted:
                widget.pack(**kwargs)
        self._visible_frames = wanted

    def show_heatmap_text(self, text: str) -> None:
        self._set_text(self._heat_text, text)

    def append_heatmap_text(self, text: str) -> None:
        self._heat_text.configure(state="normal")
        self._heat_text.insert("end", text)
        self._heat_text.configure(state="disabled")

    def _refresh_materials(self) -> None:
        materials = self._session.project.materials
        values = [m.id for m in materials]
        self._material_combo["values"] = values
        self._obstacle_material_combo["values"] = values

    def _refresh_ap_bands(self) -> None:
        """Banda del marco Radio desde el catálogo del proyecto (F10)."""
        self._ap_band_combo["values"] = [b.name for b in self._session.project.bands]

    def _ap_current_band(self):
        """Banda seleccionada en el combo (nombre → objeto) o None."""
        label = self._ap_band_var.get()
        for band in self._session.project.bands:
            if band.name == label:
                return band
        return None

    def _ap_display_band(self, ap):
        """Banda del AP para mostrar/editar: la configurada o la activa."""
        session = self._session
        if ap.band_id:
            return session.project.get_band(ap.band_id)
        return session.project.get_band(session.band_id)

    def _ap_update_freq_label(self) -> None:
        """Frecuencia central derivada del catálogo (nunca persistida)."""
        band = self._ap_current_band()
        raw = self._ap_channel_var.get().strip()
        if band is None or not raw:
            self._ap_freq_var.set("—")
            return
        try:
            channel = channel_for_band(band, int(raw))
        except ValueError:
            self._ap_freq_var.set("—")
            return
        self._ap_freq_var.set(f"{channel.center_frequency_mhz:g} MHz")

    def _ap_band_selected(self, _event=None) -> None:
        """Al cambiar la banda: canales y anchos de esa familia (F10).

        Si el canal elegido no existe en la banda nueva se propone el
        canal por defecto de esa banda y se avisa (Fase 14.2): nunca se
        conserva en silencio una configuración inválida.
        """
        band = self._ap_current_band()
        if band is None:
            return
        numbers = channel_numbers_for_frequency(band.frequency_mhz)
        self._ap_channel_combo["values"] = [str(n) for n in numbers]
        current = self._ap_channel_var.get().strip()
        try:
            current_int = int(current)
        except ValueError:
            current_int = None
        if current_int is not None and current_int in numbers:
            self._ap_channel_var.set(str(current_int))
            hint = f"{band.name}: el canal {current_int} sigue siendo válido."
        else:
            channel = default_channel(band).number
            self._ap_channel_var.set(str(channel))
            hint = (
                f"El canal {current or '—'} no existe en {band.name}: "
                f"se propone el canal {channel}."
            )
        widths = [str(w) for w in allowed_channel_widths_mhz(band.frequency_mhz)]
        self._ap_width_combo["values"] = widths
        if self._ap_width_var.get() not in widths:
            self._ap_width_var.set(widths[0])
        self._ap_update_freq_label()
        selected = self._session.selected_ap()
        self._ap_hint_for = selected.id if selected is not None else None
        self._ap_hint_var.set(hint)

    def _ap_channel_selected(self, _event=None) -> None:
        self._ap_update_freq_label()

    def _ap_load_controls(self, ap) -> None:
        """Sincroniza los controles Radio con el AP seleccionado."""
        if self._ap_hint_for != ap.id:
            # Cambió el AP: el aviso anterior ya no le corresponde.
            self._ap_hint_var.set("")
            self._ap_hint_for = ap.id
        self._refresh_ap_bands()
        band = self._ap_display_band(ap)
        self._ap_band_var.set(band.name)
        numbers = channel_numbers_for_frequency(band.frequency_mhz)
        self._ap_channel_combo["values"] = [str(n) for n in numbers]
        self._ap_channel_var.set(
            str(ap.channel)
            if ap.channel is not None
            else str(default_channel(band).number)
        )
        widths = [str(w) for w in allowed_channel_widths_mhz(band.frequency_mhz)]
        self._ap_width_combo["values"] = widths
        self._ap_width_var.set(str(ap.radio.channel_width_mhz))
        self._ap_update_freq_label()
        self._ap_standard_var.set(ap.radio.wifi_standard)
        self._ap_ptx_var.set(f"{ap.radio.p_tx_dbm:g}")
        self._ap_band_combo.configure(state="readonly")
        self._ap_channel_combo.configure(state="readonly")
        self._ap_width_combo.configure(state="readonly")
        self._ap_standard_combo.configure(state="readonly")
        self._ap_apply_btn.configure(state="normal")
        self._ap_reset_btn.configure(state="normal")

    def _ap_clear_controls(self) -> None:
        self._ap_band_var.set("")
        self._ap_channel_combo["values"] = []
        self._ap_channel_var.set("")
        self._ap_width_combo["values"] = []
        self._ap_width_var.set("")
        self._ap_freq_var.set("—")
        self._ap_standard_var.set("")
        self._ap_ptx_var.set("")
        self._ap_hint_var.set("")
        self._ap_hint_for = None
        self._ap_band_combo.configure(state="disabled")
        self._ap_channel_combo.configure(state="disabled")
        self._ap_width_combo.configure(state="disabled")
        self._ap_standard_combo.configure(state="disabled")
        self._ap_apply_btn.configure(state="disabled")
        self._ap_reset_btn.configure(state="disabled")

    def _ap_rf_lines(self, ap) -> list[str]:
        """Líneas de configuración RF del AP para el bloque Selección."""
        band = self._ap_display_band(ap)
        if ap.band_id:
            band_line = f"Banda: {band.name} (configurada)"
        else:
            band_line = f"Banda: — (activa: {band.name})"
        if ap.channel is not None:
            try:
                center = (
                    f"{channel_for_band(band, ap.channel).center_frequency_mhz:g} MHz"
                )
                channel_line = (
                    f"Canal: {ap.channel} ({center}) · "
                    f"Ancho: {ap.radio.channel_width_mhz:g} MHz"
                )
            except ValueError:
                channel_line = (
                    f"Canal: {ap.channel} (inválido para {band.name}) · "
                    f"Ancho: {ap.radio.channel_width_mhz:g} MHz"
                )
        else:
            channel_line = (
                f"Canal: — (sin configurar) · "
                f"Ancho: {ap.radio.channel_width_mhz:g} MHz"
            )
        generation = wifi_generation(ap.radio.wifi_standard, band.frequency_mhz)
        standard_line = f"Estándar: {ap.radio.wifi_standard} ({generation})"
        return [band_line, channel_line, standard_line]

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh(self) -> None:
        """Relee el modelo y actualiza los controles."""
        if self._suppress:
            return
        session = self._session
        selection = session.selection

        if selection is None:
            radio = session.project.radio
            thresholds = session.project.thresholds
            self._set_text(
                self._info,
                "Ningún elemento seleccionado.\n\n"
                "1. Elige una herramienta y dibuja en el plano.\n"
                "2. Pasa a «Seleccionar» y haz clic en un AP para\n"
                "   configurar su banda/canal en «Configuración RF\n"
                "   del AP», o en una pared para su material.\n"
                "3. Pulsa «Ejecutar simulación» para ver la cobertura.\n\n"
                "Configuración RF (Config RF…):\n"
                f"  Piso de ruido: {radio.noise_floor_dbm:g} dBm\n"
                f"  Objetivo RSSI: > {thresholds.rssi_target_dbm:g} dBm\n"
                f"  Objetivo SNR: ≥ {thresholds.snr_target_db:g} dB\n"
                f"  Objetivo SINR: ≥ {thresholds.sinr_target_db:g} dB\n"
                f"  Estándar: {radio.wifi_standard}\n"
                f"  Ancho de canal: {radio.channel_width_mhz:g} MHz",
            )
            self._material_combo.configure(state="disabled")
            self._thickness_entry.configure(state="disabled")
            self._x_var.set("")
            self._y_var.set("")
        elif selection.kind == SelectionKind.WALL:
            wall = session.selected_wall()
            if wall:
                length = wall.segment.length
                thick = (
                    wall.thickness_m
                    if wall.thickness_m is not None
                    else wall.material.thickness_default_m
                )
                self._set_text(
                    self._info,
                    f"Wall\n\n"
                    f"ID: {wall.id}\n"
                    f"Material: {wall.material.name} ({wall.material.id})\n"
                    f"Espesor: {thick} m\n"
                    f"Longitud: {length:.2f} m\n"
                    f"Inicio: ({wall.segment.start.x:.2f}, {wall.segment.start.y:.2f}) m\n"
                    f"Fin: ({wall.segment.end.x:.2f}, {wall.segment.end.y:.2f}) m",
                )
                self._material_combo.configure(state="readonly")
                self._thickness_entry.configure(state="normal")
                self._material_var.set(wall.material.id)
                self._thickness_var.set(f"{thick:.4g}")
                self._x_var.set("")
                self._y_var.set("")
        elif selection.kind == SelectionKind.AP:
            ap = session.selected_ap()
            if ap:
                rf_lines = self._ap_rf_lines(ap)
                # Fase 11: interferencia del AP (solo datos reales del
                # modelo; decisión CC). Se añaden después de las líneas
                # RF sin tocar su contenido (contrato F10 intacto).
                interference_lines = session.ap_interference_lines(ap.id)
                # Fase 12: diagnóstico complementario de SINR (decisión
                # CH). No sustituye a RSSI/SNR/interferencia.
                sinr_lines = session.ap_sinr_lines(ap.id)
                detail = "\n".join(
                    rf_lines + interference_lines + sinr_lines
                )
                self._set_text(
                    self._info,
                    f"Access Point\n\n"
                    f"ID: {ap.id}\n"
                    f"X: {ap.position.x:.2f} m\n"
                    f"Y: {ap.position.y:.2f} m\n"
                    f"{detail}",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set(f"{ap.position.x:.3f}")
                self._y_var.set(f"{ap.position.y:.3f}")
        elif selection.kind == SelectionKind.CLIENT:
            client = session.selected_client()
            if client:
                self._set_text(
                    self._info,
                    f"Cliente\n\n"
                    f"ID: {client.id}\n"
                    f"X: {client.position.x:.2f} m\n"
                    f"Y: {client.position.y:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set(f"{client.position.x:.3f}")
                self._y_var.set(f"{client.position.y:.3f}")
        elif selection.kind == SelectionKind.SPACE:
            space = session.selected_space()
            if space:
                rect = space.rect
                self._set_text(
                    self._info,
                    f"Espacio\n\n"
                    f"ID: {space.id}\n"
                    f"Nombre: {space.name}\n"
                    f"Función: {space.function or '—'}\n"
                    f"Rect: ({rect.x:.2f}, {rect.y:.2f}) + "
                    f"{rect.width:.2f} × {rect.height:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set("")
                self._y_var.set("")
        elif selection.kind == SelectionKind.OPENING:
            opening = session.selected_opening()
            if opening:
                wall = session.find_wall(opening.wall_id)
                wall_len = wall.segment.length if wall else 0.0
                self._set_text(
                    self._info,
                    f"Apertura ({opening.kind})\n\n"
                    f"ID: {opening.id}\n"
                    f"Pared: {opening.wall_id} ({wall_len:.2f} m)\n"
                    f"Tramo: [{opening.start_offset_m:.2f}, "
                    f"{opening.end_offset_m:.2f}] m\n"
                    f"Longitud: {opening.length_m:.2f} m",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set("")
                self._y_var.set("")
        elif selection.kind == SelectionKind.OBSTACLE:
            obstacle = session.selected_obstacle()
            if obstacle:
                rect = obstacle.rect
                override = ", ".join(
                    f"{band}={value:g}"
                    for band, value in sorted(
                        obstacle.attenuation_override_db.items()
                    )
                )
                self._set_text(
                    self._info,
                    f"Objeto\n\n"
                    f"ID: {obstacle.id}\n"
                    f"Nombre: {obstacle.name}\n"
                    f"Tipo: {obstacle.kind}\n"
                    f"Material: {obstacle.material.name} "
                    f"({obstacle.material.id})\n"
                    f"Rect: ({rect.x:.2f}, {rect.y:.2f}) + "
                    f"{rect.width:.2f} × {rect.height:.2f} m\n"
                    f"Override: {override or '—'}",
                )
                self._material_combo.configure(state="disabled")
                self._thickness_entry.configure(state="disabled")
                self._x_var.set("")
                self._y_var.set("")

        # --- Estados por tipo (recalculados en cada refresh) ---
        kind = selection.kind if selection is not None else None

        # --- Estados del marco Radio del AP (Fase 10) ---
        ap = session.selected_ap() if kind == SelectionKind.AP else None
        if ap is not None:
            self._ap_load_controls(ap)
        else:
            self._ap_clear_controls()

        # --- Estados de los controles Fase 8 (recalculados en cada refresh) ---
        space = session.selected_space() if kind == SelectionKind.SPACE else None
        opening = (
            session.selected_opening() if kind == SelectionKind.OPENING else None
        )
        wall = session.selected_wall() if kind == SelectionKind.WALL else None
        obstacle = (
            session.selected_obstacle() if kind == SelectionKind.OBSTACLE else None
        )

        if space is not None:
            self._space_name_var.set(space.name)
            self._space_function_var.set(space.function)
            self._space_name_entry.configure(state="normal")
            self._space_function_entry.configure(state="normal")
            self._space_apply_btn.configure(state="normal")
        else:
            self._space_name_entry.configure(state="disabled")
            self._space_function_entry.configure(state="disabled")
            self._space_apply_btn.configure(state="disabled")

        if opening is not None:
            self._opening_kind_var.set(opening.kind)
            self._opening_start_var.set(f"{opening.start_offset_m:.3f}")
            self._opening_end_var.set(f"{opening.end_offset_m:.3f}")
            self._opening_kind_combo.configure(state="readonly")
            self._opening_start_entry.configure(state="normal")
            self._opening_end_entry.configure(state="normal")
            self._opening_apply_btn.configure(state="normal")
        else:
            self._opening_kind_combo.configure(state="disabled")
            self._opening_start_entry.configure(state="disabled")
            self._opening_end_entry.configure(state="disabled")
            self._opening_apply_btn.configure(state="disabled")

        if wall is not None:
            count = len(session.openings_for_wall(wall.id))
            self._opening_count_var.set(str(count))
            self._add_door_btn.configure(state="normal")
            self._add_window_btn.configure(state="normal")
        else:
            self._opening_count_var.set("—")
            self._add_door_btn.configure(state="disabled")
            self._add_window_btn.configure(state="disabled")

        # --- Estados del marco Objeto (Fase 9) ---
        if obstacle is not None:
            self._obstacle_name_var.set(obstacle.name)
            self._obstacle_kind_var.set(obstacle.kind)
            self._obstacle_material_var.set(obstacle.material.id)
            self._obstacle_override_var.set(
                ", ".join(
                    f"{band}={value:g}"
                    for band, value in sorted(
                        obstacle.attenuation_override_db.items()
                    )
                )
            )
            self._obstacle_name_entry.configure(state="normal")
            self._obstacle_kind_combo.configure(state="readonly")
            self._obstacle_material_combo.configure(state="readonly")
            self._obstacle_override_entry.configure(state="normal")
            self._obstacle_apply_btn.configure(state="normal")
        else:
            self._obstacle_name_entry.configure(state="disabled")
            self._obstacle_kind_combo.configure(state="disabled")
            self._obstacle_material_combo.configure(state="disabled")
            self._obstacle_override_entry.configure(state="disabled")
            self._obstacle_apply_btn.configure(state="disabled")

        if session.last_simulation is not None or session.last_simulation_error:
            self._set_text(self._sim_text, session.simulation_summary_text())
        if session.last_heatmap is not None or session.last_heatmap_error:
            self._set_text(self._heat_text, session.heatmap_stats_text())

        # Fase 14.2: solo los bloques que aplican al elemento elegido.
        self._update_frame_visibility(kind)

    def show_simulation_text(self, text: str) -> None:
        self._set_text(self._sim_text, text)

    def _material_selected(self, _event=None) -> None:
        wall = self._session.selected_wall()
        if not wall:
            return
        try:
            self._session.set_wall_material(wall.id, self._material_var.get())
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Material", str(exc))
            return
        self._on_changed()

    def _thickness_apply(self, _event=None) -> None:
        wall = self._session.selected_wall()
        if not wall:
            return
        raw = self._thickness_var.get().strip().replace(",", ".")
        try:
            thickness = float(raw)
        except ValueError:
            messagebox.showerror("Espesor", f"Valor inválido: {raw!r}")
            return
        try:
            self._session.set_wall_thickness(wall.id, thickness)
        except ValueError as exc:
            messagebox.showerror("Espesor", str(exc))
            return
        self._on_changed()

    def _position_apply(self) -> None:
        session = self._session
        selection = session.selection
        if selection is None:
            return
        try:
            x = float(self._x_var.get().strip().replace(",", "."))
            y = float(self._y_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Posición", "Coordenadas inválidas (metros).")
            return
        from core.geometry import Point2D

        point = Point2D(x, y)
        try:
            if selection.kind == SelectionKind.AP:
                session.move_ap(selection.entity_id, point)
            elif selection.kind == SelectionKind.CLIENT:
                session.move_client(selection.entity_id, point)
            else:
                return
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Posición", str(exc))
            return
        self._on_changed()

    # ------------------------------------------------------------------
    # Fase 8: espacios y aperturas (solo CRUD vía sesión; nada de RF aquí)
    # ------------------------------------------------------------------

    def _space_apply(self) -> None:
        space = self._session.selected_space()
        if not space:
            return
        try:
            self._session.set_space_properties(
                space.id,
                self._space_name_var.get(),
                self._space_function_var.get(),
            )
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Espacio", str(exc))
            return
        self._on_changed()

    def _opening_apply(self) -> None:
        session = self._session
        opening = session.selected_opening()
        if not opening:
            return
        try:
            start = float(
                self._opening_start_var.get().strip().replace(",", ".")
            )
            end = float(self._opening_end_var.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Apertura", "Offsets inválidos (metros).")
            return
        kind = self._opening_kind_var.get()
        try:
            session.set_opening_offsets(opening.id, start, end)
            if kind != opening.kind:
                session.set_opening_kind(opening.id, kind)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Apertura", str(exc))
            return
        self._on_changed()

    def _add_opening(self, kind: str) -> None:
        wall = self._session.selected_wall()
        if not wall:
            return
        try:
            self._session.add_opening(wall.id, kind)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Apertura", str(exc))
            return
        self._on_changed()

    # ------------------------------------------------------------------
    # Fase 9: obstáculos (CRUD vía sesión; la pérdida vive en engine/)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_overrides(raw: str) -> dict[str, float]:
        """``"band_5=6, band_2_4=4"`` → ``{"band_5": 6.0, ...}`` (vacío: {})."""
        text = str(raw).strip()
        if not text:
            return {}
        result: dict[str, float] = {}
        for token in text.replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if "=" not in token:
                raise ValueError(
                    f"Formato inválido: {token!r} (usa band_id=dB, "
                    "separado por comas)."
                )
            key, _, value = token.partition("=")
            key = key.strip()
            if not key:
                raise ValueError(f"Band id vacío en {token!r}.")
            try:
                result[key] = float(value.strip().replace(",", "."))
            except ValueError:
                raise ValueError(f"Valor inválido en {token!r}.") from None
        return result

    def _obstacle_apply(self, _event=None) -> None:
        obstacle = self._session.selected_obstacle()
        if not obstacle:
            return
        try:
            override = self._parse_overrides(self._obstacle_override_var.get())
        except ValueError as exc:
            messagebox.showerror("Objeto", str(exc))
            return
        try:
            self._session.set_obstacle_properties(
                obstacle.id,
                self._obstacle_name_var.get(),
                kind=self._obstacle_kind_var.get(),
                material_id=self._obstacle_material_var.get() or None,
                attenuation_override_db=override,
            )
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Objeto", str(exc))
            return
        self._on_changed()

    # ------------------------------------------------------------------
    # Fase 10: configuración RF por AP (banda/canal/ancho; sin RF aquí)
    # ------------------------------------------------------------------

    def _ap_apply(self) -> None:
        """Aplica TODO el bloque de una vez (UNA entrada de undo).

        Transaccional: se validan todos los campos antes de tocar el
        modelo; si algo falla, el AP queda exactamente como estaba.
        """
        ap = self._session.selected_ap()
        if not ap:
            return
        band = self._ap_current_band()
        if band is None:
            messagebox.showerror("Configuración RF del AP", "Selecciona una banda.")
            return
        try:
            channel = int(self._ap_channel_var.get().strip())
            width = int(self._ap_width_var.get().strip())
        except ValueError:
            messagebox.showerror(
                "Configuración RF del AP", "Canal o ancho inválido."
            )
            return
        raw_ptx = self._ap_ptx_var.get().strip()
        try:
            p_tx = float(raw_ptx)
        except ValueError:
            messagebox.showerror(
                "Configuración RF del AP",
                f"Potencia TX inválida: {raw_ptx or 'vacía'} (usa un número en dBm).",
            )
            return
        standard = self._ap_standard_var.get().strip()
        if standard not in WIFI_STANDARDS:
            messagebox.showerror(
                "Configuración RF del AP", f"Estándar no soportado: {standard!r}."
            )
            return
        # La banda activa de la aplicación sigue a la del AP editado para
        # que la toolbar y el heatmap hablen de la misma banda (Fase 14.2).
        if ap_config_unchanged(
            ap,
            band_id=band.id,
            channel=channel,
            width_mhz=width,
            p_tx_dbm=p_tx,
            wifi_standard=standard,
        ):
            self._session.set_band(band.id)
            self._on_changed()
            self._ap_hint_for = ap.id
            self._ap_hint_var.set(
                "Sin cambios: el AP ya tiene esta configuración."
            )
            return
        try:
            self._session.set_ap_rf_config(
                ap.id,
                band_id=band.id,
                channel=channel,
                width_mhz=width,
                p_tx_dbm=p_tx,
                wifi_standard=standard,
            )
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Configuración RF del AP", str(exc))
            return
        self._session.set_band(band.id)
        self._on_changed()
        # El aviso se escribe DESPUÉS del refresh para que no se borre.
        self._ap_hint_for = ap.id
        self._ap_hint_var.set(
            f"Aplicado: {band.name} · canal {channel} · {width} MHz · "
            f"{p_tx:g} dBm · {standard}"
        )

    def _ap_reset(self) -> None:
        """Restablece los controles a los valores actuales del AP (cancelar)."""
        ap = self._session.selected_ap()
        if ap is None:
            return
        self._ap_load_controls(ap)
        self._ap_hint_for = ap.id
        self._ap_hint_var.set("Restablecido a los valores del AP.")
