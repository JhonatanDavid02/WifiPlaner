"""Estado del editor: operaciones puras sobre Project (sin Tkinter).

Esta capa es testeable sin abrir la ventana. La UI (Canvas/panels)
la invoca y luego vuelve a dibujar desde el Project (fuente de verdad).
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from functools import wraps
from typing import Iterable

from core.access_point import AccessPoint
from core.channel import validate_channel_config
from core.client import ClientDevice
from core.geometry import Point2D, Rect, Segment2D
from core.material import Material
from core.obstacle import (
    DEFAULT_OBSTACLE_MATERIAL_ID,
    MIN_OBSTACLE_SIZE_M,
    OBSTACLE_KINDS,
    Obstacle,
)
from core.project import Project
from core.radio import wifi_generation
from core.result import SimulationResult
from core.space import MIN_SPACE_SIZE_M, Floor, Space
from core.wall import (
    DEFAULT_OPENING_LENGTH_M,
    MIN_OPENING_LENGTH_M,
    OPENING_KINDS,
    Opening,
    Wall,
)
from engine.classifier import rf_diagnostic, sinr_diagnostic
from engine.combine import combine_results
from engine import channel_optimization
from engine.channel_optimization import OptimizationTarget
from engine.coverage_grid import CoverageGrid
from engine.interference import (
    annotate_interference,
    emission_for_ap,
    interference_summary,
)
from engine.simulator import simulate_coverage
from engine.sinr import annotate_sinr, sinr_stats_block
from persistence import EditorState
from persistence import load_project as _load_document
from persistence import save_project as _save_document
# Registro único de métricas del heatmap (F7: rssi/snr; F11 añade
# «interference» — decisión CC; F12 añade «sinr» — decisión CH: el enum
# HeatmapMetric está congelado por contrato F7, así que la validación
# usa el registro del renderer).
from ui.coverage_renderer import (
    HEATMAP_METRIC_INTERFERENCE,
    HEATMAP_METRIC_SINR,
    HEATMAP_METRICS,
)
from ui.geometry_view import GeometryView, build_geometry_view

# Selector de heatmap: todos los APs (cobertura combinada, Fase 5).
HEATMAP_ALL_APS = "__all__"


class Tool(str, Enum):
    """Herramientas del editor."""

    SELECT = "select"
    WALL = "wall"
    AP = "ap"
    CLIENT = "client"
    SPACE = "space"
    # Fase 9: mobiliario/obstáculos (tecla "o", patrón de 2 clics).
    OBSTACLE = "obstacle"
    # Fase 14-F: medir distancias en metros (tecla "m").
    MEASURE = "measure"


class HeatmapMetric(str, Enum):
    """Métrica visual del heatmap (Fase 7): RSSI o SNR.

    Es una vista, no configuración del proyecto: no se persiste ni
    marca ``dirty`` (decisión BA).

    El enum queda CONGELADO con los valores de F7 (contrato de tests);
    la métrica de interferencia de F11 vive en
    ``ui.coverage_renderer.HEATMAP_METRICS`` (decisión CC).
    """

    RSSI = "rssi"
    SNR = "snr"


def _standard_label(project: Project, frequency_mhz: float) -> str:
    """Etiqueta del estándar del proyecto para una banda (Fase 7).

    Ej.: ``802.11ax (Wi-Fi 6)`` o ``802.11ax (Wi-Fi 6E)`` a 6 GHz.
    """
    standard = project.radio.wifi_standard
    return f"{standard} ({wifi_generation(standard, frequency_mhz)})"


class SelectionKind(str, Enum):
    WALL = "wall"
    AP = "ap"
    CLIENT = "client"
    SPACE = "space"
    OPENING = "opening"
    # Fase 9: obstáculos de mobiliario.
    OBSTACLE = "obstacle"


@dataclass(frozen=True)
class Selection:
    """Elemento seleccionado en el editor."""

    kind: SelectionKind
    entity_id: str


def next_entity_id(existing_ids: Iterable[str], prefix: str) -> str:
    """Genera el siguiente ID estable: AP-001, WALL-001, CLIENT-001."""
    max_n = 0
    token = f"{prefix}-"
    for entity_id in existing_ids:
        if entity_id.startswith(token):
            suffix = entity_id[len(token) :]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"{prefix}-{max_n + 1:03d}"


#: Tamaño de ejemplo por defecto del proyecto nuevo (explícito, no un
#: fallback): el diálogo «Nuevo…» permite cambiarlo y los proyectos
#: abiertos usan siempre sus propias dimensiones (Fase 14-B).
DEFAULT_FLOOR_WIDTH_M: float = 12.0
DEFAULT_FLOOR_HEIGHT_M: float = 8.0

#: Pasos de rejilla que ofrece la UI (metros) — Fase 14-E.
GRID_STEP_CHOICES: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0)

#: Profundidad máxima de la pila de deshacer (Fase 14-G).
MAX_UNDO_STEPS = 50


def undoable(method):
    """Registra el estado previo del documento si la operación termina bien.

    Decorador de los métodos mutantes de ``EditorSession``: captura una
    copia profunda de ``project`` (más la selección) antes de ejecutar y
    solo confirma el paso si NO hubo excepción — una operación rechazada
    no deja pasos huérfanos. Las llamadas anidadas (p. ej. ``move_wall``
    → ``set_wall_endpoints``) se anotan una sola vez, y durante
    undo/redo la grabación queda desactivada.

    Fase 14.1: mientras hay un gesto abierto (``begin_edit``) la
    operación se ejecuta pero **no** apila un snapshot; solo marca el
    gesto como tocado. La transición única se registra en el
    ``commit_edit`` que cierra el arrastre.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self._undo_enabled or self._undo_recording:
            return method(self, *args, **kwargs)
        if self._gesture_active:
            result = method(self, *args, **kwargs)
            self._gesture_touched = True
            return result
        previous = (deepcopy(self.project), self.selection)
        self._undo_recording = True
        try:
            result = method(self, *args, **kwargs)
        finally:
            self._undo_recording = False
        self._push_undo(previous)
        return result

    return wrapper


def snap_point_to_grid(point: Point2D, step_m: float) -> Point2D:
    """Redondea cada coordenada al múltiplo de ``step_m`` más cercano.

    Función pura (sin Tk) usada por el canvas cuando la rejilla está
    activa (``EditorSession.snap_to_grid``).

    Raises:
        ValueError: si el paso no es finito o es ≤ 0.
    """
    step = float(step_m)
    if not math.isfinite(step) or step <= 0:
        raise ValueError(f"Paso de rejilla inválido: {step_m}.")
    return Point2D(
        round(point.x / step) * step,
        round(point.y / step) * step,
    )


def create_default_project(
    width_m: float = DEFAULT_FLOOR_WIDTH_M,
    height_m: float = DEFAULT_FLOOR_HEIGHT_M,
) -> Project:
    """Proyecto inicial del editor (12 m × 8 m por defecto, sin elementos).

    Args:
        width_m: Ancho del piso en metros (> 0, ≤ 10000).
        height_m: Alto del piso en metros (> 0, ≤ 10000).

    Raises:
        ValueError: si las dimensiones no son válidas (sin fallback).
    """
    from config import load_config

    if width_m <= 0 or height_m <= 0:
        raise ValueError(f"Dimensiones deben ser > 0 m (got {width_m}×{height_m}).")
    if width_m > 10_000 or height_m > 10_000:
        raise ValueError("Máximo 10000 m por lado.")
    cfg = load_config()
    project = Project(
        name="Wi-Fi Planner — Proyecto nuevo",
        bands=cfg["bands"],
        materials=cfg["materials"],
        radio=cfg["radio"],
        thresholds=cfg["thresholds"],
    )
    floor = Floor(
        id="FLOOR-001",
        name="Planta baja",
        width_m=width_m,
        height_m=height_m,
    )
    project.floors.append(floor)
    return project


class EditorSession:
    """Operaciones del editor sobre el Project (sin UI).

    La fuente de verdad es siempre ``project``. El Canvas solo pinta.
    """

    def __init__(self, project: Project | None = None) -> None:
        self.project = project if project is not None else create_default_project()
        # Piso activo (Fase 14-C): None = primer piso del proyecto.
        self.active_floor_id: str | None = None
        self.tool: Tool = Tool.SELECT
        self.selection: Selection | None = None
        # Punto de inicio mientras se dibuja una pared (metros).
        self.wall_drag_start: Point2D | None = None
        # Fase 8: punto de inicio mientras se dibuja un espacio (metros).
        self.space_drag_start: Point2D | None = None
        # Fase 9: punto de origen mientras se dibuja un obstáculo (metros).
        self.obstacle_drag_start: Point2D | None = None
        self.band_id: str = "band_2_4"
        self.last_simulation: SimulationResult | None = None
        self.last_simulation_error: str | None = None
        # Fase 4: heatmap espacial
        self.grid_resolution_m: float = 0.5
        self.heatmap_enabled: bool = True
        # Fase 14-E: rejilla visible + snap (preferencias de vista; la
        # resolución del grid RF es grid_resolution_m, otra cosa).
        self.grid_step_m: float = 0.5
        self.snap_to_grid: bool = True
        # Fase 14-F: estado de la herramienta medir (vista; no persistible).
        self.measure_anchor: Point2D | None = None
        self.measure_cursor: Point2D | None = None
        # Fase 14-G: deshacer/rehacer por snapshots del documento.
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._undo_enabled: bool = True
        self._undo_recording: bool = False
        # Fase 14.1: gesto interactivo (arrastre) = UNA entrada de historial.
        self._gesture_active: bool = False
        self._gesture_snapshot = None
        self._gesture_dirty: bool = False
        self._gesture_touched: bool = False
        # Fase 5: HEATMAP_ALL_APS (combinado) o id de un AP concreto.
        self.heatmap_ap_id: str = HEATMAP_ALL_APS
        # Fase 7: métrica visual del heatmap (vista; no persistible).
        self.heatmap_metric: str = HeatmapMetric.RSSI.value
        self.last_heatmap: SimulationResult | None = None
        self.last_heatmap_error: str | None = None
        self.heatmap_dirty: bool = True
        # Fase 6: persistencia. Ruta del documento y cambios sin guardar.
        self.project_path: str | None = None
        self.dirty: bool = False

    # ------------------------------------------------------------------
    # Cambios sin guardar (Fase 6)
    # ------------------------------------------------------------------

    def mark_dirty(self) -> None:
        """Marca el proyecto como modificado desde la última guarda."""
        self.dirty = True

    def mark_saved(self, path: str | None = None) -> None:
        """Marca el proyecto como guardado (opcionalmente en una ruta)."""
        if path is not None:
            self.project_path = str(path)
        self.dirty = False

    # ------------------------------------------------------------------
    # Fase 14-G: deshacer / rehacer (snapshots del documento)
    # ------------------------------------------------------------------

    def _push_undo(self, snapshot) -> None:
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > MAX_UNDO_STEPS:
            del self._undo_stack[0]
        # Una acción nueva invalida la rama de rehacer.
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        """True si hay al menos un paso para deshacer."""
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """True si hay al menos un paso para rehacer."""
        return bool(self._redo_stack)

    def clear_history(self) -> None:
        """Vacía deshacer/rehacer (al abrir o crear un documento)."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._reset_gesture()

    def undo(self) -> bool:
        """Restaura el estado anterior del documento. True si había paso.

        El estado actual se mueve a la pila de rehacer; el documento
        queda como ``dirty`` (ya no coincide con lo guardado en disco).

        Fase 14.1: si hay un gesto abierto, ``Ctrl+Z`` lo **cancela**
        (restaura el estado previo al arrastre) sin tocar las pilas.
        """
        if self._gesture_active:
            self.cancel_edit()
            return True
        if not self._undo_stack:
            return False
        current = (deepcopy(self.project), self.selection)
        previous_project, previous_selection = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._apply_history(previous_project, previous_selection)
        return True

    def redo(self) -> bool:
        """Reaplica el paso deshecho. True si había paso."""
        if self._gesture_active:
            # Un gesto a medias no puede coexistir con un redo: se aborta
            # para no apilar un snapshot de un documento ya cambiado.
            self.cancel_edit()
        if not self._redo_stack:
            return False
        current = (deepcopy(self.project), self.selection)
        next_project, next_selection = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._apply_history(next_project, next_selection)
        return True

    def _apply_history(self, project: Project, selection) -> None:
        """Cambia el documento a un snapshot SIN grabar otro undo step."""
        self._undo_enabled = False
        try:
            self.project = project
            self.selection = selection
            self.invalidate_heatmap()
            self.mark_dirty()
        finally:
            self._undo_enabled = True

    # ------------------------------------------------------------------
    # Fase 14.1: gestos interactivos (UNA entrada de historial por gesto)
    # ------------------------------------------------------------------

    def _reset_gesture(self) -> None:
        """Descarta el gesto en curso sin tocar el documento."""
        self._gesture_active = False
        self._gesture_snapshot = None
        self._gesture_dirty = False
        self._gesture_touched = False

    @property
    def gesture_active(self) -> bool:
        """True mientras hay un arrastre abierto (sin ``commit_edit``)."""
        return self._gesture_active

    def begin_edit(self) -> None:
        """Congela el estado previo a un gesto interactivo (arrastre).

        Mientras el gesto está abierto, las operaciones ``@undoable``
        se ejecutan normalmente pero NO apilan snapshots intermedios.
        El gesto se cierra con ``commit_edit`` (una sola entrada) o con
        ``cancel_edit`` (restauración sin historial).

        Un ``begin_edit`` anidado conserva la foto inicial: el primer
        punto de partida es el que vale para todo el gesto.
        """
        if self._gesture_active:
            return
        self._gesture_snapshot = (deepcopy(self.project), self.selection)
        self._gesture_dirty = self.dirty
        self._gesture_touched = False
        self._gesture_active = True

    def commit_edit(self) -> bool:
        """Cierra el gesto registrando exactamente UN paso de historial.

        Returns:
            True si se apiló un paso; False si no hubo cambio real
            (gesto sin ediciones, o gesto que terminó donde empezó).

        El límite de historial (``MAX_UNDO_STEPS``), la invalidación del
        heatmap y el marcado ``dirty`` siguen siendo los de ``_push_undo``.
        """
        if not self._gesture_active:
            return False
        snapshot = self._gesture_snapshot
        touched = self._gesture_touched
        dirty_before = self._gesture_dirty
        self._reset_gesture()
        if snapshot is None or not touched:
            return False
        previous_project, _previous_selection = snapshot
        if self.project == previous_project:
            # El gesto volvió al punto de partida: nada que deshacer.
            self.dirty = dirty_before
            return False
        self._push_undo(snapshot)
        return True

    def cancel_edit(self) -> None:
        """Aborta el gesto restaurando el estado previo (sin historial)."""
        if not self._gesture_active:
            return
        snapshot = self._gesture_snapshot
        dirty_before = self._gesture_dirty
        self._reset_gesture()
        if snapshot is None:
            return
        project, selection = snapshot
        self._undo_enabled = False
        try:
            self.project = project
            self.selection = selection
            self.invalidate_heatmap()
            self.dirty = dirty_before
        finally:
            self._undo_enabled = True

    # ------------------------------------------------------------------
    # Persistencia (Fase 6): guardar / abrir / nuevo
    # ------------------------------------------------------------------

    def editor_state(self) -> EditorState:
        """Preferencias persistibles del editor (banda y resolución)."""
        return EditorState(
            band_id=self.band_id, grid_resolution_m=self.grid_resolution_m
        )

    def save_project(self, path: str | None = None) -> str:
        """Guarda el proyecto en JSON.

        Args:
            path: Ruta destino. Si es None se usa ``project_path``.

        Raises:
            ValueError: si el proyecto aún no tiene ruta (usar “Guardar como…”).
            ProjectFormatError: el proyecto no serializa/valida.
            OSError: fallo de escritura (el archivo previo queda intacto).
        """
        target = path if path is not None else self.project_path
        if target is None:
            raise ValueError("El proyecto no tiene ruta; usa “Guardar como…”.")
        written = _save_document(
            self.project, target, editor_state=self.editor_state()
        )
        self.mark_saved(str(written))
        return str(written)

    def save_project_as(self, path: str) -> str:
        """Guarda el proyecto en otra ruta y la asocia al documento."""
        return self.save_project(path)

    def open_project(self, path: str) -> None:
        """Carga un proyecto JSON y lo deja como documento activo.

        Si el archivo es inválido lanza ``ProjectFormatError`` y el
        proyecto actual queda intacto (sin estado parcial).
        """
        project, editor_state = _load_document(path)
        self._replace_document(project, editor_state, path=str(path))

    def new_project(
        self,
        width_m: float = DEFAULT_FLOOR_WIDTH_M,
        height_m: float = DEFAULT_FLOOR_HEIGHT_M,
    ) -> None:
        """Crea un proyecto vacío con las dimensiones dadas y limpia el documento.

        Args:
            width_m: Ancho del piso en metros (lo elige el usuario en la UI).
            height_m: Alto del piso en metros (lo elige el usuario en la UI).

        Raises:
            ValueError: dimensiones inválidas (el documento queda intacto).
        """
        project = create_default_project(width_m, height_m)
        self._replace_document(project, EditorState(), path=None)

    def _replace_document(
        self, project: Project, editor_state: EditorState, path: str | None
    ) -> None:
        """Intercambia el documento y reinicia el estado transitorio.

        Solo se conserva del archivo lo que es ``Project`` + configuración
        persistible; la selección, el heatmap y las simulaciones se
        regeneran (decisión AB/AC, docs/decisions.md).
        """
        self.project = project
        self.active_floor_id = None
        self.project_path = path
        self.measure_anchor = None
        self.measure_cursor = None
        # Documento nuevo/cargado: el historial anterior ya no aplica.
        self.clear_history()
        self.tool = Tool.SELECT
        self.selection = None
        self.wall_drag_start = None
        self.space_drag_start = None
        self.obstacle_drag_start = None
        self.band_id = editor_state.band_id
        self.grid_resolution_m = editor_state.grid_resolution_m
        self.heatmap_ap_id = HEATMAP_ALL_APS
        self.heatmap_metric = HeatmapMetric.RSSI.value
        self.heatmap_enabled = True
        self.last_simulation = None
        self.last_simulation_error = None
        self.last_heatmap = None
        self.last_heatmap_error = None
        self.invalidate_heatmap()
        self.dirty = False

    # ------------------------------------------------------------------
    # Piso / dimensiones
    # ------------------------------------------------------------------

    @property
    def active_floor(self) -> Floor:
        """Piso activo; todo el CRUD (walls/spaces/openings/obstacles) opera aquí.

        Si ``active_floor_id`` apunta a un piso ya borrado, se vuelve al
        primero; si el proyecto no tiene pisos, se crea el contenedor SIN
        dimensiones (Fase 14-B: nada de 12×8 implícito).
        """
        if self.active_floor_id is not None:
            for candidate in self.project.floors:
                if candidate.id == self.active_floor_id:
                    return candidate
            self.active_floor_id = None
        if not self.project.floors:
            self.project.floors.append(Floor(id="FLOOR-001", name="Planta baja"))
        return self.project.floors[0]

    @property
    def floor(self) -> Floor:
        """Piso activo (alias de ``active_floor``; compatible con Fases 4–13)."""
        return self.active_floor

    def set_active_floor(self, floor_id: str) -> None:
        """Selecciona el piso activo (Fase 14-C).

        Raises:
            ValueError: si no existe ningún piso con ese id.
        """
        target = None
        for candidate in self.project.floors:
            if candidate.id == floor_id:
                target = candidate
                break
        if target is None:
            raise ValueError(f"Piso desconocido: {floor_id!r}")
        # Mismo piso (aunque active_floor_id aún normalizara a None): no-op.
        if self.active_floor is not target:
            self.active_floor_id = floor_id
            # El heatmap pertenece al piso que se estaba pintando.
            self.invalidate_heatmap()

    @property
    def geometry_view(self) -> GeometryView:
        """Vista inmutable de solo lectura del piso activo (Fase 14-C)."""
        return build_geometry_view(
            self.active_floor,
            access_points=self.project.access_points,
            clients=self.project.clients,
        )

    @property
    def floor_width_m(self) -> float:
        width = self.floor.width_m
        if width is None:
            raise ValueError(
                "El piso no tiene ancho definido: usa set_floor_dimensions() "
                "o el diálogo «Dimensiones…» antes de simular o dibujar."
            )
        return float(width)

    @property
    def floor_height_m(self) -> float:
        height = self.floor.height_m
        if height is None:
            raise ValueError(
                "El piso no tiene alto definido: usa set_floor_dimensions() "
                "o el diálogo «Dimensiones…» antes de simular o dibujar."
            )
        return float(height)

    @undoable
    def set_floor_dimensions(self, width_m: float, height_m: float) -> None:
        """Valida y aplica nuevas dimensiones del espacio (metros).

        Además de los límites del piso, comprueba que la resolución
        actual siga produciendo un grid usable: el invariante
        «dimensiones + resolución ⇒ grid válido» se mantiene en ambos
        cambios de entrada (dimensiones y resolución), para que el
        proyecto siempre sea simulable y guardable.
        """
        floor = self.floor
        previous = (floor.width_m, floor.height_m)
        floor.set_dimensions(width_m, height_m)  # valida > 0 y <= 10000 m
        try:
            probe = CoverageGrid(
                width_m=float(floor.width_m),
                height_m=float(floor.height_m),
                resolution_m=self.grid_resolution_m,
            )
            if probe.point_count <= 0:
                raise ValueError("Grid vacío con esas dimensiones/resolución.")
        except ValueError as exc:
            floor.width_m, floor.height_m = previous
            raise ValueError(
                f"Dimensiones incompatibles con la resolución "
                f"{self.grid_resolution_m:g} m: {exc}"
            ) from exc
        self.invalidate_heatmap()
        self.mark_dirty()

    def set_grid_resolution(self, resolution_m: float) -> None:
        """Resolución del CoverageGrid en metros (> 0, con límite mínimo)."""
        resolution = float(resolution_m)
        if resolution <= 0:
            raise ValueError(f"Resolución debe ser > 0 (got {resolution}).")
        # La validación completa (mín. / máx. puntos) ocurre al construir el grid.
        probe = CoverageGrid(
            width_m=self.floor_width_m,
            height_m=self.floor_height_m,
            resolution_m=resolution,
        )
        if probe.point_count <= 0:
            raise ValueError("Grid vacío con esa resolución.")
        self.grid_resolution_m = resolution
        self.invalidate_heatmap()
        self.mark_dirty()

    def set_grid_step(self, step_m: float) -> None:
        """Paso de la rejilla visible y del snap en metros (Fase 14-E).

        Es una preferencia de vista: NO se marca ``dirty`` ni se
        persiste (schema v1 intacto).
        """
        step = float(step_m)
        if not math.isfinite(step) or step <= 0:
            raise ValueError(f"Paso de rejilla debe ser > 0 (got {step_m}).")
        if step > 1000:
            raise ValueError(f"Paso de rejilla demasiado grande: {step} m.")
        self.grid_step_m = step

    def set_snap_to_grid(self, enabled: bool) -> None:
        """Activa/desactiva el snap a rejilla (preferencia de vista)."""
        self.snap_to_grid = bool(enabled)

    # ------------------------------------------------------------------
    # Fase 14-F: herramienta medir (siempre en metros, nunca en píxeles)
    # ------------------------------------------------------------------

    def set_measure_anchor(self, point: Point2D | None) -> None:
        """Fija el primer punto de la medición (None la limpia).

        Raises:
            ValueError: si el punto no es finito.
        """
        if point is not None:
            x, y = self._finite_point(point)
            point = Point2D(x, y)
        self.measure_anchor = point
        self.measure_cursor = point

    def set_measure_cursor(self, point: Point2D | None) -> None:
        """Actualiza el segundo punto (el que sigue al cursor).

        Raises:
            ValueError: si el punto no es finito.
        """
        if point is not None:
            x, y = self._finite_point(point)
            point = Point2D(x, y)
        self.measure_cursor = point

    def measure_distance_m(self) -> float | None:
        """Distancia ancla→cursor en METROS, o None si no hay medición."""
        if self.measure_anchor is None or self.measure_cursor is None:
            return None
        return self.measure_anchor.distance_to(self.measure_cursor)

    @undoable
    def apply_rf_settings(
        self,
        *,
        noise_floor_dbm: float,
        snr_target_db: float,
        rssi_target_dbm: float,
        wifi_standard: str,
        channel_width_mhz: int,
        sinr_target_db: float | None = None,
    ) -> None:
        """Configuración RF global (Fase 7 + 12): ruido, umbrales, estándar, ancho.

        Atómico: radio y thresholds se construyen con ``replace`` ANTES de
        tocar el proyecto; si la validación falla (``ValueError``), nada
        cambia. Después se sincroniza la radio de los APs existentes
        (F7 sin configuración por AP) y se invalida el heatmap.

        ``sinr_target_db`` (F12) es opcional: ``None`` conserva el
        objetivo actual (compatibilidad con los llamadores F7).
        """
        radio = replace(
            self.project.radio,
            noise_floor_dbm=float(noise_floor_dbm),
            channel_width_mhz=int(channel_width_mhz),
            wifi_standard=str(wifi_standard),
        )
        threshold_updates: dict = {
            "rssi_target_dbm": float(rssi_target_dbm),
            "snr_target_db": float(snr_target_db),
        }
        if sinr_target_db is not None:
            threshold_updates["sinr_target_db"] = float(sinr_target_db)
        thresholds = replace(self.project.thresholds, **threshold_updates)
        # Hasta aquí solo se validó: ahora la mutación es segura.
        self.project.radio = radio
        self.project.thresholds = thresholds
        for ap in self.project.access_points:
            ap.radio = replace(
                ap.radio,
                noise_floor_dbm=radio.noise_floor_dbm,
                channel_width_mhz=radio.channel_width_mhz,
                wifi_standard=radio.wifi_standard,
            )
        self.invalidate_heatmap()
        self.mark_dirty()

    def set_band(self, band_id: str) -> None:
        """Cambia la banda activa y invalida el heatmap (no reutiliza 2.4→5)."""
        self.project.get_band(band_id)  # valida existencia
        if band_id != self.band_id:
            self.band_id = band_id
            self.invalidate_heatmap()
            self.mark_dirty()

    # ------------------------------------------------------------------
    # Configuración RF por AP (Fase 10: banda + canal + ancho)
    # ------------------------------------------------------------------

    def resolve_band_for_ap(
        self, ap: AccessPoint, default_band_id: str | None = None
    ):
        """Banda con la que se simula un AP (decisión BS).

        Usa ``ap.band_id`` si el AP tiene banda configurada; si no, la
        banda activa (o ``default_band_id`` durante una corrida). Los
        proyectos F1–F9 no definen ``band_id`` ⇒ resultado idéntico al de
        F9. La frecuencia de FSPL sigue siendo la de la banda resuelta;
        el canal del AP NO modifica la física (decisión BR/BW).

        Raises:
            KeyError: si la banda referenciada no existe.
        """
        band_id = ap.band_id or default_band_id or self.band_id
        return self.project.get_band(band_id)

    @undoable
    def set_ap_rf_config(
        self, ap_id: str, *, band_id: str, channel: int, width_mhz: int
    ) -> None:
        """Configura banda + canal + ancho de un AP de forma atómica (F10).

        El triple se valida contra el catálogo de canales
        (``core.channel.validate_channel_config``, decisión BT) ANTES de
        tocar el proyecto: si algo falla, nada cambia y no se marca
        ``dirty``. Si los valores son idénticos a los actuales no hay
        mutación (decisión BU: dirty solo si el proyecto cambió).

        Invalida el heatmap con la invalidación genérica del pipeline
        F4: el canal en sí no altera RSSI (decisión BR), pero la banda
        configurada sí determina la frecuencia de simulación del AP y
        el cambio es configuración persistible.

        Raises:
            KeyError: si el AP o la banda no existen.
            ValueError: si el canal o el ancho no son válidos para la banda.
        """
        for index, ap in enumerate(self.project.access_points):
            if ap.id == ap_id:
                band = self.project.get_band(band_id)  # valida existencia
                validate_channel_config(band, channel, width_mhz)
                if (
                    ap.band_id == band_id
                    and ap.channel == channel
                    and ap.radio.channel_width_mhz == width_mhz
                ):
                    return  # sin cambio real: sin dirty ni invalidación
                radio = replace(ap.radio, channel_width_mhz=int(width_mhz))
                self.project.access_points[index] = replace(
                    ap, band_id=band_id, channel=int(channel), radio=radio
                )
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Access Point no encontrado: {ap_id}")

    def set_heatmap_enabled(self, enabled: bool) -> None:
        self.heatmap_enabled = bool(enabled)
        if enabled:
            self.invalidate_heatmap()

    def invalidate_heatmap(self) -> None:
        """Marca el heatmap como no válido (no sirve el resultado anterior)."""
        self.heatmap_dirty = True

    def build_coverage_grid(self) -> CoverageGrid:
        """Grid espacial del piso con la resolución actual (metros)."""
        return CoverageGrid(
            width_m=self.floor_width_m,
            height_m=self.floor_height_m,
            resolution_m=self.grid_resolution_m,
        )

    def set_heatmap_ap(self, ap_id: str | None) -> None:
        """Selector del heatmap: ``HEATMAP_ALL_APS`` o un id de AP concreto.

        Invalida el heatmap al cambiar el ámbito (combinado ↔ individual).
        """
        if ap_id is None or ap_id == HEATMAP_ALL_APS:
            new_id = HEATMAP_ALL_APS
        else:
            # Debe existir en el proyecto
            found = any(ap.id == ap_id for ap in self.project.access_points)
            if not found:
                raise KeyError(f"Access Point no encontrado: {ap_id}")
            new_id = ap_id
        if new_id != self.heatmap_ap_id:
            self.heatmap_ap_id = new_id
            self.invalidate_heatmap()

    def set_heatmap_metric(self, metric: str) -> None:
        """Métrica visual del heatmap: ``rssi``, ``snr``, ``interference`` o ``sinr``.

        Es una vista: invalida el heatmap (los píxeles a pintar cambian)
        pero NO marca ``dirty`` ni se persiste (decisión BA). Las
        métricas de interferencia (F11, CC) y SINR (F12, CH) se añaden
        al registro del renderer sin tocar el enum congelado de F7.
        """
        if metric not in HEATMAP_METRICS:
            raise ValueError(
                f"Métrica no soportada: {metric!r} "
                f"(usa {' / '.join(repr(m) for m in HEATMAP_METRICS)})."
            )
        if metric != self.heatmap_metric:
            self.heatmap_metric = metric
            self.invalidate_heatmap()

    def ap_choices_for_heatmap(self) -> list[str]:
        """Valores del selector de AP en la toolbar (todos + ids)."""
        choices = [HEATMAP_ALL_APS]
        choices += [ap.id for ap in self.project.access_points]
        return choices

    def resolve_ap_for_heatmap(self) -> AccessPoint | None:
        """AP seleccionado o el primero del proyecto (comportamiento Fase 3/4)."""
        ap = self.selected_ap()
        if ap is None and self.project.access_points:
            return self.project.access_points[0]
        return ap

    def resolve_aps_for_heatmap(self) -> list[AccessPoint]:
        """APs a evaluar en el heatmap actual.

        - ``HEATMAP_ALL_APS``: todos los APs del proyecto (orden estable).
        - id concreto: solo ese AP (F4 / vista individual).
        """
        aps = list(self.project.access_points)
        if self.heatmap_ap_id == HEATMAP_ALL_APS:
            return aps
        for ap in aps:
            if ap.id == self.heatmap_ap_id:
                return [ap]
        # AP del selector ya no existe → todos (o el primero si solo queda)
        return aps

    # ------------------------------------------------------------------
    # Interferencia espectral (Fase 11: contexto y anotación)
    # ------------------------------------------------------------------

    def _interference_context_aps(
        self, ap: AccessPoint, band_id: str | None = None
    ) -> list[AccessPoint]:
        """APs que pueden interferir con ``ap`` (F11, decisión CB).

        Solo APs distintos, **con canal configurado** y en la **misma
        banda resuelta**: jamás hay interacción entre bandas. Un AP con
        banda irreferenciable se omite aquí (no debe romper la corrida
        del AP deseado; su propia simulación seguirá validándolo).
        """
        band_id = band_id or self.band_id
        try:
            target_band = self.resolve_band_for_ap(ap, band_id)
        except KeyError:
            return []
        context: list[AccessPoint] = []
        for other in self.project.access_points:
            if other.id == ap.id or other.channel is None:
                continue
            try:
                other_band = self.resolve_band_for_ap(other, band_id)
            except KeyError:
                continue
            if other_band.id == target_band.id:
                context.append(other)
        return context

    def _spectral_emissions(
        self, aps: Iterable[AccessPoint], band_id: str | None = None
    ) -> dict:
        """``{ap_id: SpectralEmission}`` solo para APs con canal (CB)."""
        band_id = band_id or self.band_id
        emissions: dict = {}
        for ap in aps:
            if ap.channel is None:
                continue
            emission = emission_for_ap(
                ap, self.resolve_band_for_ap(ap, band_id)
            )
            if emission is not None:
                emissions[ap.id] = emission
        return emissions

    def _ap_evaluations(self, ap_id: str) -> list:
        """Evaluaciones anotadas disponibles para ``ap_id`` (patrón F11).

        Prioriza la última simulación puntual si es de ese AP; si no,
        las evaluaciones de ese AP en el heatmap combinado. Vacío si
        aún no hay corrida que lo incluya. Sin importar la métrica
        visible: los datos del panel no dependen de la vista (CC).
        """
        if (
            self.last_simulation is not None
            and self.last_simulation.evaluations
            and self.last_simulation.evaluations[0].access_point_id == ap_id
        ):
            return list(self.last_simulation.evaluations)
        if self.last_heatmap is not None:
            return [
                e
                for e in self.last_heatmap.evaluations
                if e.access_point_id == ap_id
            ]
        return []

    def ap_interference_lines(self, ap_id: str) -> list[str]:
        """Líneas de interferencia del AP para el panel (F11, decisión CC).

        Solo datos reales del modelo (sin números inventados):

        - AP sin canal ⇒ fuera del modelo espectral (decisión CB).
        - Sin otros APs con canal en la banda ⇒ 0 interferentes
          (es una propiedad de la configuración, no de una corrida).
        - Con candidatos pero sin corrida que lo anote ⇒ «sin datos».
        """
        ap = next(
            (a for a in self.project.access_points if a.id == ap_id), None
        )
        if ap is None:
            return []
        if ap.channel is None:
            return ["Interferencia: — (AP sin canal)"]
        if not self._interference_context_aps(ap, self.band_id):
            return ["Interferencia: 0 APs (sin espectro compartido)"]
        evaluations = self._ap_evaluations(ap_id)
        summary = interference_summary(evaluations)
        if summary is None or summary.evaluated_points == 0:
            return ["Interferencia: — (sin datos de corrida)"]
        lines = ["Interferencia:", f"APs interferentes (máx): {summary.interferer_count_max}"]
        if summary.interference_max_dbm is None:
            lines.append("Potencia agregada: sin interferentes")
        else:
            lines.append(
                f"Potencia agregada máx: {summary.interference_max_dbm:g} dBm"
            )
            if summary.dominant_interferer_ap_id:
                lines.append(f"Dominante: {summary.dominant_interferer_ap_id}")
        return lines

    def ap_sinr_lines(self, ap_id: str) -> list[str]:
        """Líneas de SINR del AP para el panel (F12, decisión CH).

        Diagnóstico complementario de la interferencia de F11: NO
        sustituye las líneas de RSSI/SNR/interferencia; las complementa
        con la relación señal/(ruido+I). Solo datos reales:

        - AP desconocido ⇒ vacío (patrón de las demás líneas de panel).
        - Sin corrida que lo anote ⇒ «sin datos».
        - Con datos ⇒ mínimo/máximo/promedio y cumplimiento del
          objetivo ``sinr_target_db`` (mismo formato que el bloque
          ``SINR (dB)`` de las estadísticas).
        """
        ap = next(
            (a for a in self.project.access_points if a.id == ap_id), None
        )
        if ap is None:
            return []
        evaluations = self._ap_evaluations(ap_id)
        stats = sinr_stats_block(
            evaluations, self.project.thresholds.sinr_target_db
        )
        if not stats:
            return ["SINR: — (sin datos de corrida)"]
        return [
            "SINR (dB):",
            f"  mínimo: {stats['sinr_min_db']:.2f} dB",
            f"  máximo: {stats['sinr_max_db']:.2f} dB",
            f"  promedio: {stats['sinr_avg_db']:.2f} dB",
            (
                f"  ≥ objetivo {stats['sinr_target_db']:g} dB: "
                f"{100.0 * stats['sinr_ratio']:.1f}% "
                f"({stats['points_meeting_sinr_target']})"
            ),
        ]

    # ------------------------------------------------------------------
    # Optimización de canales (Fase 13: propuesta + aplicación)
    # ------------------------------------------------------------------

    def optimize_channels(
        self,
        band_id: str | None = None,
        requested_candidates=None,
    ):
        """Propuesta de reasignación de canales de la banda (F13, CM).

        Simula los APs de la banda UNA vez (el canal no altera RSSI/SNR,
        decisión BR) y evalúa asignaciones con el pipeline existente
        F4 → F11 → F12 → F5. Es una PROPUESTA: NO muta el proyecto
        (sin dirty y sin invalidar la corrida visible); los canales solo
        cambian vía ``apply_channel_assignment``.

        Solo los APs CON CANAL son optimizables (objetivos); los demás
        APs de la banda entran en la evaluación sin emisión (decisión
        CB), de modo que el score refleja el heatmap combinado real.

        Args:
            band_id: Banda a optimizar (por defecto la activa).
            requested_candidates: Candidatos opcionales por ``ap_id``
                (se filtran contra el validador único F10).

        Returns:
            ``OptimizationResult`` de ``engine.channel_optimization``.

        Raises:
            KeyError: si la banda no existe.
            ValueError: si candidatos u objetivos son inválidos.
        """
        band_id = band_id or self.band_id
        self.project.get_band(band_id)  # valida existencia

        band_aps: list[AccessPoint] = []
        for ap in self.project.access_points:
            try:
                band = self.resolve_band_for_ap(ap, band_id)
            except KeyError:
                continue  # banda del AP irreferenciable: fuera (patrón F11)
            if band.id == band_id:
                band_aps.append(ap)

        if not band_aps:
            return channel_optimization.optimize_channels(
                [], {}, self.project.thresholds, requested_candidates
            )

        points = self.build_coverage_grid().points()
        base_results: dict = {}
        for ap in band_aps:
            base_results[ap.id] = simulate_coverage(
                project=self.project,
                access_point=ap,
                frequency_band=self.resolve_band_for_ap(ap, band_id),
                sample_points=points,
                walls=self.floor.walls,
                openings=self.floor.openings,
                obstacles=self.floor.obstacles,
            )
        targets = [
            OptimizationTarget(
                ap_id=ap.id,
                band=self.resolve_band_for_ap(ap, band_id),
                width_mhz=ap.radio.channel_width_mhz,
                current_channel=ap.channel,
            )
            for ap in band_aps
            if ap.channel is not None
        ]
        return channel_optimization.optimize_channels(
            targets,
            base_results,
            self.project.thresholds,
            requested_candidates,
        )

    @undoable
    def apply_channel_assignment(self, assignment) -> list[str]:
        """Aplica una propuesta F13 canal a canal (paso «Aplicar»).

        Reutiliza ``set_ap_rf_config`` (F10): cada triple (banda, canal,
        ancho) se valida ANTES de tocar el proyecto; solo los APs que
        realmente cambian se reemplazan (dirty + invalidación de
        heatmap, patrón BU). Aplicar es siempre explícito: la sesión
        jamás cambia canales por sí sola.

        Args:
            assignment: ``{ap_id: canal}`` (la propuesta optimizada).

        Returns:
            Lista ordenada de ids a los que se les cambió el canal.

        Raises:
            KeyError: si un id no existe en el proyecto.
            ValueError: si un canal no es válido para la banda del AP.
        """
        applied: list[str] = []
        for ap_id, channel in sorted(assignment.items()):
            ap = next(
                (a for a in self.project.access_points if a.id == ap_id), None
            )
            if ap is None:
                raise KeyError(f"Access Point no encontrado: {ap_id}")
            if channel is None or ap.channel == channel:
                continue  # sin cambio real (patrón BU)
            self.set_ap_rf_config(
                ap_id,
                band_id=ap.band_id or self.band_id,
                channel=channel,
                width_mhz=ap.radio.channel_width_mhz,
            )
            applied.append(ap_id)
        return applied

    def run_heatmap(self, band_id: str | None = None) -> SimulationResult:
        """Simula el CoverageGrid con las paredes reales.

        Fase 5: si el selector es ``HEATMAP_ALL_APS`` y hay N > 1 APs,
        evalúa el **mismo grid** para cada AP con ``simulate_coverage``
        y fusiona con ``combine_results`` (mejor RSSI por punto; no es
        interferencia). Con 0 o 1 AP el comportamiento es el de Fase 4.

        Raises:
            ValueError: si no hay AP o el grid es inválido.
            MaterialAttenuationError: banda sin datos (p. ej. 6 GHz).
        """
        band_id = band_id or self.band_id
        # Valida ANTES de mutar: una banda desconocida no debe dejar la
        # sesión con band_id inválido, y un cambio real de banda es
        # configuración persistible ⇒ dirty (decisión AN, F6.1).
        self.project.get_band(band_id)
        if band_id != self.band_id:
            self.band_id = band_id
            self.mark_dirty()
        self.last_heatmap_error = None

        aps = self.resolve_aps_for_heatmap()
        if not aps:
            raise ValueError("Coloca al menos un Access Point para el heatmap.")

        grid = self.build_coverage_grid()
        points = grid.points()

        results: list[SimulationResult] = []
        for ap in aps:
            # Fase 10: cada AP se simula en su banda configurada (o en la
            # activa si no la tiene). Con APs de banda mixta,
            # ``combine_results`` rechaza combinar (contrato F5 intacto).
            results.append(
                simulate_coverage(
                    project=self.project,
                    access_point=ap,
                    frequency_band=self.resolve_band_for_ap(ap, band_id),
                    sample_points=points,
                    walls=self.floor.walls,
                    openings=self.floor.openings,
                    obstacles=self.floor.obstacles,
                )
            )

        # Fase 11: contexto espectral. Con selector individual y AP con
        # canal (decisión CB) se simulan los demás APs con canal de la
        # misma banda; se usan únicamente para ANOTAR el AP seleccionado
        # (la vista sigue siendo su heatmap). La métrica visible NO lo
        # condiciona (así el panel y la métrica «interference» siempre
        # tienen datos reales cuando los canales están configurados).
        # Proyectos sin canales no sufren este coste (decisión CE).
        context: list[AccessPoint] = []
        if len(aps) == 1 and aps[0].channel is not None:
            context = self._interference_context_aps(aps[0], band_id)
            for other in context:
                results.append(
                    simulate_coverage(
                        project=self.project,
                        access_point=other,
                        frequency_band=self.resolve_band_for_ap(other, band_id),
                        sample_points=points,
                        walls=self.floor.walls,
                        openings=self.floor.openings,
                        obstacles=self.floor.obstacles,
                    )
                )

        # Fase 11: anota interferencia en cada evaluación (reutiliza
        # los P_rx ya calculados; decide BX). Sin resultados o con un
        # solo AP no hay contexto posible ⇒ se omite.
        # Fase 12: después de la interferencia (F11) se anota el SINR
        # (decisión CF) y ANTES de combinar (F5), de modo que la
        # evaluación ganadora por RSSI transporta su propio SINR. Con
        # un solo resultado no se anota aquí: evaluate_link ya entregó
        # SINR = SNR exactamente (decisión CG).
        if len(results) >= 2:
            emissions = self._spectral_emissions(
                list(aps) + context, band_id
            )
            results = annotate_interference(results, emissions)
            results = annotate_sinr(results, self.project.thresholds)

        result = results[0] if len(aps) == 1 else combine_results(results)
        self.last_heatmap = result
        self.heatmap_dirty = False
        return result

    def heatmap_stats_text(self) -> str:
        """Estadísticas del último heatmap (denominador: puntos del grid)."""
        if self.last_heatmap_error:
            return self.last_heatmap_error
        if self.last_heatmap is None:
            return "Sin heatmap todavía."
        from ui.coverage_renderer import stats_text

        band = self.project.get_band(self.last_heatmap.band_id)
        if self.heatmap_ap_id == HEATMAP_ALL_APS:
            n = len(self.project.access_points)
            ap_label = f"Todos los AP ({n})" if n != 1 else "Todos los AP (1)"
        else:
            ap_label = self.heatmap_ap_id
        header = (
            f"AP: {ap_label}\n"
            f"Banda: {band.name}\n"
            f"Resolución: {self.grid_resolution_m:g} m\n"
            f"Estándar: {_standard_label(self.project, band.frequency_mhz)}\n"
        )
        if self.heatmap_metric == HeatmapMetric.SNR.value:
            header += (
                f"Métrica: SNR (dB)\n"
                f"SNR objetivo: {self.project.thresholds.snr_target_db:g} dB\n"
            )
        elif self.heatmap_metric == HEATMAP_METRIC_INTERFERENCE:
            # Fase 11 (decisión CC): la métrica vive fuera del enum
            # congelado de F7, en el registro del renderer.
            header += "Métrica: Interferencia (dBm)\n"
            summary = interference_summary(self.last_heatmap.evaluations)
            if summary is None or summary.evaluated_points == 0:
                header += "Modelo espectral: sin datos en esta corrida\n"
            elif summary.interference_max_dbm is None:
                header += "Modelo espectral: sin interferentes en la malla\n"
            else:
                header += (
                    f"Interferencia agregada máx: {summary.interference_max_dbm:g} dBm\n"
                    f"APs interferentes (máx): {summary.interferer_count_max}\n"
                )
        elif self.heatmap_metric == HEATMAP_METRIC_SINR:
            # Fase 12 (decisión CH): métrica paralela fuera del enum.
            header += (
                f"Métrica: SINR (dB)\n"
                f"SINR objetivo: {self.project.thresholds.sinr_target_db:g} dB\n"
            )
        header += "\n"
        return header + stats_text(self.last_heatmap)

    def client_rssi_lines(self) -> list[str]:
        """RSSI/SOM en posiciones de clientes (si hay heatmap y clientes)."""
        if not self.last_heatmap or not self.project.clients:
            return []
        lines: list[str] = []
        for client in self.project.clients:
            ev = self.last_heatmap.best_at(client.position)
            if ev is None:
                # Buscar por proximidad mínima (redondeo de grid)
                best = None
                best_d = float("inf")
                for e in self.last_heatmap.evaluations:
                    d = e.point.distance_to(client.position)
                    if d < best_d:
                        best_d = d
                        best = e
                ev = best
            if ev is None:
                continue
            diagnostic = rf_diagnostic(
                ev.rx_power_dbm, ev.snr_db, self.project.thresholds
            )
            line = (
                f"{client.id}: AP {ev.access_point_id} | "
                f"{ev.distance_m:.2f} m | "
                f"RSSI {ev.rx_power_dbm:.1f} dBm | "
                f"SOM {ev.som_db:.1f} | "
                f"SNR {ev.snr_db:.1f} dB | {ev.quality.value} | "
                f"{diagnostic}"
            )
            # F12: diagnóstico complementario de SINR (no sustituye a
            # RSSI/SNR/interferencia; solo añade esta relación).
            if ev.sinr_db is not None:
                line += (
                    f" | SINR {ev.sinr_db:.1f} dB "
                    f"({sinr_diagnostic(ev.sinr_db, self.project.thresholds)})"
                )
            lines.append(line)
        return lines

    # ------------------------------------------------------------------
    # Selección / herramienta
    # ------------------------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.wall_drag_start = None
        self.space_drag_start = None
        self.obstacle_drag_start = None
        # Cambiar de herramienta descarta una medición en curso (14-F).
        self.measure_anchor = None
        self.measure_cursor = None
        if tool != Tool.SELECT:
            self.selection = None

    def select(self, kind: SelectionKind | None, entity_id: str | None) -> None:
        if kind is None or entity_id is None:
            self.selection = None
        else:
            self.selection = Selection(kind=kind, entity_id=entity_id)

    def selected_wall(self) -> Wall | None:
        if self.selection and self.selection.kind == SelectionKind.WALL:
            for wall in self.floor.walls:
                if wall.id == self.selection.entity_id:
                    return wall
        return None

    def selected_ap(self) -> AccessPoint | None:
        if self.selection and self.selection.kind == SelectionKind.AP:
            for ap in self.project.access_points:
                if ap.id == self.selection.entity_id:
                    return ap
        return None

    def selected_client(self) -> ClientDevice | None:
        if self.selection and self.selection.kind == SelectionKind.CLIENT:
            for client in self.project.clients:
                if client.id == self.selection.entity_id:
                    return client
        return None

    def selected_space(self) -> Space | None:
        if self.selection and self.selection.kind == SelectionKind.SPACE:
            for space in self.floor.spaces:
                if space.id == self.selection.entity_id:
                    return space
        return None

    def selected_opening(self) -> Opening | None:
        if self.selection and self.selection.kind == SelectionKind.OPENING:
            for opening in self.floor.openings:
                if opening.id == self.selection.entity_id:
                    return opening
        return None

    def selected_obstacle(self) -> Obstacle | None:
        """Obstáculo seleccionado (Fase 9), o None."""
        if self.selection and self.selection.kind == SelectionKind.OBSTACLE:
            for obstacle in self.floor.obstacles:
                if obstacle.id == self.selection.entity_id:
                    return obstacle
        return None

    def find_wall(self, wall_id: str) -> Wall | None:
        """Pared por id (o None). Útil para el panel de propiedades."""
        for wall in self.floor.walls:
            if wall.id == wall_id:
                return wall
        return None

    def openings_for_wall(self, wall_id: str) -> list[Opening]:
        """Openings de una pared en orden canónico ``(start, id)``."""
        from core.wall import group_openings_by_wall

        return list(group_openings_by_wall(self.floor.openings).get(wall_id, ()))

    # ------------------------------------------------------------------
    # Crear entidades
    # ------------------------------------------------------------------

    def _all_ids(self) -> list[str]:
        ids = [w.id for w in self.floor.walls]
        ids += [ap.id for ap in self.project.access_points]
        ids += [c.id for c in self.project.clients]
        ids += [f.id for f in self.project.floors]
        ids += [s.id for s in self.floor.spaces]
        ids += [o.id for o in self.floor.openings]
        ids += [obstacle.id for obstacle in self.floor.obstacles]
        return ids

    @undoable
    def add_wall(self, start: Point2D, end: Point2D) -> Wall:
        """Crea una pared en metros. Validaciones de geometría mínima."""
        if start.distance_to(end) < 1e-6:
            raise ValueError("La pared necesita dos puntos distintos.")
        wall_id = next_entity_id(self._all_ids(), "WALL")
        wall = Wall(
            id=wall_id,
            segment=Segment2D(start, end),
            material=self.project.get_material("drywall"),
        )
        self.floor.walls.append(wall)
        self.select(SelectionKind.WALL, wall_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return wall

    @undoable
    def add_access_point(self, position: Point2D) -> AccessPoint:
        """Crea un AP en metros con la radio por defecto del proyecto."""
        position = self._clamp_to_floor(position)
        ap_id = next_entity_id(self._all_ids(), "AP")
        ap = AccessPoint(id=ap_id, position=position, radio=self.project.radio)
        self.project.access_points.append(ap)
        self.select(SelectionKind.AP, ap_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return ap

    @undoable
    def add_client(self, position: Point2D) -> ClientDevice:
        """Crea un dispositivo cliente en metros."""
        position = self._clamp_to_floor(position)
        client_id = next_entity_id(self._all_ids(), "CLIENT")
        client = ClientDevice(id=client_id, position=position)
        self.project.clients.append(client)
        self.select(SelectionKind.CLIENT, client_id)
        self.mark_dirty()
        return client

    # ------------------------------------------------------------------
    # Espacios (Fase 8): geometría + organización, sin RF (decisión BH)
    # ------------------------------------------------------------------

    @undoable
    def add_space(self, corner_a: Point2D, corner_b: Point2D) -> Space:
        """Crea un espacio (rect alineado a ejes) entre dos esquinas.

        Ambas esquinas se recortan al rectángulo del piso. El tamaño
        mínimo por lado es ``MIN_SPACE_SIZE_M``. No invalida el heatmap:
        los espacios no participan en la propagación (decisión BH).

        Raises:
            ValueError: si el rectángulo resultante es demasiado pequeño.
        """
        width = self.floor_width_m
        height = self.floor_height_m

        def _clamp(point: Point2D) -> tuple[float, float]:
            return (
                min(max(point.x, 0.0), width),
                min(max(point.y, 0.0), height),
            )

        x1, y1 = _clamp(corner_a)
        x2, y2 = _clamp(corner_b)
        rect = Rect(
            x=min(x1, x2),
            y=min(y1, y2),
            width=abs(x2 - x1),
            height=abs(y2 - y1),
        )
        if rect.width < MIN_SPACE_SIZE_M or rect.height < MIN_SPACE_SIZE_M:
            raise ValueError(
                f"Espacio demasiado pequeño: mínimo {MIN_SPACE_SIZE_M:g} m "
                f"por lado (got {rect.width:g} × {rect.height:g} m)."
            )
        space_id = next_entity_id(self._all_ids(), "SPACE")
        number = space_id.rsplit("-", 1)[-1]
        space = Space(id=space_id, name=f"Espacio {number}", rect=rect)
        self.floor.spaces.append(space)
        self.select(SelectionKind.SPACE, space_id)
        self.mark_dirty()
        return space

    @undoable
    def set_space_properties(
        self, space_id: str, name: str, function: str = ""
    ) -> None:
        """Actualiza nombre y función zonal de un espacio (strings)."""
        name = str(name)
        function = str(function)
        if not name.strip():
            raise ValueError("El nombre del espacio no puede estar vacío.")
        if len(name) > 200 or len(function) > 200:
            raise ValueError("Nombre o función demasiado largo (máx. 200).")
        for index, space in enumerate(self.floor.spaces):
            if space.id == space_id:
                self.floor.spaces[index] = replace(
                    space, name=name, function=function
                )
                self.mark_dirty()
                return
        raise KeyError(f"Espacio no encontrado: {space_id}")

    # ------------------------------------------------------------------
    # Aperturas (Fase 8): huecos en paredes (decisión BG: reemplazo)
    # ------------------------------------------------------------------

    @undoable
    def add_opening(
        self, wall_id: str, kind: str, center_offset_m: float | None = None
    ) -> Opening:
        """Crea una apertura centrada (o en ``center_offset_m``) en una pared.

        La longitud por defecto es la del tipo (``DEFAULT_OPENING_LENGTH_M``)
        y se recorta para caber en la pared. Invalida el heatmap (los
        openings sí afectan a la propagación) y marca ``dirty``.

        Raises:
            KeyError: si la pared no existe.
            ValueError: si el tipo no es válido o la pared es demasiado
                corta para cualquier apertura.
        """
        wall = self.find_wall(wall_id)
        if wall is None:
            raise KeyError(f"Pared no encontrada: {wall_id}")
        if kind not in OPENING_KINDS:
            raise ValueError(
                f"Tipo de apertura no soportado: {kind!r} "
                f"(permitidos: {', '.join(OPENING_KINDS)})."
            )
        wall_length = wall.segment.length
        if wall_length < MIN_OPENING_LENGTH_M:
            raise ValueError(
                "La pared es demasiado corta para una apertura "
                f"({wall_length:g} m)."
            )
        length = min(DEFAULT_OPENING_LENGTH_M[kind], wall_length)
        center = wall_length / 2.0 if center_offset_m is None else float(center_offset_m)
        start = min(max(center - length / 2.0, 0.0), wall_length - length)
        end = start + length

        opening_id = next_entity_id(self._all_ids(), "OPEN")
        opening = Opening(
            id=opening_id,
            wall_id=wall_id,
            start_offset_m=start,
            end_offset_m=end,
            kind=kind,
        )
        self.floor.openings.append(opening)
        self.select(SelectionKind.OPENING, opening_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return opening

    @undoable
    def set_opening_offsets(
        self, opening_id: str, start_offset_m: float, end_offset_m: float
    ) -> None:
        """Mueve/redimensiona una apertura por offsets métricos sobre la pared.

        Los offsets se recortan al intervalo de la pared y después se
        exige la longitud mínima: una edición nunca puede producir un
        opening inválido o fuera de la pared.

        Raises:
            KeyError: si la apertura o su pared no existen.
            ValueError: si los valores no son finitos o la longitud
                resultante es menor que ``MIN_OPENING_LENGTH_M``.
        """
        try:
            start = float(str(start_offset_m).replace(",", "."))
            end = float(str(end_offset_m).replace(",", "."))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Offsets inválidos: {exc}") from exc
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError("Los offsets deben ser finitos.")

        opening = None
        for item in self.floor.openings:
            if item.id == opening_id:
                opening = item
                break
        if opening is None:
            raise KeyError(f"Apertura no encontrada: {opening_id}")
        wall = self.find_wall(opening.wall_id)
        if wall is None:
            raise KeyError(f"Pared no encontrada: {opening.wall_id}")

        wall_length = wall.segment.length
        start = min(max(start, 0.0), wall_length)
        end = min(max(end, 0.0), wall_length)
        if end - start < MIN_OPENING_LENGTH_M:
            raise ValueError(
                f"La apertura debe medir ≥ {MIN_OPENING_LENGTH_M:g} m "
                f"(pared de {wall_length:g} m; got {end - start:g} m)."
            )
        for index, item in enumerate(self.floor.openings):
            if item.id == opening_id:
                self.floor.openings[index] = replace(
                    item, start_offset_m=start, end_offset_m=end
                )
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Apertura no encontrada: {opening_id}")

    @undoable
    def set_opening_kind(self, opening_id: str, kind: str) -> None:
        """Cambia el tipo visual (door/window/pass_through).

        El tipo NO altera la pérdida (decisión BG): marca ``dirty`` pero
        no invalida el heatmap.
        """
        if kind not in OPENING_KINDS:
            raise ValueError(
                f"Tipo de apertura no soportado: {kind!r} "
                f"(permitidos: {', '.join(OPENING_KINDS)})."
            )
        for index, item in enumerate(self.floor.openings):
            if item.id == opening_id:
                self.floor.openings[index] = replace(item, kind=kind)
                self.mark_dirty()
                return
        raise KeyError(f"Apertura no encontrada: {opening_id}")

    # ------------------------------------------------------------------
    # Mobiliario / obstáculos (Fase 9): SÍ afecta a la RF (decisión BL+)
    # ------------------------------------------------------------------

    @undoable
    def add_obstacle(
        self, corner_a: Point2D, corner_b: Point2D, name: str = ""
    ) -> Obstacle:
        """Crea un obstáculo (footprint rect alineado a ejes) entre dos esquinas.

        Ambas esquinas se recortan al rectángulo del piso. El tamaño
        mínimo por lado es ``MIN_OBSTACLE_SIZE_M`` (0.1 m). Material por
        defecto del catálogo (``DEFAULT_OBSTACLE_MATERIAL_ID``).

        Invalida el heatmap y marca ``dirty``: a diferencia de un
        espacio, un obstáculo atenúa la señal (decisión BL/BP).

        Raises:
            ValueError: si el footprint resultante es demasiado pequeño.
        """
        width = self.floor_width_m
        height = self.floor_height_m

        def _clamp(point: Point2D) -> tuple[float, float]:
            return (
                min(max(point.x, 0.0), width),
                min(max(point.y, 0.0), height),
            )

        x1, y1 = _clamp(corner_a)
        x2, y2 = _clamp(corner_b)
        rect = Rect(
            x=min(x1, x2),
            y=min(y1, y2),
            width=abs(x2 - x1),
            height=abs(y2 - y1),
        )
        if rect.width < MIN_OBSTACLE_SIZE_M or rect.height < MIN_OBSTACLE_SIZE_M:
            raise ValueError(
                f"Objeto demasiado pequeño: mínimo {MIN_OBSTACLE_SIZE_M:g} m "
                f"por lado (got {rect.width:g} × {rect.height:g} m)."
            )
        obstacle_id = next_entity_id(self._all_ids(), "OBST")
        number = obstacle_id.rsplit("-", 1)[-1]
        obstacle = Obstacle(
            id=obstacle_id,
            name=name or f"Objeto {number}",
            rect=rect,
            material=self.project.get_material(DEFAULT_OBSTACLE_MATERIAL_ID),
        )
        self.floor.obstacles.append(obstacle)
        self.select(SelectionKind.OBSTACLE, obstacle_id)
        self.invalidate_heatmap()
        self.mark_dirty()
        return obstacle

    @undoable
    def set_obstacle_properties(
        self,
        obstacle_id: str,
        name: str,
        kind: str = "furniture",
        material_id: str | None = None,
        attenuation_override_db: dict[str, float] | None = None,
    ) -> None:
        """Actualiza nombre/tipo/material/override de un obstáculo.

        El material y el override afectan a la propagación ⇒ se
        invalida el heatmap (decisión BP). El ``replace`` vuelve a pasar
        por ``Obstacle.__post_init__`` (decisión BL): tipo, rango de
        override y finitud se revalidan aquí.

        Raises:
            KeyError: si el obstáculo no existe o el material no.
            ValueError: si nombre/tipo/override no son válidos.
        """
        name = str(name)
        if not name.strip():
            raise ValueError("El nombre del objeto no puede estar vacío.")
        if len(name) > 200:
            raise ValueError("Nombre demasiado largo (máx. 200).")
        if kind not in OBSTACLE_KINDS:
            raise ValueError(
                f"Tipo de objeto no soportado: {kind!r} "
                f"(permitidos: {', '.join(OBSTACLE_KINDS)})."
            )
        for index, obstacle in enumerate(self.floor.obstacles):
            if obstacle.id == obstacle_id:
                material = (
                    obstacle.material
                    if material_id is None
                    else self.project.get_material(material_id)
                )
                self.floor.obstacles[index] = replace(
                    obstacle,
                    name=name,
                    kind=kind,
                    material=material,
                    attenuation_override_db=dict(attenuation_override_db or {}),
                )
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Objeto no encontrado: {obstacle_id}")

    @undoable
    def move_obstacle(self, obstacle_id: str, min_corner: Point2D) -> None:
        """Mueve el footprint (esquina inferior izquierda) dentro del piso.

        El tamaño no cambia: la esquina se recorta para que el rect
        completo quepa en el plano (decisión BP). Invalida el heatmap.
        """
        for index, obstacle in enumerate(self.floor.obstacles):
            if obstacle.id == obstacle_id:
                x = min(
                    max(min_corner.x, 0.0),
                    max(self.floor_width_m - obstacle.rect.width, 0.0),
                )
                y = min(
                    max(min_corner.y, 0.0),
                    max(self.floor_height_m - obstacle.rect.height, 0.0),
                )
                self.floor.obstacles[index] = replace(
                    obstacle,
                    rect=Rect(
                        x=x,
                        y=y,
                        width=obstacle.rect.width,
                        height=obstacle.rect.height,
                    ),
                )
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Objeto no encontrado: {obstacle_id}")

    def _clamp_to_floor(self, position: Point2D) -> Point2D:
        """Mantiene el punto dentro del rectángulo del piso."""
        x = min(max(position.x, 0.0), self.floor_width_m)
        y = min(max(position.y, 0.0), self.floor_height_m)
        return Point2D(x, y)

    # ------------------------------------------------------------------
    # Mover / editar
    # ------------------------------------------------------------------

    @undoable
    def move_ap(self, ap_id: str, position: Point2D) -> None:
        """Actualiza la posición del AP en METROS (nunca píxeles)."""
        position = self._clamp_to_floor(position)
        for index, ap in enumerate(self.project.access_points):
            if ap.id == ap_id:
                self.project.access_points[index] = replace(ap, position=position)
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Access Point no encontrado: {ap_id}")

    @undoable
    def move_client(self, client_id: str, position: Point2D) -> None:
        """Actualiza la posición del cliente en METROS."""
        position = self._clamp_to_floor(position)
        for index, client in enumerate(self.project.clients):
            if client.id == client_id:
                self.project.clients[index] = replace(client, position=position)
                self.mark_dirty()
                return
        raise KeyError(f"Cliente no encontrado: {client_id}")

    @undoable
    def set_wall_material(self, wall_id: str, material_id: str) -> None:
        """Cambia el material de una pared (catálogo del Project)."""
        material: Material = self.project.get_material(material_id)
        for index, wall in enumerate(self.floor.walls):
            if wall.id == wall_id:
                self.floor.walls[index] = replace(wall, material=material)
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Pared no encontrada: {wall_id}")

    @undoable
    def set_wall_thickness(self, wall_id: str, thickness_m: float) -> None:
        """Cambia el espesor de una pared. Debe ser > 0."""
        if thickness_m <= 0:
            raise ValueError(f"Espesor debe ser > 0 m (got {thickness_m}).")
        if thickness_m > 10:
            raise ValueError(
                f"Espesor no razonable: {thickness_m} m (máximo 10 m)."
            )
        for index, wall in enumerate(self.floor.walls):
            if wall.id == wall_id:
                self.floor.walls[index] = replace(wall, thickness_m=float(thickness_m))
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Pared no encontrada: {wall_id}")

    # ------------------------------------------------------------------
    # Fase 14-D: edición de geometría (extremos, traslaciones, rects)
    # ------------------------------------------------------------------

    @staticmethod
    def _finite_point(point: Point2D) -> tuple[float, float]:
        x, y = float(point.x), float(point.y)
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("Coordenadas no finitas.")
        return x, y

    @undoable
    def set_wall_endpoints(self, wall_id: str, start: Point2D, end: Point2D) -> None:
        """Mueve/redimensiona una pared cambiando sus dos extremos.

        Protección atómica de openings (Fase 14-D): si algún hueco de la
        pared se quedaría fuera de la nueva longitud, se RECHAZA la
        operación completa sin modificar nada (la geometría anterior
        sigue siendo válida).

        Raises:
            KeyError: si la pared no existe.
            ValueError: si los puntos no son finitos, coinciden o algún
                opening no cabría en la longitud nueva.
        """
        wall = self.find_wall(wall_id)
        if wall is None:
            raise KeyError(f"Pared no encontrada: {wall_id}")
        sx, sy = self._finite_point(start)
        ex, ey = self._finite_point(end)
        start_pt, end_pt = Point2D(sx, sy), Point2D(ex, ey)
        new_length = start_pt.distance_to(end_pt)
        if new_length < 1e-6:
            raise ValueError("La pared necesita dos puntos distintos.")
        overflowing = [
            item.id
            for item in self.openings_for_wall(wall_id)
            if item.end_offset_m > new_length + 1e-9
        ]
        if overflowing:
            raise ValueError(
                f"La pared tiene {len(overflowing)} hueco(s) que no caben en "
                f"la longitud nueva ({new_length:g} m): "
                f"{', '.join(overflowing)}. "
                "Acorta o elimina los huecos antes de encoger la pared."
            )
        for index, item in enumerate(self.floor.walls):
            if item.id == wall_id:
                self.floor.walls[index] = replace(
                    item, segment=Segment2D(start_pt, end_pt)
                )
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Pared no encontrada: {wall_id}")

    @undoable
    def move_wall(self, wall_id: str, delta: Point2D) -> None:
        """Traslada una pared entera; los offsets de sus openings se mantienen.

        Raises:
            KeyError: si la pared no existe.
            ValueError: si el delta no es finito (o deja la pared degenerada).
        """
        wall = self.find_wall(wall_id)
        if wall is None:
            raise KeyError(f"Pared no encontrada: {wall_id}")
        dx, dy = self._finite_point(delta)
        self.set_wall_endpoints(
            wall_id,
            Point2D(wall.segment.start.x + dx, wall.segment.start.y + dy),
            Point2D(wall.segment.end.x + dx, wall.segment.end.y + dy),
        )

    @staticmethod
    def _finite_rect(rect: Rect) -> None:
        values = (rect.x, rect.y, rect.width, rect.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Rect con valores no finitos.")

    def _clamped_rect(self, rect: Rect, min_size_m: float, what: str) -> Rect:
        """Recorta ``rect`` al piso y exige el tamaño mínimo por lado."""
        x1 = min(max(rect.x, 0.0), self.floor_width_m)
        y1 = min(max(rect.y, 0.0), self.floor_height_m)
        x2 = min(max(rect.x + rect.width, 0.0), self.floor_width_m)
        y2 = min(max(rect.y + rect.height, 0.0), self.floor_height_m)
        width, height = x2 - x1, y2 - y1
        if width < min_size_m or height < min_size_m:
            raise ValueError(
                f"El {what} debe medir ≥ {min_size_m:g} m por lado "
                f"(recortado al piso: {width:g} × {height:g} m)."
            )
        return Rect(x=x1, y=y1, width=width, height=height)

    @undoable
    def set_space_rect(self, space_id: str, rect: Rect) -> None:
        """Mueve/redimensiona un espacio (rect recortado al piso).

        Los espacios no participan en la propagación (decisión BH): no se
        invalida el heatmap, solo se marca ``dirty``.

        Raises:
            KeyError: si el espacio no existe.
            ValueError: si el rect no es finito o queda demasiado pequeño.
        """
        self._finite_rect(rect)
        for index, space in enumerate(self.floor.spaces):
            if space.id == space_id:
                clamped = self._clamped_rect(
                    rect, MIN_SPACE_SIZE_M, "espacio"
                )
                self.floor.spaces[index] = replace(space, rect=clamped)
                self.mark_dirty()
                return
        raise KeyError(f"Espacio no encontrado: {space_id}")

    @undoable
    def move_space(self, space_id: str, delta: Point2D) -> None:
        """Traslada un espacio manteniendo su tamaño (recorte al piso).

        Raises:
            KeyError: si el espacio no existe.
            ValueError: si el delta no es finito o el rect choca con el piso.
        """
        space = None
        for item in self.floor.spaces:
            if item.id == space_id:
                space = item
                break
        if space is None:
            raise KeyError(f"Espacio no encontrado: {space_id}")
        dx, dy = self._finite_point(delta)
        # Mantiene el tamaño: la esquina se recorta para que el rect
        # completo quepa en el piso (mismo criterio que move_obstacle).
        x = min(
            max(space.rect.x + dx, 0.0),
            max(self.floor_width_m - space.rect.width, 0.0),
        )
        y = min(
            max(space.rect.y + dy, 0.0),
            max(self.floor_height_m - space.rect.height, 0.0),
        )
        self.set_space_rect(
            space_id,
            Rect(
                x=x,
                y=y,
                width=space.rect.width,
                height=space.rect.height,
            ),
        )

    @undoable
    def set_obstacle_rect(self, obstacle_id: str, rect: Rect) -> None:
        """Mueve/redimensiona el footprint de un obstáculo (recortado al piso).

        La geometría del obstáculo sí atenúa la propagación (Fase 9): se
        invalida el heatmap y se marca ``dirty``.

        Raises:
            KeyError: si el obstáculo no existe.
            ValueError: si el rect no es finito o queda demasiado pequeño.
        """
        self._finite_rect(rect)
        for index, obstacle in enumerate(self.floor.obstacles):
            if obstacle.id == obstacle_id:
                clamped = self._clamped_rect(
                    rect, MIN_OBSTACLE_SIZE_M, "objeto"
                )
                self.floor.obstacles[index] = replace(obstacle, rect=clamped)
                self.invalidate_heatmap()
                self.mark_dirty()
                return
        raise KeyError(f"Objeto no encontrado: {obstacle_id}")

    # ------------------------------------------------------------------
    # Eliminar
    # ------------------------------------------------------------------

    @undoable
    def delete_selection(self) -> bool:
        """Elimina el elemento seleccionado del modelo. True si había uno."""
        if self.selection is None:
            return False
        kind, entity_id = self.selection.kind, self.selection.entity_id

        if kind == SelectionKind.WALL:
            for index, wall in enumerate(self.floor.walls):
                if wall.id == entity_id:
                    del self.floor.walls[index]
                    # Fase 8: al borrar la pared, sus openings se caen con ella
                    # (nada puede referenciar una pared inexistente).
                    remaining = [
                        op for op in self.floor.openings if op.wall_id != entity_id
                    ]
                    if len(remaining) != len(self.floor.openings):
                        self.floor.openings[:] = remaining
                    self.selection = None
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.AP:
            for index, ap in enumerate(self.project.access_points):
                if ap.id == entity_id:
                    del self.project.access_points[index]
                    self.selection = None
                    # Si el heatmap apuntaba a ese AP, volver a combinado.
                    if self.heatmap_ap_id == entity_id:
                        self.heatmap_ap_id = HEATMAP_ALL_APS
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.CLIENT:
            for index, client in enumerate(self.project.clients):
                if client.id == entity_id:
                    del self.project.clients[index]
                    self.selection = None
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.SPACE:
            # Los espacios no son RF: dirty sí, heatmap no (decisión BH).
            for index, space in enumerate(self.floor.spaces):
                if space.id == entity_id:
                    del self.floor.spaces[index]
                    self.selection = None
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.OPENING:
            for index, opening in enumerate(self.floor.openings):
                if opening.id == entity_id:
                    del self.floor.openings[index]
                    self.selection = None
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        elif kind == SelectionKind.OBSTACLE:
            # Los obstáculos SÍ son RF (Fase 9): dirty + invalidar.
            for index, obstacle in enumerate(self.floor.obstacles):
                if obstacle.id == entity_id:
                    del self.floor.obstacles[index]
                    self.selection = None
                    self.invalidate_heatmap()
                    self.mark_dirty()
                    return True
        self.selection = None
        return False

    # ------------------------------------------------------------------
    # Simulación (invoca engine; sin fórmulas aquí)
    # ------------------------------------------------------------------

    def sample_points_for_simulation(self) -> list[Point2D]:
        """Puntos de muestreo: clientes si existen, si no una malla 3×3."""
        if self.project.clients:
            return [c.position for c in self.project.clients]
        w, h = self.floor_width_m, self.floor_height_m
        points: list[Point2D] = []
        for fx in (0.2, 0.5, 0.8):
            for fy in (0.2, 0.5, 0.8):
                points.append(Point2D(w * fx, h * fy))
        return points

    def run_simulation(self, band_id: str | None = None) -> SimulationResult:
        """Invoca simulate_coverage con las paredes reales del piso.

        La UI solo muestra un resumen de texto (sin heatmap en Fase 3).

        Raises:
            ValueError: si no hay AP.
            MaterialAttenuationError: banda sin datos (p. ej. 6 GHz).
        """
        band_id = band_id or self.band_id
        # Misma regla que run_heatmap: validar antes de mutar + dirty
        # si la banda persistible cambia (decisión AN, F6.1).
        self.project.get_band(band_id)
        if band_id != self.band_id:
            self.band_id = band_id
            self.mark_dirty()
        self.last_simulation_error = None

        ap = self.selected_ap()
        if ap is None and self.project.access_points:
            ap = self.project.access_points[0]
        if ap is None:
            raise ValueError("Coloca al menos un Access Point para simular.")

        points = self.sample_points_for_simulation()
        result = simulate_coverage(
            project=self.project,
            access_point=ap,
            # Fase 10: banda configurada del AP o la activa (decisión BS).
            frequency_band=self.resolve_band_for_ap(ap, band_id),
            sample_points=points,
            walls=self.floor.walls,
            openings=self.floor.openings,
            obstacles=self.floor.obstacles,
        )
        # Fase 11: anota la interferencia del AP deseado en sus puntos.
        # Solo si tiene canal (decisión CB); con otros APs con canal en
        # la banda se simulan esos (reutiliza los P_rx; sin fórmulas
        # nuevas) y se anota antes de guardar el resultado (decisión BX).
        if ap.channel is not None:
            context = self._interference_context_aps(ap, band_id)
            if context:
                results = [result]
                for other in context:
                    results.append(
                        simulate_coverage(
                            project=self.project,
                            access_point=other,
                            frequency_band=self.resolve_band_for_ap(other, band_id),
                            sample_points=points,
                            walls=self.floor.walls,
                            openings=self.floor.openings,
                            obstacles=self.floor.obstacles,
                        )
                    )
                emissions = self._spectral_emissions([ap] + context, band_id)
                results = annotate_interference(results, emissions)
                # F12: SINR con la interferencia ya anotada (decisión CF);
                # nos quedamos con el AP deseado (results[0]).
                result = annotate_sinr(results, self.project.thresholds)[0]
        self.last_simulation = result
        return result

    def simulation_summary_text(self) -> str:
        """Resumen de texto del último resultado (o mensaje de error)."""
        if self.last_simulation_error:
            return self.last_simulation_error
        result = self.last_simulation
        if result is None:
            return "Sin simulación todavía."

        evaluations = result.evaluations
        if not evaluations:
            return "Sin puntos simulados."

        rx_values = [e.rx_power_dbm for e in evaluations]
        snr_values = [e.snr_db for e in evaluations]
        sinr_values = [e.sinr_db for e in evaluations if e.sinr_db is not None]
        ap_id = evaluations[0].access_point_id
        band = self.project.get_band(result.band_id)
        wall_count = len(self.floor.walls)
        text = (
            f"AP: {ap_id}\n"
            f"Banda: {band.name}\n"
            f"Paredes: {wall_count}\n"
            f"Objetos: {len(self.floor.obstacles)}\n"
            f"Puntos simulados: {len(evaluations)}\n"
            f"RSSI mínimo: {min(rx_values):.2f} dBm\n"
            f"RSSI máximo: {max(rx_values):.2f} dBm\n"
            f"SNR mínimo: {min(snr_values):.2f} dB\n"
            f"SNR máximo: {max(snr_values):.2f} dB"
        )
        # Fase 12: capa paralela de SINR (solo si la corrida la anotó).
        if sinr_values:
            text += (
                f"\nSINR mínimo: {min(sinr_values):.2f} dB"
                f"\nSINR máximo: {max(sinr_values):.2f} dB"
            )
        return text
