"""Obstáculos físicos interiores (mobiliario y objetos).

Fase 9. Responsabilidades separadas (docs/decisions.md, decisión BL):

- ``Wall``     = elemento arquitectónico estructural.
- ``Opening``  = interrupción de una ``Wall``.
- ``Space``    = región arquitectónica (sin RF, decisión BH).
- ``Obstacle`` = objeto físico interior que puede atenuar la señal.

El footprint es un ``Rect`` alineado a ejes en metros: aproximación 2D
**sin altura**, sin polígonos arbitrarios y sin giro — el editor trabaja
con la misma primitiva que los espacios (decisión BL).

La atenuación por banda procede del catálogo de materiales del
proyecto (``Material.attenuation_for``) y puede **sustituirse** por
banda con ``attenuation_override_db`` (nunca se suman; decisión BM).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.geometry import Rect
from core.material import Material

# Tipos semánticos (metadato del editor). NO hay una clase Python por
# tipo: “mobiliario” es ``Obstacle(kind="furniture")`` (decisión BL).
OBSTACLE_KINDS: tuple[str, ...] = ("furniture", "equipment", "column", "other")

# Tamaño mínimo por lado al crear desde el editor, en metros (un rect
# menor sería invisible/inutilizable; misma filosofía que los espacios).
MIN_OBSTACLE_SIZE_M = 0.1

# Tamaño máximo por lado aceptado en archivo, en metros (mismo orden
# que las dimensiones del piso; la validación vive en persistencia).
MAX_OBSTACLE_SIZE_M = 1_000.0

# Rango del override por banda en dB (idéntico al de los openings).
MAX_OBSTACLE_ATTENUATION_DB = 200.0

# Material por defecto al crear desde el editor (mobiliario típico).
DEFAULT_OBSTACLE_MATERIAL_ID = "wood"


@dataclass(frozen=True)
class Obstacle:
    """Objeto físico interior con footprint rectangular y atenuación propia.

    Attributes:
        id: Identificador estable (ej. "OBST-001").
        name: Nombre legible (ej. "Mesa").
        rect: Footprint en metros (rect alineado a ejes).
        material: Material del catálogo del proyecto (obligatorio).
        kind: "furniture" | "equipment" | "column" | "other".
        attenuation_override_db: {band_id: pérdida en dB}. Si la banda
            evaluada está aquí, este valor **sustituye** al de referencia
            del material (decisión BM); nunca se suman.
        blocks_signal: Si es False el motor lo ignora (como en Wall).
        metadata: Datos adicionales libres.
    """

    id: str
    name: str
    rect: Rect
    material: Material
    kind: str = "furniture"
    attenuation_override_db: dict = field(default_factory=dict)
    blocks_signal: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Obstacle.id debe ser un texto no vacío.")
        if not isinstance(self.name, str):
            raise ValueError("Obstacle.name debe ser un texto.")
        if self.kind not in OBSTACLE_KINDS:
            raise ValueError(
                f"Obstacle.kind no soportado: {self.kind!r} "
                f"(permitidos: {', '.join(OBSTACLE_KINDS)})."
            )
        if not isinstance(self.rect, Rect):
            raise ValueError("Obstacle.rect debe ser un Rect.")
        for name in ("x", "y", "width", "height"):
            value = getattr(self.rect, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Obstacle.rect.{name} debe ser un número.")
            if not math.isfinite(float(value)):
                raise ValueError(f"Obstacle.rect.{name} debe ser finito.")
        if not isinstance(self.material, Material):
            raise ValueError(
                "Obstacle.material debe ser un Material del catálogo."
            )
        if not isinstance(self.attenuation_override_db, dict):
            raise ValueError("Obstacle.attenuation_override_db debe ser un dict.")
        overrides: dict[str, float] = {}
        for band_id, raw in self.attenuation_override_db.items():
            if not isinstance(band_id, str) or not band_id:
                raise ValueError(
                    "Obstacle.attenuation_override_db: las claves deben ser "
                    "band ids no vacíos."
                )
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(
                    f"Obstacle.attenuation_override_db[{band_id!r}] debe ser "
                    "un número."
                )
            loss = float(raw)
            if not math.isfinite(loss) or not (
                0.0 <= loss <= MAX_OBSTACLE_ATTENUATION_DB
            ):
                raise ValueError(
                    f"Obstacle.attenuation_override_db[{band_id!r}] debe estar "
                    f"en [0, {MAX_OBSTACLE_ATTENUATION_DB:g}] dB (got {raw!r})."
                )
            overrides[band_id] = loss
        object.__setattr__(self, "attenuation_override_db", overrides)

    @property
    def size_m(self) -> tuple[float, float]:
        """Tamaño del footprint en metros (ancho, alto)."""
        return (self.rect.width, self.rect.height)
