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
| `L_obstacles` | Pérdida por materiales atravesados | dB | 0.0 (Fase 1) |

Notas:
- `L_m = 10 dB` por defecto (**decisión B**). Es configurable.
- Para reproducir las versiones legacy v3/v4 (que omitían `L_m`),
  usar `fade_margin_db = 0.0`.
- `L_obstacles = 0` en Fase 1; la estructura ya lo contempla y se
  conecta con la geometría de paredes en Fase 2.

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

## 8. Pérdida por obstáculos (estructura V1)

```
L_obstacles = Σ atenuación(material_i, banda)
```

- Cada pared atravesada aporta la atenuación de su material para la banda.
- En Fase 1 la intersección rayo-pared aún no está implementada;
  `L_obstacles` se pasa como parámetro (defecto `0.0`).
- La suma de materiales ya es funcional: `engine.obstacles.obstacle_loss_for_crossings`.

Valores de referencia de materiales (estimaciones configurables,
ver `config/default_config.yaml` y `docs/decisions.md`):

| Material | 2.4 GHz | 5 GHz |
|---|---:|---:|
| Drywall | 3 dB | 4 dB |
| Madera | 3 dB | 4 dB |
| Vidrio | 3 dB | 4 dB |
| Ladrillo | 6 dB | 8 dB |
| Concreto | 12 dB | 15 dB |
| Concreto reforzado | 15 dB | 20 dB |
| Metal | 25 dB | 30 dB |

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
