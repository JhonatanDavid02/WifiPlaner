# Fórmulas — Wi-Fi Planner V1

Todas las fórmulas viven en `engine/`. La UI no las contiene.

Unidades: distancia `d` en **metros**, frecuencia `f` en **MHz**,
potencia en **dBm**, pérdidas en **dB**, ganancia en **dBi**.

---

## 1. Longitud de onda

```
λ = c / f
```

- `c = 3 × 10⁸ m/s` (velocidad de la luz, aproximación de ingeniería)
- `f` en Hz
- `λ` resulta en metros

Ejemplos:
- 2.4 GHz → λ = 12.5 cm
- 5 GHz → λ = 6 cm

Implementación: `engine.propagation.wavelength_m(frequency_hz)`

---

## 2. Free Space Path Loss (FSPL)

```
FSPL(dB) = 20 · log10(d) + 20 · log10(f_MHz) − 27.55
```

- `d` en metros, debe ser `> 0`
- `f` en MHz, debe ser `> 0`
- Resultado redondeado a 2 decimales (compatibilidad con legacy)

Validaciones: se lanza `ValueError` si `d ≤ 0` o `f ≤ 0`.

Implementación: `engine.propagation.path_loss_fspl_db(distance_m, frequency_mhz)`

---

## 3. Presupuesto de enlace (P_rx / RSSI)

```
P_rx = P_tx + G_tx − L_tx − FSPL − L_m + G_rx − L_rx − L_obstacles
```

| Símbolo | Significado | Unidad | Defecto |
|---|---|---|---|
| `P_tx` | Potencia de transmisión | dBm | 20.0 |
| `G_tx` | Ganancia antena TX | dBi | 3.0 |
| `L_tx` | Pérdidas TX | dB | 1.0 |
| `FSPL` | Pérdida en espacio libre | dB | calculado |
| `L_m` | Fade margin (margen de desvanecimiento) | dB | **10.0** |
| `G_rx` | Ganancia antena RX | dBi | 0.0 |
| `L_rx` | Pérdidas RX | dB | 1.0 |
| `L_obstacles` | Pérdida por materiales atravesados | dB | 0.0 (sin paredes) |

Notas:
- `L_m = 10 dB` por defecto (**decisión B**). Es configurable.
- Para reproducir las versiones legacy v3/v4 (que omitían `L_m`),
  usar `fade_margin_db = 0.0`.
- `L_obstacles` proviene de `trace_walls` cuando se pasan paredes
  (Fase 2); es `0.0` si no hay obstáculos.

Implementación: `engine.link_budget.link_budget(...)`

---

## 4. System Operating Margin (SOM)

```
SOM(dB) = P_rx − Sensibilidad
```

- `P_rx` en dBm
- Sensibilidad en dBm (defecto `-75.0`)
- Resultado en dB, redondeado a 2 decimales

Implementación: `engine.link_budget.system_operating_margin(...)`

---

## 5. Clasificación SOM (veredicto)

| Condición | Veredicto |
|---|---|
| `SOM ≥ 20 dB` | **APROBADO** |
| `10 dB ≤ SOM < 20 dB` | **RIESGO** |
| `SOM < 10 dB` | **FALLIDO** |

Los umbrales 20 y 10 son **configurables** (`CoverageThresholds`),
no números mágicos. Comparación con `≥` (**decisión D**).

Implementación: `engine.classifier.classify_som(som_db, thresholds)`

---

## 6. RSSI objetivo

```
P_rx > −67 dBm   →  CUMPLE
P_rx ≤ −67 dBm   →  NO CUMPLE
```

Comparación **estricta** (`>`), no `≥` (**decisión C**).
El umbral `-67 dBm` es configurable (`CoverageThresholds.rssi_target_dbm`).

Implementación: `engine.classifier.meets_rssi_target(rx_power_dbm, thresholds)`

---

## 7. Clases de cobertura (calidad)

| Clase | Condición (P_rx) |
|---|---|
| Excelente | `≥ −50 dBm` |
| Buena | `≥ −67 dBm` |
| Regular | `≥ −75 dBm` |
| Débil | `≥ −85 dBm` |
| Sin cobertura útil | `< −85 dBm` |

Todos los umbrales son configurables (`CoverageThresholds`).
Esta clasificación prepara el heatmap de fases posteriores.

Implementación: `engine.classifier.classify_quality(rx_power_dbm, thresholds)`

---

## 8. Pérdida por obstáculos (paredes reales)

```
L_total_obstacles = Σ L_wall_i          (por cada pared atravesada)

L_wall = L_referencia(material, banda) × (espesor_actual / espesor_referencia)
```

### Trazado (Fase 2)

Para cada par (AP → punto):

1. Se construye el segmento `path = Segment2D(AP, punto)`.
2. Cada `Wall` con `blocks_signal=True` se evalúa con
   `engine.intersection.segments_cross` (cruce interior estricto).
3. Las paredes cruzadas se ordenan por distancia desde el AP.
4. Cada crice aporta `L_wall` con el modelo de espesor.
5. El total entra al link budget como `L_obstacles`.

### Modelo de espesor (aproximación de ingeniería)

```
L_wall = L_ref × (t_actual / t_ref)
```

- `t_ref = material.thickness_default_m` (espesor de referencia).
- `L_ref = material.attenuation_db[band_id]` (atenuación de referencia).
- Si `t_actual = t_ref` → `L_wall = L_ref` (sin cambio).
- Si `thickness_m = None` en la pared → se usa `t_ref` (`L = L_ref`).
- Validaciones: `t_actual > 0`, `t_ref > 0`, material con datos para la banda.

**Advertencia:** el escalado lineal es una **aproximación de ingeniería**
para el modelo predictivo V1. **NO** es una simulación electromagnética
ni una curva de atenuación medida por capas.

Valores de referencia de materiales (estimaciones configurables,
ver `config/default_config.yaml` y `docs/decisions.md`):

| Material | 2.4 GHz | 5 GHz | Espesor ref. |
|---|---:|---:|---:|
| Drywall | 3 dB | 4 dB | 12 mm |
| Madera | 3 dB | 4 dB | 40 mm |
| Vidrio | 3 dB | 4 dB | 8 mm |
| Ladrillo | 6 dB | 8 dB | 120 mm |
| Concreto | 12 dB | 15 dB | 150 mm |
| Concreto reforzado | 15 dB | 20 dB | 200 mm |
| Metal | 25 dB | 30 dB | 5 mm |

### 6 GHz

No hay `L_ref` configurada para `band_6` en el catálogo V1.
Consultar atenuación lanza `MaterialAttenuationError`. No se inventan
valores ni se convierte silenciosamente 5 → 6 GHz.

Implementación: `engine.obstacles.wall_attenuation_db`,
`engine.obstacles.trace_walls`.

---

## 10. Heatmap de cobertura (Fase 4) — estimación, no EM

**Disclaimer:** el heatmap es una **estimación predictiva** del modelo
configurado (FSPL + presupuesto de enlace + atenuación de materiales
configurables). **NO** es una simulación electromagnética completa ni
sustituye mediciones en sitio.

### Muestreo (`engine.coverage_grid.CoverageGrid`)

- Puntos en múltiplos de `resolution_m` desde `(0,0)`, más un punto de
  borde si la dimensión no es múltiplo exacto (decisión L).
- Límites V1: `resolution_m ≥ 0.05 m`, `point_count ≤ 100_000`.
- Ejemplo: 12 × 8 m @ 0.50 m → 25 × 17 = **425** puntos.

### Flujo por punto del grid

Misma cadena canónica que las secciones 1–8, sin fórmulas nuevas:

```
para cada punto p en CoverageGrid.points():
    L_obstacles = Σ L_wall   (trace_walls AP → p, decisión K)
    P_rx = link_budget(..., L_obstacles)
    SOM  = P_rx − sensibilidad
    calidad = classify_quality(P_rx, umbrales)
```

- **Un solo AP** por heatmap (decisión M).
- `%` de cobertura: denominador = **todos los puntos del grid**
  (decisión P).
- Si un punto del grid cae **sobre el AP** (`d = 0`), `evaluate_link`
  usa un piso `MIN_FSPL_DISTANCE_M = 0.1 m` solo para FSPL
  (decisión T); la fórmula FSPL no se modifica.
- Visualización: color continuo de `P_rx` en `ui/coverage_renderer`
  (solo presentación; no altera umbrales RF).
- Invalidación + debounce al editar modelo (decisión O).

---

## 9. Ejemplo del DOCX (validación)

Distancia 10 m, 5 GHz (5180 MHz), con `L_m = 10 dB`:

```
FSPL = 20·log10(10) + 20·log10(5180) − 27.55 = 66.74 dB
P_rx = 20 + 3 − 1 − 66.74 − 10 + 0 − 1     = −55.74 dBm
SOM  = −55.74 − (−75)                       = 19.26 dB  → RIESGO
```

Este caso está incluido en la golden data (`tests/fixtures/golden_data.py`,
Tabla 2) y se valida en `tests/test_link_budget.py`.
