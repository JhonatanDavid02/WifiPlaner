# Arquitectura — Wi-Fi Planner V1

## Visión general

Wi-Fi Planner es un sistema de diseño y simulación visual de redes Wi-Fi.
La V1 establece la **fundación**: dominio, geometría en metros, motor RF
centralizado, configuración centralizada, pruebas y documentación.

**Fase 4 (actual):** editor 2D + **heatmap de cobertura** sobre
`CoverageGrid`. El heatmap es una **estimación predictiva** del modelo
configurado; no es una simulación electromagnética completa.

## Separación de capas

```
┌─────────────────────────────────────────────┐
│  UI (Fase 3–4)                              │
│  editor 2D (Tkinter), heatmap (Pillow),     │
│  viewport (metros→píxeles), paneles         │
│  CONSUME SimulationResult / LinkEvaluation  │
│  NUNCA contiene fórmulas de RF              │
├─────────────────────────────────────────────┤
│  engine/  (motor RF)                       │
│  propagation, link_budget, classifier,      │
│  obstacles, intersection, coverage_grid,    │
│  simulator, combine                         │
│  Funciones puras, deterministas, testeables │
│  NO importa tkinter ni PIL                 │
├─────────────────────────────────────────────┤
│  core/  (modelo de dominio)                │
│  geometry (metros), space, wall, material,  │
│  band, radio, access_point, client,         │
│  project, result                            │
│  NO contiene fórmulas de RF                │
│  NO importa UI                             │
├─────────────────────────────────────────────┤
│  config/  (configuración central)          │
│  default_config.yaml: umbrales, radios,     │
│  bandas, materiales                         │
│  NO hay números mágicos en el código        │
├─────────────────────────────────────────────┤
│  tests/  (pruebas del motor + UI sin Tk)   │
│  pytest, deterministas, sin abrir ventana   │
│  golden data del DOCX legacy               │
└─────────────────────────────────────────────┘
```

## Responsabilidades por módulo

### `core/`
Representa el dominio. Entidades puras, sin lógica de RF ni de UI.

| Módulo | Responsabilidad |
|---|---|
| `geometry.py` | `Point2D`, `Segment2D`, `Rect` — **unidades: metros** |
| `band.py` | `FrequencyBand` — 2.4 / 5 / 6 GHz desde V1 |
| `material.py` | `Material` — atenuación por banda, valores centralizados |
| `radio.py` | `RadioConfiguration` — P_tx, ganancias, pérdidas, Lm, sensibilidad |
| `access_point.py` | `AccessPoint` — posición en metros + configuración de radio |
| `client.py` | `ClientDevice` — posición + sensibilidad |
| `wall.py` | `Wall`, `Opening`, `Obstacle` — geometría + material + espesor |
| `space.py` | `Space`, `Floor` — zonas y pisos (`width_m`/`height_m`) |
| `project.py` | `Project`, `CoverageThresholds` — contenedor raíz + umbrales |
| `result.py` | `LinkEvaluation`, `SimulationResult`, `QualityClass`, `Verdict` |

### `engine/`
Motor de cálculo. Funciones puras que reciben geometría, parámetros y
devuelven resultados. **La UI solo consume estos resultados.**

| Módulo | Responsabilidad |
|---|---|
| `propagation.py` | Longitud de onda y FSPL |
| `link_budget.py` | Presupuesto de enlace, SOM, `evaluate_link` |
| `classifier.py` | Clasificación SOM / RSSI / calidad de cobertura |
| `intersection.py` | Cruce trayecto ↔ segmento de pared (interior estricto) |
| `obstacles.py` | `trace_walls`, atenuación por material/espesor, suma |
| `coverage_grid.py` | **Fase 4:** malla regular de puntos (metros), límites |
| `simulator.py` | `simulate_coverage` — un punto o el grid completo |
| `combine.py` | Combinación de resultados multi-AP (Fase 5) |

### `ui/` (Fase 3–4)
Presentación. Sin fórmulas RF; solo pintar, capturar eventos y llamar
al engine / `EditorSession`.

| Módulo | Responsabilidad |
|---|---|
| `session.py` | `EditorSession`: operaciones puras sobre `Project` (testeable sin Tk) |
| `viewport.py` | **Único** conversor metros ↔ píxeles (escala isotrópica) |
| `editor_canvas.py` | Canvas: capas floor → heatmap → walls → APs → leyenda; hit-test |
| `coverage_renderer.py` | `SimulationResult` → imagen Pillow RGBA + leyenda + stats |
| `app.py` | Ventana principal, **debounce ~150 ms** del heatmap |
| `panels/toolbar.py` | Herramienta, banda, resolución, toggle heatmap, dimensiones |
| `panels/properties.py` | Propiedades del elemento + resumen simulación/heatmap |

### `config/`
Configuración centralizada en YAML. Radio, umbrales, bandas y materiales
viven aquí. El código los recibe por parámetro o los carga con `load_config()`.

### `tests/`
Pruebas deterministas con pytest. Incluyen golden data extraída del DOCX
legacy (Tablas 2 y 3) y pruebas de grid/heatmap **sin abrir Tkinter**.

## Flujo de datos (editor + paredes + heatmap)

```
UI (metros)                    engine                              UI (píxeles)
┌──────────┐   Project, AP    ┌────────────────────────────┐        ┌────────────┐
│ Editor   │ ───────────────► │ 1. CoverageGrid.points()   │        │ Heatmap    │
│ (canvas) │   band, res.     │ 2. trace_walls(AP → punto) │        │ (viewport) │
│ + walls  │                  │ 3. L_obstacles             │   SimulationResult
└──────────┘                  │ 4. FSPL + link budget      │ ─────► │ rx, quality│
                              │ 5. SOM + clasificación     │        │ verdict    │
                              └────────────────────────────┘        └────────────┘
```

1. El editor construye un `Project` con geometría en **metros**.
2. `EditorSession.run_heatmap()` construye el `CoverageGrid` y llama a
   `engine.simulate_coverage(..., sample_points=grid.points(), walls=floor.walls)`.
3. Por cada punto, `trace_walls` + link budget canónico (sin fórmulas
   nuevas en la UI).
4. `ui.coverage_renderer.build_heatmap_image` pinta cada evaluación como
   celda centrada en su punto, alineada al `Viewport` (metros → píxeles
   solo vía `Viewport`).
5. Capas del Canvas: suelo/rejilla → heatmap → paredes → APs/clientes →
   leyenda. El hit-test del editor **no** depende de la capa heatmap.
6. La UI **nunca** recalcula FSPL, SOM, intersecciones ni umbrales.

### `trace_walls` (responsabilidad clave)

```
trace_walls(source, target, walls, band_id) -> ObstacleTraceResult
```

- Evalúa cada pared con `blocks_signal=True` contra el segmento
  AP → punto.
- Conserva **orden y detalle** por pared (`WallCrossing`).
- Total: `attenuation_db = Σ loss_db` (redondeado a 2 decimales).
- Determinista: empates de distancia se rompen por `wall.id`.

### Heatmap (Fase 4)

- **UN solo AP** por heatmap (seleccionado o primero).
- Invalidación + debounce ~150 ms al mover AP / cambiar banda /
  pared / dimensión / resolución.
- `%` de cobertura: denominador = **puntos totales del grid**.
- Disclaimer: estimación predictiva, no simulación EM.
- 6 GHz: error visible (`MaterialAttenuationError`), sin fallback.

## Unidades

| Magnitud | Unidad |
|---|---|
| Coordenadas, distancias, espesores, resolución grid | **metros (m)** |
| Frecuencia | MHz (FSPL) / Hz (longitud de onda) |
| Potencia, sensibilidad | dBm |
| Ganancia | dBi |
| Pérdidas, FSPL, SOM, atenuación | dB |
| Área | m² |
| Píxeles | solo `ui/viewport.py` + Canvas |

Los píxeles **no existen** en `core/` ni `engine/`.

## Preparación para fases posteriores

- **Fase 2 (hecha):** trazado rayo-pared + `L_obstacles` real.
- **Fase 3 (hecha):** editor 2D Tkinter.
- **Fase 4 (hecha):** `CoverageGrid` + heatmap + leyenda + stats.
- **Fase 5:** `combine_results` fusiona múltiples AP en el heatmap.
- **Fase 6:** persistencia de `Project` (JSON/YAML).
- **Futuro 3D:** `Floor.elevation_m` ya existe; geometría 2D no cambia.
- **Openings / huecos:** atenuación diferenciada en fase posterior.
