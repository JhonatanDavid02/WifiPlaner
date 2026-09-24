"""Persistencia local de proyectos (JSON).

Capa aislada entre el dominio (``core/``) y el almacenamiento:

    Project  ──►  persistence  ──►  JSON (archivo local)

Reglas de la capa:

- ``core/`` y ``engine/`` NO importan este módulo (el dominio no sabe
  que existe un archivo).
- La UI no serializa: solo pide guardar/abrir (vía ``EditorSession``).
- Todo lo que aquí se escribe es **dato del proyecto** en metros;
  nunca estado de Tkinter, imágenes ni resultados de simulación.
- El formato está versionado (``schema_version``) para poder evolucionar
  sin romper proyectos antiguos de forma silenciosa.
"""

from __future__ import annotations

from persistence.json_project_repository import (
    DEFAULT_GRID_RESOLUTION_M,
    SCHEMA_VERSION,
    EditorState,
    ProjectFormatError,
    document_from_dict,
    document_to_dict,
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)

__all__ = [
    "DEFAULT_GRID_RESOLUTION_M",
    "SCHEMA_VERSION",
    "EditorState",
    "ProjectFormatError",
    "document_from_dict",
    "document_to_dict",
    "load_project",
    "project_from_dict",
    "project_to_dict",
    "save_project",
]
