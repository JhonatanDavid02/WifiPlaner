# Arquitectura — Wi-Fi Planner V1

## Visión general

Wi-Fi Planner es un sistema de diseño y simulación visual de redes Wi-Fi.
La V1 establece la **fundación**: dominio, geometría en metros, motor RF
centralizado, configuración centralizada, pruebas y documentación.

No existe interfaz gráfica en V1. La futura UI (editor 2D, heatmap) se
añadirá en fases posteriores **sin tocar el motor**.

## Separación de capas

```
┌─────────────────────────────────────────────┐
│  UI (futura, Fase 3+)                      │
│  editor 2D, heatmap, ventanas, canvas       │
│  CONSUME SimulationResult / LinkEvaluation  │
│  NUNCA contiene fórmulas de RF              │
├─────────────────────────────────────────────┤
│  engine/  (motor RF)                       │
│  propagation, link_budget, classifier,      │
│  obstacles, simulator, combine              │
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
│  tests/  (pruebas del motor)               │
│  pytest, deterministas, sin UI              │
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
| `space.py` | `Space`, `Floor` — zonas y pisos |
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
| `simulator.py` | Simulación de cobertura (puntos; grid en Fase 4) |
| `combine.py` | Combinación de resultados multi-AP (Fase 5) |

### `config/`
Configuración centralizada en YAML. Radio, umbrales, bandas y materiales
viven aquí. El código los recibe por parámetro o los carga con `load_config()`.

### `tests/`
Pruebas deterministas con pytest. Incluyen golden data extraída del DOCX
legacy (Tablas 2 y 3) para validar que el motor nuevo reproduce los
resultados históricos aprobados.

## Flujo de datos (editor + paredes + heatmap)

```
UI (metros)                    engine                              UI (píxeles)
┌──────────┐   Project, AP    ┌────────────────────────────┐        ┌────────────┐
│ Editor   │ ───────────────► │ 1. trace_walls(AP → punto) │        │ Heatmap    │
│ (canvas) │   band, puntos   │    intersección + materiales│       │ (viewport) │
│ + walls  │                  │ 2. L_obstacles             │   SimulationResult
└──────────┘                  │ 3. FSPL + link budget      │ ─────► │ rx, quality│
                              │ 4. SOM + clasificación     │        │ verdict    │
                              └────────────────────────────┘        └────────────┘
```

1. El editor construye un `Project` con geometría en **metros** (paredes
   como `Wall` con `Segment2D` + `Material` + espesor).
2. La UI llama a `engine.simulate_coverage(..., walls=floor.walls)`.
3. Por cada punto, `engine.obstacles.trace_walls(source, target, walls, band)`:
   - `engine.intersection.segments_cross` decide qué paredes se atraviesan
     (cruce interior estricto; extremos/esquinas no cuentan);
   - `wall_attenuation_db` aplica `L_ref * (espesor / espesor_ref)`;
   - devuelve `ObstacleTraceResult` ordenado por distancia desde el AP.
4. El `ObstacleLoss` total entra al link budget canónico (`L_obstacles`).
5. El motor devuelve `SimulationResult` con `LinkEvaluation` por punto.
6. La UI convierte metros → píxeles y pinta el resultado.
7. La UI **nunca** recalcula FSPL, SOM, intersecciones ni umbrales.

### `trace_walls` (responsabilidad clave)

```
trace_walls(source, target, walls, band_id) -> ObstacleTraceResult
```

- Evalúa cada pared con `blocks_signal=True` contra el segmento
  AP → punto.
- Conserva **orden y detalle** por pared (`WallCrossing`: id, material,
  pérdida, distancia, orden) — no solo un número.
- Total: `attenuation_db = Σ loss_db` (redondeado a 2 decimales).
- Determinista: empates de distancia se rompen por `wall.id`.

## Unidades

| Magnitud | Unidad |
|---|---|
| Coordenadas, distancias, espesores | **metros (m)** |
| Frecuencia | MHz (FSPL) / Hz (longitud de onda) |
| Potencia, sensibilidad | dBm |
| Ganancia | dBi |
| Pérdidas, FSPL, SOM, atenuación | dB |
| Área | m² |

Los píxeles **no existen** en `core/` ni `engine/`. Pertenecen
exclusivamente al futuro viewport.

## Preparación para fases posteriores

- **Fase 2 (hecha):** trazado rayo-pared (`intersection` + `trace_walls`)
  e integración de `L_obstacles` real en `simulate_coverage`.
- **Fase 3:** editor 2D consume `core/geometry` y `core/wall`.
- **Fase 4:** grid de simulación + heatmap consumen `simulate_coverage`.
- **Fase 5:** `combine_results` fusiona múltiples AP.
- **Fase 6:** persistencia de `Project` (JSON/YAML).
- **Futuro 3D:** `Floor.elevation_m` ya existe; geometría 2D no cambia.
- **Openings / huecos:** `core.wall.Opening` existe; la atenuación
  diferenciada de puertas/ventanas se conectará en fase posterior.
