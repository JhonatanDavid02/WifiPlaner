"""Paleta de colores y estilos del editor (solo UI)."""

from __future__ import annotations

# Etiquetas de estado de los clientes (misma fuente que la clasificación
# de ui/client_signal.py, para que color y texto no puedan divergir).
from ui.client_signal import (
    STATE_BUENA,
    STATE_DEBIL,
    STATE_FUERTE,
    STATE_INESTABLE,
    STATE_SIN_SENAL,
)

# Fondo general (tema oscuro)
BG = "#1e1e2e"
BG_PANEL = "#252536"
BG_CANVAS = "#12121c"
FG = "#e0e0e0"
FG_DIM = "#9a9aa8"
ACCENT = "#4f9cf9"
ACCENT_HOVER = "#6bb0ff"
DANGER = "#e06c75"
SUCCESS = "#98c379"
WARNING = "#e5c07b"

# Elementos del plano
FLOOR_FILL = "#1a1a28"
FLOOR_OUTLINE = "#5a5a72"
WALL_COLOR = "#d0d0e0"
WALL_SELECTED = "#4f9cf9"
WALL_PREVIEW = "#4f9cf9"
AP_COLOR = "#e5c07b"
AP_SELECTED = "#ffd866"
CLIENT_COLOR = "#98c379"
CLIENT_SELECTED = "#b8e986"
GRID_COLOR = "#2a2a3c"
TEXT_DIM = "#8a8aa0"
TEXT_LABEL = "#c0c0d0"

# Fase 8: espacios (zonas) y aperturas (puertas/ventanas)
SPACE_FILL = "#3a4a6b"
SPACE_OUTLINE = "#7a8ab0"
SPACE_SELECTED = "#4f9cf9"
SPACE_PREVIEW = "#4f9cf9"
DOOR_COLOR = "#e5c07b"
WINDOW_COLOR = "#56b6c2"
PASS_THROUGH_COLOR = "#c678dd"
OPENING_SELECTED = "#4f9cf9"

# Fase 9: obstáculos de mobiliario (footprints semisólidos, bajo paredes)
OBSTACLE_FILL = "#6b4a2f"
OBSTACLE_OUTLINE = "#b08050"
OBSTACLE_SELECTED = "#4f9cf9"
OBSTACLE_PREVIEW = "#4f9cf9"
#: Herramienta medir (Fase 14-F): línea y etiqueta de distancia.
MEASURE_COLOR = "#e5c07b"

# Estado de la señal en la posición de cada cliente (indicador del
# plano). El color describe el RSSI medido ahí (ui/client_signal.py);
# NO se lee del heatmap, que es solo pintura del resultado.
CLIENT_STATE_BUENA = "#8affc1"      # verde claro
CLIENT_STATE_FUERTE = "#3ddc84"     # verde
CLIENT_STATE_DEBIL = "#ffd166"      # amarillo
CLIENT_STATE_INESTABLE = "#ff5f56"  # rojo
CLIENT_STATE_SIN = "#8b93a1"        # gris

CLIENT_STATE_COLOR = {
    STATE_BUENA: CLIENT_STATE_BUENA,
    STATE_FUERTE: CLIENT_STATE_FUERTE,
    STATE_DEBIL: CLIENT_STATE_DEBIL,
    STATE_INESTABLE: CLIENT_STATE_INESTABLE,
    STATE_SIN_SENAL: CLIENT_STATE_SIN,
}

# Controles ttk (estilo)
STYLE_MAP = {
    "TFrame": {"background": [("active", BG), ("!active", BG)]},
    "TLabelframe": {
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
    },
    "TLabelframe.Label": {
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
    },
    "TLabel": {
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
    },
    "TButton": {
        "background": [("active", ACCENT_HOVER), ("!active", ACCENT)],
        "foreground": [("active", "#ffffff"), ("!active", "#ffffff")],
        "padding": [8, 4],
    },
    "Toolbutton": {
        "background": [("active", ACCENT_HOVER), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
        "padding": [8, 4],
    },
    # TCheckbutton y TSeparator no estaban en la paleta: clam los deja
    # con fondo gris claro y texto NEGRO sobre el panel oscuro.
    "TCheckbutton": {
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
        "padding": [4, 4],
    },
    "TSeparator": {
        "background": [("active", FLOOR_OUTLINE), ("!active", FLOOR_OUTLINE)],
    },
    "TMenubutton": {
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
    },
    "TCombobox": {
        "fieldbackground": [("active", BG), ("!active", BG)],
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG), ("!active", FG)],
        "arrowcolor": [("active", FG), ("!active", FG)],
    },
    "TEntry": {
        "fieldbackground": [("active", BG), ("!active", BG)],
        "foreground": [("active", FG), ("!active", FG)],
        "insertcolor": [("active", FG), ("!active", FG)],
    },
    "TSpinbox": {
        "fieldbackground": [("active", BG), ("!active", BG)],
        "foreground": [("active", FG), ("!active", FG)],
        "arrowcolor": [("active", FG), ("!active", FG)],
    },
    "StatusBar.TLabel": {
        "background": [("active", BG_PANEL), ("!active", BG_PANEL)],
        "foreground": [("active", FG_DIM), ("!active", FG_DIM)],
    },
}
