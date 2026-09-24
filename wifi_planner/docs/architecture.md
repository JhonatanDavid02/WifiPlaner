# Arquitectura — Wi-Fi Planner V1

## Visión general

Wi-Fi Planner es un sistema de diseño y simulación visual de redes Wi-Fi.
La V1 establece la **fundación**: dominio, geometría en metros, motor RF
centralizado, configuración centralizada, pruebas y documentación.

**Fase 6 + 6.1 (actual):** persistencia local de proyectos en **JSON**,
auditada y endurecida (F6.1). El `Project` es la única fuente de verdad
editable: se guarda a archivo y se regenera todo lo derivado
(simulación, heatmap, UI) al abrir. La capa `persistence/` aísla el
formato del dominio y de la UI, trata el archivo como **entrada no
confiable** (incluido el parser) y escribe de forma atómica y durable.

**Fase 5:** editor 2D + **heatmap multi-AP** sobre el mismo
`CoverageGrid`. Cada AP se evalúa con `simulate_coverage` y se combinan
con `combine_results` (mejor RSSI por punto; **no** es interferencia).
El heatmap es una **estimación predictiva** del modelo configurado;
no es una simulación electromagnética completa.

## Separación de capas

```
┌─────────────────────────────────────────────┐
│  UI (Fase 3–6)                              │
│  editor 2D (Tkinter), heatmap (Pillow),     │
│  viewport (metros→píxeles), paneles,        │
│  menú Archivo (Nuevo/Abrir/Guardar)         │
│  CONSUME SimulationResult / LinkEvaluation  │
│  NUNCA serializa el proyecto por su cuenta  │
│  NUNCA contiene fórmulas de RF              │
├─────────────────────────────────────────────┤
│  persistence/  (Fase 6)                    │
│  Project ↔ JSON (schema_version), validación│
│  de entrada no confiable, escritura atómica │
│  Importa core/ (+ engine solo para validar  │
│  límites del grid). NO importa UI           │
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
│  NO importa UI ni persistence              │
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

### `ui/` (Fase 3–6)
Presentación. Sin fórmulas RF; solo pintar, capturar eventos y llamar
al engine / `EditorSession`.

| Módulo | Responsabilidad |
|---|---|
| `session.py` | `EditorSession`: operaciones puras sobre `Project` (testeable sin Tk): editor + guardar/abrir/nuevo + dirty state |
| `viewport.py` | **Único** conversor metros ↔ píxeles (escala isotrópica) |
| `editor_canvas.py` | Canvas: capas floor → heatmap → walls → APs → leyenda; hit-test |
| `coverage_renderer.py` | `SimulationResult` → imagen Pillow RGBA + leyenda + stats |
| `app.py` | Ventana principal, **debounce ~150 ms** del heatmap, menú **Archivo** (Nuevo/Abrir/Guardar/Guardar como) y confirmación de cambios sin guardar |
| `panels/toolbar.py` | Herramienta, banda, resolución, toggle heatmap, dimensiones, selector de AP |
| `panels/properties.py` | Propiedades del elemento + resumen simulación/heatmap |

### `persistence/` (Fase 6, endurecida en 6.1)
Representación externa del proyecto en **JSON**. Convierte
`Project → dict → archivo` y `archivo → Project` con validación estricta
(esquema, límites, NaN/Inf, booleans ≠ números, ids únicos, material
referenciado, ≥ 1 piso). El parser también se trata como no confiable
(`ValueError`/`RecursionError` ⇒ `ProjectFormatError`). No conoce
Tkinter ni simula; el dominio (`core/`) no sabe que existen archivos.

| Módulo | Responsabilidad |
|---|---|
| `json_project_repository.py` | `save_project` (revalida + `.tmp` + `fsync` + `os.replace`) / `load_project`, `project_to_dict` / `project_from_dict`, dispatch por `schema_version` (`_document_v1`; punto de extensión para futuras versiones), `ProjectFormatError`, límites |
| `EditorState` | Preferencias persistibles del editor: banda activa y resolución del grid |

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

### Heatmap (Fase 4–5)

- **Fase 5:** selector `AP:` en toolbar → `Todos los AP` (combinado) o
  un AP individual. El combinado itera `simulate_coverage` sobre el
  **mismo** `CoverageGrid` y fusiona con `combine_results` (mejor RSSI
  por punto; empate → menor `access_point_id`).
- Invalidación + debounce ~150 ms (F4) reutilizada en F5: mover AP,
  banda, pared, dimensión, resolución, agregar/eliminar AP, cambiar
  selector de AP.
- `%` de cobertura: denominador = **puntos totales del grid**.
- Dominancia (`ap_dominance_percent`): puntos dominados por cada AP ÷
  total (suma ≈ 100 %).
- Disclaimer: estimación predictiva, no simulación EM.
- 6 GHz: error visible (`MaterialAttenuationError`), sin fallback.
- **No** hay interferencia, SINR, roaming ni optimización de canales.

### Persistencia (Fase 6)

```
             ┌──────────────┐
             │   Project    │  fuente de verdad (metros)
             └──────┬───────┘
        ┌───────────┴───────────┐
        ▼                       ▼
  persistence/              engine/
   (JSON, v1)            simulate_coverage
        │                       │
        ▼                       ▼
   archivo .json         SimulationResult
                               │
                               ▼
                         UI (heatmap/paneles)
```

- El archivo guarda **solo** el `Project` + `EditorState` (banda y
  resolución). Al abrir: `JSON → Project → simulate → UI`.
- `schema_version` obligatoria; incompatible ⇒ `ProjectFormatError`
  (error visible, proyecto actual intacto, sin carga parcial). El
  dispatch por versión (`_document_v1`) es el punto donde una futura
  v2 añadiría su lector/migración (F6.1 solo deja la preparación).
- Coordenadas siempre en metros (`x_m`/`y_m`); los píxeles solo existen
  en `Viewport`.
- Las paredes referencian materiales por id dentro del propio catálogo
  del proyecto (el archivo es autocontenido); se exige **≥ 1 piso**
  (simetría guardar/cargar).
- Escritura atómica y durable (`.tmp` + `fsync` + `os.replace`) y
  revalidación previa: no se deja un archivo que la app no pueda abrir,
  y un fallo de escritura no destruye el archivo anterior.
- Todo el JSON es **entrada no confiable**: validación de tipos
  (booleanos nunca pasan por números), NaN/Inf, límites de dimensiones,
  coordenadas, espesores, listas, strings, metadata, resolución del
  grid y tamaño de archivo; incluso los errores del parser
  (`ValueError`/`RecursionError`) se convierten en `ProjectFormatError`.
- Invariante de edición: **dimensiones + resolución ⇒ grid usable** se
  comprueba al cambiar cualquiera de los dos ⇒ el proyecto siempre es
  simulable y guardable.
- Al cambiar de documento la UI se limpia por completo (heatmap,
  selección, herramienta, arrastre, selector de AP): no queda estado
  residual del proyecto anterior.
- **No** se persisten: selección, herramienta, heatmap, resultados de
  simulación ni imágenes (se regeneran; ver `docs/decisions.md` AB–AT).

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
- **Fase 5 (hecha):** multi-AP — mismo grid, `combine_results`,
  selector Todos/AP, dominancia por AP, estadísticas combinadas.
- **Fase 6 (hecha):** persistencia local JSON — `Project` ↔ archivo,
  schema versionado, guardar/abrir/nuevo, dirty state.
- **Fase 6.1 (hecha):** endurecimiento de persistencia — parser duro,
  límites extremos, invariante dims/resolución, simetría guardar/cargar,
  fsync, limpieza de estado residual, dispatch por versión.
- **Fase 7:** por definir (p. ej. huecos/`Opening`, espacios `Space`,
  canales).
- **Futuro 3D:** `Floor.elevation_m` ya existe; geometría 2D no cambia.
- **Openings / huecos:** atenuación diferenciada en fase posterior.
- **Otras bases de datos / API / nube:** la capa `persistence/` es el
  punto de sustitución sin tocar `core/` ni `engine/`.
