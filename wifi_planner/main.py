"""Punto de entrada de Wi-Fi Planner V1.

Fase 3: abre el editor 2D (Tkinter).

Uso:
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permitir ejecución directa desde la raíz del paquete wifi_planner/.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from ui import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
