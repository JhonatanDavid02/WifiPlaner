"""Capa de interfaz de usuario (Tkinter).

Reglas:
- Esta capa PUEDE importar core/ y engine/.
- core/ y engine/ NUNCA importan ui/.
- La UI no contiene fórmulas RF: solo modela, invoca el engine y pinta.
"""

from __future__ import annotations

__all__ = ["run_app"]


def run_app() -> int:
    """Abre la ventana principal de Wi-Fi Planner. Devuelve exit code."""
    from ui.app import run_app as _run

    return _run()
