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
| `obstacles.py` | Pérdida acumulada por materiales atravesados |
| `simulator.py` | Simulación de cobertura (puntos; grid en Fase 4) |
| `combine.py` | Combinación de resultados multi-AP (Fase 5) |

### `config/`
Configuración centralizada en YAML. Radio, umbrales, bandas y materiales
viven aquí. El código los recibe por parámetro o los carga con `load_config()`.

### `tests/`
Pruebas deterministas con pytest. Incluyen golden data extraída del DOCX
legacy (Tablas 2 y 3) para validar que el motor nuevo reproduce los
resultados históricos aprobados.

## Flujo de datos (futuro editor + heatmap)

```
UI (metros)                    engine                      UI (píxeles)
┌──────────┐   Project, AP    ┌──────────────────┐   SimulationResult  ┌────────────┐
│ Editor   │ ───────────────► │ simulate_coverage│ ─────────────────► │ Heatmap    │
│ (canvas) │   band, puntos   │ (FSPL + Lm +     │   rx_power_dbm     │ (viewport) │
└──────────┘                  │  obstáculos)     │   quality, verdict └────────────┘
                              └──────────────────┘
```

1. El editor construye un `Project` con geometría en **metros**.
2. La UI llama a `engine.simulate_coverage(...)`.
3. El motor devuelve `SimulationResult` con `LinkEvaluation` por punto.
4. La UI convierte metros → píxeles y pinta el resultado.
5. La UI **nunca** recalcula FSPL, SOM ni umbrales.

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

- **Fase 2:** trazado rayo-pared en `engine/obstacles.py` (ya suma materiales).
- **Fase 3:** editor 2D consume `core/geometry` y `core/wall`.
- **Fase 4:** grid de simulación + heatmap consumen `simulate_coverage`.
- **Fase 5:** `combine_results` fusiona múltiples AP.
- **Fase 6:** persistencia de `Project` (JSON/YAML).
- **Futuro 3D:** `Floor.elevation_m` ya existe; geometría 2D no cambia.
