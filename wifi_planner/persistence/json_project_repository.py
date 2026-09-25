"""Repositorio JSON de proyectos: Project ↔ JSON, con validación estricta.

Formato (``schema_version = 1``)::

    {
      "schema_version": 1,
      "project": {
        "name": "...",
        "units": "m",
        "bands": [...],
        "materials": [...],
        "radio": {...},
        "thresholds": {...},
        "floors": [{"id", "name", "level", "width_m", "height_m",
                    "elevation_m", "metadata", "walls": [...],
                    "spaces": [...], "openings": [...],
                    "obstacles": [...]}],
        "access_points": [...],
        "clients": [...],
        "metadata": {...}
      },
      "editor": {"band_id": "band_2_4", "grid_resolution_m": 0.5}
    }

Decisiones de formato (docs/decisions.md, Fase 6 + 7 + 8):

- Coordenadas SIEMPRE en metros (``x_m`` / ``y_m``); los píxeles no
  existen aquí (la conversión es responsabilidad del ``Viewport``).
- Las paredes referencian el catálogo de materiales por ``material_id``
  (una sola tabla: ``project.materials``).
- No se persisten resultados de simulación, heatmaps ni estado visual:
  se regeneran al abrir.
- ``schema_version`` incompatible => ``ProjectFormatError`` controlado
  (nunca carga parcial ni sobrescribe el proyecto en memoria).
- Fase 7 (misma versión 1, claves **opcionales**): ``radio`` puede
  traer ``noise_floor_dbm``, ``channel_width_mhz`` y ``wifi_standard``;
  ``thresholds`` puede traer ``snr_target_db``. Si faltan (archivos F6)
  se aplican los defaults centralizados de ``core/`` (decisión AZ):
  ningún proyecto F6 deja de abrirse.
- Fase 8 (misma versión 1, decisiones BE/BJ): ``floors[]`` gana las
  claves **opcionales** ``spaces`` y ``openings`` (ausentes ⇒ listas
  vacías: archivos F6/F7 abren sin migración). Los openings exigen
  ``wall_id`` existente en el mismo piso y offsets dentro de la pared.
  ``Opening.blocks_signal`` no existía en el formato: el hueco siempre
  modifica su pared (la semántica es del cruce, no de una bandera).
- Fase 9 (misma versión 1, decisiones BL/BO): ``floors[]`` gana la
  clave **opcional** ``obstacles`` (ausentes ⇒ lista vacía: archivos
  F1–F8 abren sin migración). Cada obstáculo lleva ``rect`` (footprint
  en metros), ``material_id`` (obligatorio y existente en el catálogo),
  ``kind`` y ``attenuation_override_db`` opcional por banda. Se escribe
  siempre al guardar, como spaces/openings.
- Fase 10 (misma versión 1, decisiones BS/BV): cada AP gana la clave
  **opcional** ``band_id`` (ausente ⇒ ``None``: el AP usa la banda
  activa; archivos F6–F9 abren sin migración) junto al ``channel``
  ya existente, que ahora sí se configura. Invariante al LEER:
  ``channel`` explícito exige ``band_id`` y el canal debe pertenecer
  al catálogo de esa banda (``core.channel``); ``band_id`` debe existir
  en ``project.bands``. El ancho × banda sigue validándose al simular
  (contrato F7 intacto). La frecuencia central del canal NUNCA se
  persiste: se deriva del catálogo (decisión BR).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.access_point import AccessPoint
from core.band import FrequencyBand
from core.channel import channel_for_band
from core.client import ClientDevice
from core.geometry import Point2D, Rect, Segment2D
from core.material import Material
from core.obstacle import (
    MAX_OBSTACLE_ATTENUATION_DB,
    MAX_OBSTACLE_SIZE_M,
    OBSTACLE_KINDS,
    Obstacle,
)
from core.project import (
    SINR_TARGET_MAX_DB,
    SINR_TARGET_MIN_DB,
    SNR_TARGET_MAX_DB,
    SNR_TARGET_MIN_DB,
    CoverageThresholds,
    Project,
)
from core.radio import (
    CHANNEL_WIDTHS_MHZ,
    NOISE_FLOOR_MAX_DBM,
    NOISE_FLOOR_MIN_DBM,
    WIFI_STANDARDS,
    RadioConfiguration,
)
from core.space import Floor, Space
from core.wall import (
    MAX_OPENING_ATTENUATION_DB,
    MAX_OPENING_LENGTH_M,
    MIN_OPENING_LENGTH_M,
    OPENING_KINDS,
    Opening,
    Wall,
)

# Versión del formato. Un incremento implica que hay que migrar/validar.
SCHEMA_VERSION = 1

# Resolución de grid por defecto (coincide con EditorSession).
DEFAULT_GRID_RESOLUTION_M = 0.5

# Límites de seguridad: el JSON es entrada no confiable.
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_NAME_LEN = 200
MAX_ID_LEN = 64
MAX_COORD_M = 100_000.0
MAX_DIMENSION_M = 10_000.0
MAX_THICKNESS_M = 10.0
MAX_RESOLUTION_M = 1_000.0
MAX_BANDS = 64
MAX_MATERIALS = 512
MAX_FLOORS = 64
MAX_WALLS = 50_000
MAX_APS = 10_000
MAX_CLIENTS = 10_000
MAX_ATTENUATION_DB = 200.0
MAX_METADATA_DEPTH = 10
MAX_METADATA_ITEMS = 10_000
# Fase 8 (decisión BJ): límites de geometría arquitectónica.
MAX_SPACES = 5_000
MAX_OPENINGS = 10_000
MAX_OPENINGS_PER_WALL = 32
# Fase 9 (decisión BO): límites de mobiliario. El techo de obstáculos
# es el mismo que el de espacios (miles de objetos por plano es un
# escenario extremo; el tamaño por lado cota el trabajo geométrico).
MAX_OBSTACLES = 5_000


class ProjectFormatError(Exception):
    """Archivo de proyecto ilegible, inválido o con versión incompatible."""


@dataclass(frozen=True)
class EditorState:
    """Preferencias del editor que SÍ se persisten (configuración).

    No es estado visual (selección, heatmap visible, herramienta): son
    parámetros que afectan a cómo se rehace la simulación al abrir.
    """

    band_id: str = "band_2_4"
    grid_resolution_m: float = DEFAULT_GRID_RESOLUTION_M


# ---------------------------------------------------------------------------
# Validadores primitivos
# ---------------------------------------------------------------------------


def _fail(message: str) -> None:
    raise ProjectFormatError(message)


def _require_dict(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{path}: se espera un objeto JSON.")
    return value


def _require_list(value: Any, path: str, max_items: int) -> list:
    if not isinstance(value, list):
        _fail(f"{path}: se espera una lista JSON.")
    if len(value) > max_items:
        _fail(f"{path}: demasiados elementos ({len(value)} > {max_items}).")
    return value


def _require_str(
    value: Any, path: str, *, max_len: int = MAX_NAME_LEN, allow_empty: bool = True
) -> str:
    if not isinstance(value, str):
        _fail(f"{path}: se espera una cadena de texto.")
    if len(value) > max_len:
        _fail(f"{path}: demasiado largo ({len(value)} > {max_len} caracteres).")
    if not allow_empty and not value.strip():
        _fail(f"{path}: no puede estar vacío.")
    return value


def _require_id(value: Any, path: str) -> str:
    return _require_str(value, path, max_len=MAX_ID_LEN, allow_empty=False)


def _require_number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if value is None:
        _fail(f"{path}: falta el campo obligatorio.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{path}: se espera un número.")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{path}: número no finito ({value!r}).")
    if minimum is not None and number < minimum:
        _fail(f"{path}: debe ser >= {minimum} (got {number}).")
    if maximum is not None and number > maximum:
        _fail(f"{path}: debe ser <= {maximum} (got {number}).")
    return number


def _require_int(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{path}: se espera un entero.")
    if minimum is not None and value < minimum:
        _fail(f"{path}: debe ser >= {minimum} (got {value}).")
    if maximum is not None and value > maximum:
        _fail(f"{path}: debe ser <= {maximum} (got {value}).")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{path}: se espera true/false.")
    return value


def _validate_metadata(value: Any, path: str, depth: int = 0) -> dict:
    """metadata: dict JSON con claves str y valores finitos (recursivo)."""
    if depth > MAX_METADATA_DEPTH:
        _fail(f"{path}: anidación demasiado profunda.")
    if value is None:
        return {}
    data = _require_dict(value, path)
    _walk_metadata(data, path, depth)
    return data


def _walk_metadata(value: Any, path: str, depth: int) -> None:
    if depth > MAX_METADATA_DEPTH:
        _fail(f"{path}: anidación demasiado profunda.")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{path}: número no finito en metadata.")
        return
    if isinstance(value, list):
        if len(value) > MAX_METADATA_ITEMS:
            _fail(f"{path}: lista de metadata demasiado grande.")
        for index, item in enumerate(value):
            _walk_metadata(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_METADATA_ITEMS:
            _fail(f"{path}: objeto de metadata demasiado grande.")
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{path}: las claves de metadata deben ser texto.")
            _walk_metadata(item, f"{path}.{key}", depth + 1)
        return
    _fail(f"{path}: valor de metadata no soportado ({type(value).__name__}).")


def _point_to_dict(point: Point2D) -> dict[str, float]:
    return {"x_m": point.x, "y_m": point.y}


def _point_from_dict(value: Any, path: str) -> Point2D:
    data = _require_dict(value, path)
    x = _require_number(data.get("x_m"), f"{path}.x_m", minimum=-MAX_COORD_M, maximum=MAX_COORD_M)
    y = _require_number(data.get("y_m"), f"{path}.y_m", minimum=-MAX_COORD_M, maximum=MAX_COORD_M)
    return Point2D(x, y)


def _require_unique(ids: list[str], path: str) -> None:
    seen: set[str] = set()
    for entity_id in ids:
        if entity_id in seen:
            _fail(f"{path}: id duplicado {entity_id!r}.")
        seen.add(entity_id)


# ---------------------------------------------------------------------------
# Serialización (Project → dict)
# ---------------------------------------------------------------------------


def _radio_to_dict(radio: RadioConfiguration) -> dict[str, float]:
    return {
        "p_tx_dbm": radio.p_tx_dbm,
        "g_tx_dbi": radio.g_tx_dbi,
        "l_tx_db": radio.l_tx_db,
        "g_rx_dbi": radio.g_rx_dbi,
        "l_rx_db": radio.l_rx_db,
        "sensitivity_dbm": radio.sensitivity_dbm,
        "fade_margin_db": radio.fade_margin_db,
        # Fase 7 (claves opcionales al LEER; siempre se escriben):
        "noise_floor_dbm": radio.noise_floor_dbm,
        "channel_width_mhz": int(radio.channel_width_mhz),
        "wifi_standard": radio.wifi_standard,
    }


def _thresholds_to_dict(thresholds: CoverageThresholds) -> dict[str, float]:
    return {
        "rssi_target_dbm": thresholds.rssi_target_dbm,
        "som_aprobado_min_db": thresholds.som_aprobado_min_db,
        "som_riesgo_min_db": thresholds.som_riesgo_min_db,
        "excellent_min_dbm": thresholds.excellent_min_dbm,
        "good_min_dbm": thresholds.good_min_dbm,
        "regular_min_dbm": thresholds.regular_min_dbm,
        "weak_min_dbm": thresholds.weak_min_dbm,
        # Fase 7 (clave opcional al LEER; siempre se escribe):
        "snr_target_db": thresholds.snr_target_db,
        # Fase 12 (clave opcional al LEER; siempre se escribe):
        # es CONFIGURACIÓN de umbral, no un resultado derivado (CD).
        "sinr_target_db": thresholds.sinr_target_db,
    }


def _wall_to_dict(wall: Wall) -> dict[str, Any]:
    return {
        "id": wall.id,
        "start": _point_to_dict(wall.segment.start),
        "end": _point_to_dict(wall.segment.end),
        "material_id": wall.material.id,
        "thickness_m": wall.thickness_m,
        "blocks_signal": wall.blocks_signal,
    }


def _space_to_dict(space: Space) -> dict[str, Any]:
    return {
        "id": space.id,
        "name": space.name,
        "function": space.function,
        "rect": {
            "x_m": space.rect.x,
            "y_m": space.rect.y,
            "width_m": space.rect.width,
            "height_m": space.rect.height,
        },
        "metadata": dict(space.metadata),
    }


def _opening_to_dict(opening: Opening) -> dict[str, Any]:
    return {
        "id": opening.id,
        "wall_id": opening.wall_id,
        "start_offset_m": opening.start_offset_m,
        "end_offset_m": opening.end_offset_m,
        "kind": opening.kind,
        "attenuation_override_db": dict(opening.attenuation_override_db),
    }


def _obstacle_to_dict(obstacle: Obstacle) -> dict[str, Any]:
    return {
        "id": obstacle.id,
        "name": obstacle.name,
        "kind": obstacle.kind,
        "rect": {
            "x_m": obstacle.rect.x,
            "y_m": obstacle.rect.y,
            "width_m": obstacle.rect.width,
            "height_m": obstacle.rect.height,
        },
        "material_id": obstacle.material.id,
        "blocks_signal": obstacle.blocks_signal,
        "attenuation_override_db": dict(obstacle.attenuation_override_db),
        "metadata": dict(obstacle.metadata),
    }


def _floor_to_dict(floor: Floor) -> dict[str, Any]:
    return {
        "id": floor.id,
        "name": floor.name,
        "level": floor.level,
        "width_m": floor.width_m,
        "height_m": floor.height_m,
        "elevation_m": floor.elevation_m,
        "metadata": dict(floor.metadata),
        "walls": [_wall_to_dict(wall) for wall in floor.walls],
        # Fase 8 (claves opcionales al LEER; siempre se escriben):
        "spaces": [_space_to_dict(space) for space in floor.spaces],
        "openings": [_opening_to_dict(opening) for opening in floor.openings],
        # Fase 9 (mismo patrón; decisión BO):
        "obstacles": [_obstacle_to_dict(o) for o in floor.obstacles],
    }


def _ap_to_dict(ap: AccessPoint) -> dict[str, Any]:
    return {
        "id": ap.id,
        "position": _point_to_dict(ap.position),
        "name": ap.name,
        "enabled": ap.enabled,
        # Fase 10: banda configurada del AP (None = banda activa).
        "band_id": ap.band_id,
        "channel": ap.channel,
        "radio": _radio_to_dict(ap.radio),
        "metadata": dict(ap.metadata),
    }


def _client_to_dict(client: ClientDevice) -> dict[str, Any]:
    return {
        "id": client.id,
        "position": _point_to_dict(client.position),
        "name": client.name,
        "sensitivity_dbm": client.sensitivity_dbm,
        "metadata": dict(client.metadata),
    }


def project_to_dict(project: Project) -> dict[str, Any]:
    """Convierte un ``Project`` en datos JSON-compatibles (determinista)."""
    return {
        "name": project.name,
        "units": project.units,
        "bands": [
            {"id": band.id, "name": band.name, "frequency_mhz": band.frequency_mhz}
            for band in project.bands
        ],
        "materials": [
            {
                "id": material.id,
                "name": material.name,
                "description": material.description,
                "thickness_default_m": material.thickness_default_m,
                "attenuation_db": dict(material.attenuation_db),
            }
            for material in project.materials
        ],
        "radio": _radio_to_dict(project.radio),
        "thresholds": _thresholds_to_dict(project.thresholds),
        "floors": [_floor_to_dict(floor) for floor in project.floors],
        "access_points": [_ap_to_dict(ap) for ap in project.access_points],
        "clients": [_client_to_dict(client) for client in project.clients],
        "metadata": dict(project.metadata),
    }


def document_to_dict(
    project: Project, editor_state: EditorState | None = None
) -> dict[str, Any]:
    """Documento completo: ``schema_version`` + proyecto + estado de editor."""
    state = editor_state or EditorState(band_id=_default_band_id(project))
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project_to_dict(project),
        "editor": {
            "band_id": state.band_id,
            "grid_resolution_m": state.grid_resolution_m,
        },
    }


def _default_band_id(project: Project) -> str:
    """Banda por defecto para un documento sin sección ``editor``."""
    if any(band.id == "band_2_4" for band in project.bands):
        return "band_2_4"
    if project.bands:
        return project.bands[0].id
    return "band_2_4"


# ---------------------------------------------------------------------------
# Deserialización (dict → Project)
# ---------------------------------------------------------------------------


def _radio_from_dict(value: Any, path: str) -> RadioConfiguration:
    data = _require_dict(value, path)
    fields = (
        "p_tx_dbm",
        "g_tx_dbi",
        "l_tx_db",
        "g_rx_dbi",
        "l_rx_db",
        "sensitivity_dbm",
        "fade_margin_db",
    )
    # Límites físicos por campo (solo donde el dominio ya está acotado:
    # la sensibilidad de clientes usa exactamente el mismo rango).
    limits: dict[str, tuple[float | None, float | None]] = {
        "sensitivity_dbm": (-200.0, 0.0),
    }
    kwargs: dict[str, float] = {}
    for field in fields:
        if field not in data:
            _fail(f"{path}.{field}: falta el campo obligatorio.")
        minimum, maximum = limits.get(field, (None, None))
        kwargs[field] = _require_number(
            data[field], f"{path}.{field}", minimum=minimum, maximum=maximum
        )
    if kwargs["fade_margin_db"] < 0:
        _fail(f"{path}.fade_margin_db no puede ser negativo.")

    # Fase 7: campos OPCIONALES (ausentes en archivos F6 => defaults
    # centralizados desde la instancia por defecto, decisión AZ).
    defaults = RadioConfiguration()
    if "noise_floor_dbm" in data:
        kwargs["noise_floor_dbm"] = _require_number(
            data["noise_floor_dbm"],
            f"{path}.noise_floor_dbm",
            minimum=NOISE_FLOOR_MIN_DBM,
            maximum=NOISE_FLOOR_MAX_DBM,
        )
    else:
        kwargs["noise_floor_dbm"] = defaults.noise_floor_dbm

    if "channel_width_mhz" in data:
        width = _require_int(data["channel_width_mhz"], f"{path}.channel_width_mhz")
        if width not in CHANNEL_WIDTHS_MHZ:
            _fail(
                f"{path}.channel_width_mhz: ancho no soportado {width} MHz "
                f"(permitidos: {', '.join(str(w) for w in CHANNEL_WIDTHS_MHZ)})."
            )
        kwargs["channel_width_mhz"] = width
    else:
        kwargs["channel_width_mhz"] = defaults.channel_width_mhz

    if "wifi_standard" in data:
        standard = _require_str(
            data["wifi_standard"], f"{path}.wifi_standard",
            max_len=16, allow_empty=False,
        )
        if standard not in WIFI_STANDARDS:
            _fail(
                f"{path}.wifi_standard: estándar no soportado {standard!r} "
                f"(permitidos: {', '.join(WIFI_STANDARDS)})."
            )
        kwargs["wifi_standard"] = standard
    else:
        kwargs["wifi_standard"] = defaults.wifi_standard

    return RadioConfiguration(**kwargs)


def _thresholds_from_dict(value: Any, path: str) -> CoverageThresholds:
    data = _require_dict(value, path)
    fields = (
        "rssi_target_dbm",
        "som_aprobado_min_db",
        "som_riesgo_min_db",
        "excellent_min_dbm",
        "good_min_dbm",
        "regular_min_dbm",
        "weak_min_dbm",
    )
    kwargs: dict[str, float] = {}
    for field in fields:
        if field not in data:
            _fail(f"{path}.{field}: falta el campo obligatorio.")
        kwargs[field] = _require_number(data[field], f"{path}.{field}")

    # Fase 7: campo OPCIONAL (ausente en archivos F6 => default centralizado).
    if "snr_target_db" in data:
        kwargs["snr_target_db"] = _require_number(
            data["snr_target_db"],
            f"{path}.snr_target_db",
            minimum=SNR_TARGET_MIN_DB,
            maximum=SNR_TARGET_MAX_DB,
        )
    else:
        kwargs["snr_target_db"] = CoverageThresholds().snr_target_db

    # Fase 12: campo OPCIONAL (ausente en archivos F1–F11 => default
    # centralizado, patrón AZ). Los resultados derivados (sinr_db de las
    # evaluaciones) NO se persisten jamás.
    if "sinr_target_db" in data:
        kwargs["sinr_target_db"] = _require_number(
            data["sinr_target_db"],
            f"{path}.sinr_target_db",
            minimum=SINR_TARGET_MIN_DB,
            maximum=SINR_TARGET_MAX_DB,
        )
    else:
        kwargs["sinr_target_db"] = CoverageThresholds().sinr_target_db

    return CoverageThresholds(**kwargs)


def _bands_from_list(value: Any, path: str) -> list[FrequencyBand]:
    items = _require_list(value, path, MAX_BANDS)
    if not items:
        _fail(f"{path}: el proyecto necesita al menos una banda.")
    bands: list[FrequencyBand] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "name", "frequency_mhz"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        frequency = _require_number(
            data["frequency_mhz"], f"{item_path}.frequency_mhz", minimum=1e-6
        )
        bands.append(
            FrequencyBand(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data["name"], f"{item_path}.name"),
                frequency_mhz=frequency,
            )
        )
    _require_unique([band.id for band in bands], path)
    return bands


def _materials_from_list(value: Any, path: str) -> list[Material]:
    items = _require_list(value, path, MAX_MATERIALS)
    materials: list[Material] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "name", "thickness_default_m", "attenuation_db"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        thickness = _require_number(
            data["thickness_default_m"],
            f"{item_path}.thickness_default_m",
            minimum=1e-6,
            maximum=MAX_THICKNESS_M,
        )
        raw_attenuation = _require_dict(
            data["attenuation_db"], f"{item_path}.attenuation_db"
        )
        attenuation: dict[str, float] = {}
        for band_id, raw_value in raw_attenuation.items():
            if not isinstance(band_id, str):
                _fail(f"{item_path}.attenuation_db: las claves deben ser texto.")
            attenuation[band_id] = _require_number(
                raw_value,
                f"{item_path}.attenuation_db.{band_id}",
                minimum=0.0,
                maximum=MAX_ATTENUATION_DB,
            )
        materials.append(
            Material(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data["name"], f"{item_path}.name"),
                description=_require_str(
                    data.get("description", ""), f"{item_path}.description"
                ),
                thickness_default_m=thickness,
                attenuation_db=attenuation,
            )
        )
    _require_unique([material.id for material in materials], path)
    return materials


def _walls_from_list(
    value: Any, path: str, materials_by_id: dict[str, Material]
) -> list[Wall]:
    items = _require_list(value, path, MAX_WALLS)
    walls: list[Wall] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "start", "end", "material_id"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        material_id = _require_id(data["material_id"], f"{item_path}.material_id")
        if material_id not in materials_by_id:
            _fail(f"{item_path}.material_id: material desconocido {material_id!r}.")
        raw_thickness = data.get("thickness_m")
        if raw_thickness is None:
            thickness: float | None = None
        else:
            thickness = _require_number(
                raw_thickness,
                f"{item_path}.thickness_m",
                minimum=1e-6,
                maximum=MAX_THICKNESS_M,
            )
        start = _point_from_dict(data["start"], f"{item_path}.start")
        end = _point_from_dict(data["end"], f"{item_path}.end")
        if start.distance_to(end) < 1e-6:
            _fail(f"{item_path}: la pared necesita dos puntos distintos.")
        walls.append(
            Wall(
                id=_require_id(data["id"], f"{item_path}.id"),
                segment=Segment2D(start, end),
                material=materials_by_id[material_id],
                thickness_m=thickness,
                blocks_signal=_require_bool(
                    data.get("blocks_signal", True), f"{item_path}.blocks_signal"
                ),
            )
        )
    _require_unique([wall.id for wall in walls], path)
    return walls


def _rect_from_dict(value: Any, path: str) -> Rect:
    """Rect de espacio/obstáculo: dimensiones (0, MAX_DIMENSION_M] y coords acotadas."""
    data = _require_dict(value, path)
    x = _require_number(
        data.get("x_m"), f"{path}.x_m", minimum=-MAX_COORD_M, maximum=MAX_COORD_M
    )
    y = _require_number(
        data.get("y_m"), f"{path}.y_m", minimum=-MAX_COORD_M, maximum=MAX_COORD_M
    )
    width = _require_number(
        data.get("width_m"), f"{path}.width_m",
        minimum=1e-6, maximum=MAX_DIMENSION_M,
    )
    height = _require_number(
        data.get("height_m"), f"{path}.height_m",
        minimum=1e-6, maximum=MAX_DIMENSION_M,
    )
    try:
        return Rect(x=x, y=y, width=width, height=height)
    except ValueError as exc:
        _fail(f"{path}: {exc}")


def _spaces_from_list(value: Any, path: str) -> list[Space]:
    items = _require_list(value, path, MAX_SPACES)
    spaces: list[Space] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "rect"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        spaces.append(
            Space(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                function=_require_str(
                    data.get("function", ""), f"{item_path}.function"
                ),
                rect=_rect_from_dict(data["rect"], f"{item_path}.rect"),
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([space.id for space in spaces], path)
    return spaces


def _openings_from_list(
    value: Any, path: str, walls_by_id: dict[str, Wall]
) -> list[Opening]:
    """Openings de un piso: ``wall_id`` existente + offsets dentro de la pared."""
    items = _require_list(value, path, MAX_OPENINGS)
    openings: list[Opening] = []
    per_wall: dict[str, int] = {}
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "wall_id", "start_offset_m", "end_offset_m"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        wall_id = _require_id(data["wall_id"], f"{item_path}.wall_id")
        wall = walls_by_id.get(wall_id)
        if wall is None:
            _fail(f"{item_path}.wall_id: pared desconocida {wall_id!r}.")
        start = _require_number(
            data["start_offset_m"], f"{item_path}.start_offset_m",
            minimum=0.0, maximum=MAX_DIMENSION_M,
        )
        end = _require_number(
            data["end_offset_m"], f"{item_path}.end_offset_m",
            minimum=0.0, maximum=MAX_DIMENSION_M,
        )
        if end - start < MIN_OPENING_LENGTH_M:
            _fail(
                f"{item_path}: la longitud debe ser ≥ {MIN_OPENING_LENGTH_M:g} m "
                f"(got {end - start:g})."
            )
        if end - start > MAX_OPENING_LENGTH_M:
            _fail(
                f"{item_path}: la longitud debe ser ≤ {MAX_OPENING_LENGTH_M:g} m "
                f"(got {end - start:g})."
            )
        wall_length = wall.segment.length
        if end > wall_length + 1e-6:
            _fail(
                f"{item_path}: el hueco excede la pared {wall_id!r} "
                f"({wall_length:g} m; end={end:g} m)."
            )
        kind = _require_str(
            data.get("kind", "door"), f"{item_path}.kind",
            max_len=32, allow_empty=False,
        )
        if kind not in OPENING_KINDS:
            _fail(
                f"{item_path}.kind: tipo no soportado {kind!r} "
                f"(permitidos: {', '.join(OPENING_KINDS)})."
            )
        raw_override = data.get("attenuation_override_db") or {}
        override_data = _require_dict(raw_override, f"{item_path}.attenuation_override_db")
        override: dict[str, float] = {}
        for band_id, raw_loss in override_data.items():
            if not isinstance(band_id, str) or not band_id:
                _fail(
                    f"{item_path}.attenuation_override_db: las claves deben "
                    "ser band ids no vacíos."
                )
            override[band_id] = _require_number(
                raw_loss,
                f"{item_path}.attenuation_override_db.{band_id}",
                minimum=0.0, maximum=MAX_OPENING_ATTENUATION_DB,
            )
        per_wall[wall_id] = per_wall.get(wall_id, 0) + 1
        if per_wall[wall_id] > MAX_OPENINGS_PER_WALL:
            _fail(
                f"{path}: la pared {wall_id!r} tiene más de "
                f"{MAX_OPENINGS_PER_WALL} openings."
            )
        openings.append(
            Opening(
                id=_require_id(data["id"], f"{item_path}.id"),
                wall_id=wall_id,
                start_offset_m=start,
                end_offset_m=end,
                kind=kind,
                attenuation_override_db=override,
            )
        )
    _require_unique([opening.id for opening in openings], path)
    return openings


def _obstacles_from_list(
    value: Any, path: str, materials_by_id: dict[str, Material]
) -> list[Obstacle]:
    """Obstáculos de un piso: ``material_id`` del catálogo + rect válido.

    Fase 9 (decisión BO): entrada no confiable con los mismos niveles
    de protección que spaces/openings — límite de lista, ids únicos,
    strings acotados, números finitos, kind soportado, materiales
    existentes y override en [0, MAX_OBSTACLE_ATTENUATION_DB].
    """
    items = _require_list(value, path, MAX_OBSTACLES)
    obstacles: list[Obstacle] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "rect", "material_id"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        material_id = _require_id(data["material_id"], f"{item_path}.material_id")
        material = materials_by_id.get(material_id)
        if material is None:
            _fail(f"{item_path}.material_id: material desconocido {material_id!r}.")
        rect = _rect_from_dict(data["rect"], f"{item_path}.rect")
        if rect.width > MAX_OBSTACLE_SIZE_M or rect.height > MAX_OBSTACLE_SIZE_M:
            _fail(
                f"{item_path}.rect: el footprint debe medir ≤ "
                f"{MAX_OBSTACLE_SIZE_M:g} m por lado "
                f"(got {rect.width:g} × {rect.height:g})."
            )
        kind = _require_str(
            data.get("kind", "furniture"), f"{item_path}.kind",
            max_len=32, allow_empty=False,
        )
        if kind not in OBSTACLE_KINDS:
            _fail(
                f"{item_path}.kind: tipo no soportado {kind!r} "
                f"(permitidos: {', '.join(OBSTACLE_KINDS)})."
            )
        raw_override = data.get("attenuation_override_db") or {}
        override_data = _require_dict(
            raw_override, f"{item_path}.attenuation_override_db"
        )
        override: dict[str, float] = {}
        for band_id, raw_loss in override_data.items():
            if not isinstance(band_id, str) or not band_id:
                _fail(
                    f"{item_path}.attenuation_override_db: las claves deben "
                    "ser band ids no vacíos."
                )
            override[band_id] = _require_number(
                raw_loss,
                f"{item_path}.attenuation_override_db.{band_id}",
                minimum=0.0, maximum=MAX_OBSTACLE_ATTENUATION_DB,
            )
        obstacles.append(
            Obstacle(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                rect=rect,
                material=material,
                kind=kind,
                attenuation_override_db=override,
                blocks_signal=_require_bool(
                    data.get("blocks_signal", True),
                    f"{item_path}.blocks_signal",
                ),
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([obstacle.id for obstacle in obstacles], path)
    return obstacles


def _floors_from_list(
    value: Any, path: str, materials_by_id: dict[str, Material]
) -> list[Floor]:
    items = _require_list(value, path, MAX_FLOORS)
    if not items:
        # El editor v1 no puede trabajar sin piso; exigirlo aquí mantiene
        # simétrico guardar/cargar (nunca se escribe algo que no se abre).
        _fail(f"{path}: el proyecto necesita al menos un piso.")
    floors: list[Floor] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "width_m", "height_m", "walls"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        width = _require_number(
            data["width_m"],
            f"{item_path}.width_m",
            minimum=1e-6,
            maximum=MAX_DIMENSION_M,
        )
        height = _require_number(
            data["height_m"],
            f"{item_path}.height_m",
            minimum=1e-6,
            maximum=MAX_DIMENSION_M,
        )
        walls = _walls_from_list(
            data["walls"], f"{item_path}.walls", materials_by_id
        )
        walls_by_id = {wall.id: wall for wall in walls}
        # Fase 8 (claves opcionales; ausentes ⇒ listas vacías — decisión BE):
        spaces = _spaces_from_list(data.get("spaces", []), f"{item_path}.spaces")
        openings = _openings_from_list(
            data.get("openings", []), f"{item_path}.openings", walls_by_id
        )
        # Fase 9 (mismo patrón; ausentes ⇒ lista vacía — decisión BO):
        obstacles = _obstacles_from_list(
            data.get("obstacles", []), f"{item_path}.obstacles", materials_by_id
        )
        floors.append(
            Floor(
                id=_require_id(data["id"], f"{item_path}.id"),
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                level=_require_int(data.get("level", 0), f"{item_path}.level"),
                walls=walls,
                spaces=spaces,
                openings=openings,
                obstacles=obstacles,
                elevation_m=_require_number(
                    data.get("elevation_m", 0.0),
                    f"{item_path}.elevation_m",
                    minimum=-10_000.0,
                    maximum=10_000.0,
                ),
                width_m=width,
                height_m=height,
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([floor.id for floor in floors], path)
    return floors


def _aps_from_list(
    value: Any, path: str, bands: list[FrequencyBand]
) -> list[AccessPoint]:
    items = _require_list(value, path, MAX_APS)
    aps: list[AccessPoint] = []
    bands_by_id = {band.id: band for band in bands}
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "position"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        # Fase 10 (decisión BV): banda y canal por AP. Ambas claves son
        # opcionales al leer (archivos F6–F9 sin ellas ⇒ None); la
        # frecuencia central NUNCA viene del archivo: se deriva del
        # catálogo de canales (decisión BR).
        raw_band_id = data.get("band_id")
        band_id: str | None = None
        if raw_band_id is not None:
            band_id = _require_str(raw_band_id, f"{item_path}.band_id", max_len=64)
            if band_id not in bands_by_id:
                _fail(f"{item_path}.band_id: banda desconocida {band_id!r}.")
        raw_channel = data.get("channel")
        channel: int | None = None
        if raw_channel is not None:
            channel = _require_int(raw_channel, f"{item_path}.channel", minimum=0)
            if band_id is None:
                _fail(
                    f"{item_path}.channel: requiere band_id "
                    "(canal por AP sin banda configurada, Fase 10)."
                )
            try:
                channel_for_band(bands_by_id[band_id], channel)
            except ValueError as exc:
                _fail(f"{item_path}.channel: {exc}")
        if "radio" in data:
            radio = _radio_from_dict(data["radio"], f"{item_path}.radio")
        else:
            radio = RadioConfiguration()
        aps.append(
            AccessPoint(
                id=_require_id(data["id"], f"{item_path}.id"),
                position=_point_from_dict(data["position"], f"{item_path}.position"),
                radio=radio,
                band_id=band_id,
                channel=channel,
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                enabled=_require_bool(data.get("enabled", True), f"{item_path}.enabled"),
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([ap.id for ap in aps], path)
    return aps


def _clients_from_list(value: Any, path: str) -> list[ClientDevice]:
    items = _require_list(value, path, MAX_CLIENTS)
    clients: list[ClientDevice] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        data = _require_dict(item, item_path)
        for field in ("id", "position"):
            if field not in data:
                _fail(f"{item_path}.{field}: falta el campo obligatorio.")
        clients.append(
            ClientDevice(
                id=_require_id(data["id"], f"{item_path}.id"),
                position=_point_from_dict(data["position"], f"{item_path}.position"),
                sensitivity_dbm=_require_number(
                    data.get("sensitivity_dbm", -75.0),
                    f"{item_path}.sensitivity_dbm",
                    minimum=-200.0,
                    maximum=0.0,
                ),
                name=_require_str(data.get("name", ""), f"{item_path}.name"),
                metadata=_validate_metadata(
                    data.get("metadata"), f"{item_path}.metadata"
                ),
            )
        )
    _require_unique([client.id for client in clients], path)
    return clients


def project_from_dict(value: Any) -> Project:
    """Valida y reconstruye un ``Project`` desde datos JSON.

    Raises:
        ProjectFormatError: estructura, tipos, límites o referencias
            inválidas (p. ej. material inexistente, id duplicado, NaN).
    """
    data = _require_dict(value, "project")
    for field in (
        "name",
        "units",
        "bands",
        "materials",
        "radio",
        "thresholds",
        "floors",
        "access_points",
        "clients",
    ):
        if field not in data:
            _fail(f"project.{field}: falta el campo obligatorio.")

    units = _require_str(data["units"], "project.units", max_len=16)
    if units != "m":
        _fail(f"project.units: unidad no soportada {units!r} (se espera 'm').")

    name = _require_str(data["name"], "project.name", allow_empty=False)
    bands = _bands_from_list(data["bands"], "project.bands")
    materials = _materials_from_list(data["materials"], "project.materials")
    materials_by_id = {material.id: material for material in materials}
    floors = _floors_from_list(data["floors"], "project.floors", materials_by_id)
    access_points = _aps_from_list(
        data["access_points"], "project.access_points", bands
    )
    clients = _clients_from_list(data["clients"], "project.clients")
    metadata = _validate_metadata(data.get("metadata"), "project.metadata")

    project = Project(
        name=name,
        units=units,
        bands=bands,
        materials=materials,
        radio=_radio_from_dict(data["radio"], "project.radio"),
        thresholds=_thresholds_from_dict(data["thresholds"], "project.thresholds"),
        access_points=access_points,
        clients=clients,
        floors=floors,
        metadata=metadata,
    )
    return project


def _validate_grid_resolution(project: Project, resolution_m: float) -> None:
    """La resolución debe producir un grid usable con el piso del archivo."""
    if not (0.0 < resolution_m <= MAX_RESOLUTION_M):
        _fail(
            "editor.grid_resolution_m: debe estar en (0, "
            f"{MAX_RESOLUTION_M:g}] (got {resolution_m})."
        )
    if not project.floors:
        return
    from engine.coverage_grid import CoverageGrid

    floor = project.floors[0]
    if floor.width_m is None or floor.height_m is None:
        return
    try:
        grid = CoverageGrid(
            width_m=floor.width_m,
            height_m=floor.height_m,
            resolution_m=resolution_m,
        )
    except ValueError as exc:
        _fail(f"editor.grid_resolution_m: {exc}")
    if grid.point_count <= 0:
        _fail("editor.grid_resolution_m: el grid quedaría vacío.")


def document_from_dict(value: Any) -> tuple[Project, EditorState]:
    """Valida el documento completo y devuelve ``(project, editor_state)``.

    Raises:
        ProjectFormatError: versión incompatible, JSON malformado o
            valores inválidos. Nunca devuelve un estado parcial.
    """
    try:
        return _document_from_dict(value)
    except ProjectFormatError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProjectFormatError(f"Valores inválidos en el documento: {exc}") from exc


def _document_from_dict(value: Any) -> tuple[Project, EditorState]:
    """Detecta ``schema_version`` y delega en el lector de esa versión.

    Punto único de extensión para formatos futuros (F6.1 deja la
    preparación, no implementa migraciones): una ``schema_version = 2``
    añadiría aquí su lector/migración sin tocar el resto de la capa.
    """
    document = _require_dict(value, "documento")
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        _fail("schema_version: falta el campo o no es un entero.")
    if version != SCHEMA_VERSION:
        _fail(
            f"Versión de esquema incompatible: {version} "
            f"(esta aplicación soporta schema_version={SCHEMA_VERSION})."
        )
    return _document_v1(document)


def _document_v1(document: dict) -> tuple[Project, EditorState]:
    """Lee y valida un documento con ``schema_version = 1``."""
    if "project" not in document:
        _fail("project: falta la sección obligatoria del proyecto.")

    project = project_from_dict(document["project"])

    raw_editor = document.get("editor")
    if raw_editor is None:
        state = EditorState(band_id=_default_band_id(project))
    else:
        editor = _require_dict(raw_editor, "editor")
        for field in ("band_id", "grid_resolution_m"):
            if field not in editor:
                _fail(f"editor.{field}: falta el campo obligatorio.")
        band_id = _require_id(editor["band_id"], "editor.band_id")
        known = {band.id for band in project.bands}
        if band_id not in known:
            _fail(f"editor.band_id: banda desconocida {band_id!r}.")
        resolution = _require_number(
            editor["grid_resolution_m"], "editor.grid_resolution_m", minimum=1e-6
        )
        state = EditorState(band_id=band_id, grid_resolution_m=resolution)

    _validate_grid_resolution(project, state.grid_resolution_m)
    return project, state


# ---------------------------------------------------------------------------
# Archivo (guardar / abrir)
# ---------------------------------------------------------------------------


def save_project(
    project: Project,
    path: str | Path,
    editor_state: EditorState | None = None,
) -> Path:
    """Guarda el proyecto en ``path`` de forma atómica (temp + fsync + replace).

    El documento se revalida antes de escribir: nunca se deja en disco
    un archivo que la propia aplicación no podría abrir.

    Raises:
        ProjectFormatError: el proyecto no es serializable o no valida.
        OSError: error de escritura (el archivo previo queda intacto).
    """
    document = document_to_dict(project, editor_state)
    # Revalidación: lo que guardas debe poder abrirse.
    document_from_dict(document)

    try:
        text = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProjectFormatError(
            f"El proyecto no es serializable a JSON: {exc}"
        ) from exc

    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)

    # Escritura atómica: temporal + fsync (durabilidad) + replace.
    # Si algo falla antes del replace, el archivo previo queda intacto
    # y el temporal se elimina.
    temporary = target.with_name(target.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def load_project(path: str | Path) -> tuple[Project, EditorState]:
    """Carga y valida un proyecto desde ``path``.

    Raises:
        ProjectFormatError: archivo ausente, demasiado grande, no UTF-8,
            JSON inválido, esquema incompatible o valores inválidos.
    """
    source = Path(path)
    if not source.exists():
        raise ProjectFormatError(f"El archivo no existe: {source}")
    if not source.is_file():
        raise ProjectFormatError(f"La ruta no es un archivo: {source}")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ProjectFormatError(f"No se puede leer {source}: {exc}") from exc
    if size > MAX_FILE_BYTES:
        raise ProjectFormatError(
            f"Archivo demasiado grande ({size} bytes; máximo {MAX_FILE_BYTES})."
        )
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectFormatError(
            f"El archivo no es texto UTF-8 válido: {exc}"
        ) from exc
    except OSError as exc:
        raise ProjectFormatError(f"No se puede leer {source}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectFormatError(f"JSON inválido en {source.name}: {exc}") from exc
    except (ValueError, RecursionError) as exc:
        # p. ej. entero con más de 4300 dígitos o anidamiento excesivo:
        # el fallo del parser también es un error controlado de formato.
        raise ProjectFormatError(f"JSON ilegible en {source.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectFormatError(
            f"El documento debe ser un objeto JSON (got {type(data).__name__})."
        )
    return document_from_dict(data)
