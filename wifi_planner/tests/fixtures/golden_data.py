"""Golden data extraído del DOCX/XLSX legacy del proyecto CUN.

Tabla 2 (DOCX §8.2): FSPL / RSSI / SOM para distancias 5/10/15/20 m
en 2.4 GHz (2437 MHz) y 5 GHz (5180 MHz).

Supuestos del presupuesto de enlace legacy (DOCX Tabla 1):
    P_tx=20 dBm, G_tx=3 dBi, L_tx=1 dB, L_m=10 dB, G_rx=0 dBi,
    L_rx=1 dB, sensibilidad=-75 dBm.

Tabla 3 (DOCX §9): SOM por AP en el caso peor de cada banda,
usando las distancias máximas 3.80 / 4.88 / 5.42 / 5.58 m
(decisión A: distancias históricas DOCX/v1/v2; NO las de v3/v4).

NO editar estos valores sin una decisión explícita documentada
en docs/decisions.md.
"""

# Parámetros del enlace legacy usados para generar la golden data.
LEGACY_RADIO_PARAMS = {
    "p_tx_dbm": 20.0,
    "g_tx_dbi": 3.0,
    "l_tx_db": 1.0,
    "fade_margin_db": 10.0,
    "g_rx_dbi": 0.0,
    "l_rx_db": 1.0,
    "sensitivity_dbm": -75.0,
}

BAND_24_MHZ = 2437.0
BAND_5_MHZ = 5180.0

# Tabla 2 DOCX: (distancia_m, freq_mhz, fspl_db, rssi_dbm, som_db, veredicto)
TABLA_2 = [
    (5.0, BAND_24_MHZ, 54.17, -43.17, 31.83, "APROBADO"),
    (5.0, BAND_5_MHZ, 60.72, -49.72, 25.28, "APROBADO"),
    (10.0, BAND_24_MHZ, 60.19, -49.19, 25.81, "APROBADO"),
    (10.0, BAND_5_MHZ, 66.74, -55.74, 19.26, "RIESGO"),
    (15.0, BAND_24_MHZ, 63.71, -52.71, 22.29, "APROBADO"),
    (15.0, BAND_5_MHZ, 70.26, -59.26, 15.74, "RIESGO"),
    (20.0, BAND_24_MHZ, 66.21, -55.21, 19.79, "RIESGO"),
    (20.0, BAND_5_MHZ, 72.76, -61.76, 13.24, "RIESGO"),
]

# Tabla 3 DOCX: (ap_id, distancia_m, som_24_db, som_5_db)
# Som 2.4 GHz reportado en el DOCX como rango 30.88–34.22 dB;
# los valores intermedios se recalculan con la misma fórmula canónica
# (FSPL + Lm=10) para evitar la imprecisión de transcripción manual.
TABLA_3 = [
    ("AP1", 3.80, 34.22, 27.67),
    ("AP2", 4.88, 32.04, 25.50),
    ("AP3", 5.42, 31.13, 24.58),
    ("AP4", 5.58, 30.88, 24.33),
]

# Umbrales de veredicto (decisión D).
SOM_APROBADO_MIN = 20.0
SOM_RIESGO_MIN = 10.0

# RSSI objetivo estricto (decisión C).
RSSI_TARGET_DBM = -67.0

# Distancias divergentes de v3/v4 congeladas como legacy (NO usar).
LEGACY_V3_V4_DISTANCIAS = {
    "AP1": 5.72,
    "AP2": 8.92,
    "AP3": 6.87,
    "AP4": 9.65,
}
