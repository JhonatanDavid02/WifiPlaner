"""
=============================================================================
CALCULADORA DE INGENIERIA WLAN - BIBLIOTECA UNIVERSITARIA
Auditoria y Rediseno de Red Wi-Fi
Corporacion Unificada Nacional de Educacion Superior (CUN)
Asignatura: Redes Inalambricas
=============================================================================
Este script implementa EXACTAMENTE la metodologia y las formulas ensenadas
en los documentos guia del curso:

  - G1 (Fundamentos de Redes Inalambricas): FSPL(dB) = 20*log10(d) +
    20*log10(f_MHz) - 27.55   [d en metros, f en MHz]

  - G2 (Diseno y Configuracion de WLAN): Presupuesto de enlace (Link Budget)
    P_rx = P_tx + G_tx - L_tx - L_fs - L_m + G_rx - L_rx
    SOM (dB) = P_rx - Sensibilidad_receptor

Todas las variables de entrada estan expuestas al inicio de main() para que
el estudiante pueda modificarlas y recalcular. Los resultados que imprime
este script DEBEN coincidir con los que aparecen en el documento academico
y en el archivo Excel (ver Capitulo 19 del enunciado: "Consistencia entre
Python, Excel y Documento").
=============================================================================
"""

import math

# -----------------------------------------------------------------------
# 1. FUNCIONES DE FISICA DE RF (metodologia G1)
# -----------------------------------------------------------------------

def calcular_longitud_onda(frecuencia_hz):
    """
    lambda = c / f   (G1, seccion 1.1)
    Devuelve la longitud de onda en metros.
    """
    c = 300_000_000  # velocidad de la luz, m/s
    return c / frecuencia_hz


def calcular_fspl(distancia_m, frecuencia_mhz):
    """
    Perdida en el Espacio Libre (Free Space Path Loss).
    Formula exacta de G1 / G2 (Capitulo 4):
        FSPL(dB) = 20*log10(d) + 20*log10(f) - 27.55
    d: distancia en metros
    f: frecuencia en MHz
    """
    if distancia_m <= 0:
        raise ValueError("La distancia debe ser mayor que 0.")
    K = -27.55
    return round((20 * math.log10(distancia_m)) + (20 * math.log10(frecuencia_mhz)) + K, 2)


# -----------------------------------------------------------------------
# 2. FUNCIONES DE PRESUPUESTO DE ENLACE (metodologia G2, Capitulo 1.2)
# -----------------------------------------------------------------------

def calcular_rssi(p_tx, g_tx, l_tx, fspl, l_m, g_rx, l_rx):
    """
    Ecuacion maestra del Link Budget (G2):
        P_rx = P_tx + G_tx - L_tx - L_fs - L_m + G_rx - L_rx
    Todas las unidades en dB / dBm / dBi segun corresponda.
    """
    p_rx = p_tx + g_tx - l_tx - fspl - l_m + g_rx - l_rx
    return round(p_rx, 2)


def calcular_som(p_rx, sensibilidad_rx):
    """
    System Operating Margin (G2, Capitulo 4.1):
        SOM (dB) = P_rx - Sensibilidad_receptor
    """
    return round(p_rx - sensibilidad_rx, 2)


def evaluar_veredicto(som):
    """
    Criterio de ingenieria (G2): SOM > 20 dB = excelente / aprobado,
    10 dB <= SOM <= 20 dB = riesgo (funciona pero con margen ajustado),
    SOM < 10 dB = fallido / inestable.
    """
    if som < 10:
        return "FALLIDO"
    elif som < 20:
        return "RIESGO"
    else:
        return "APROBADO"


# -----------------------------------------------------------------------
# 3. PARAMETROS DEL PROYECTO (ver Tabla 1 del documento academico)
#    Los valores marcados como SUPUESTO se documentan y justifican
#    tambien en el documento academico (seccion "Supuestos Tecnicos").
# -----------------------------------------------------------------------

# Parametros de radio (comunes a los 4 AP propuestos)
P_TX = 20.0        # dBm  - Potencia de transmision tipica de AP empresarial en Colombia (G1)
G_TX = 3.0         # dBi  - Antena omnidireccional integrada (G1: rango tipico 2-5 dBi)
G_RX = 0.0         # dBi  - [SUPUESTO] antena tipica de smartphone/laptop (dispositivo "menos capaz", LCD)
L_TX = 1.0         # dB   - [SUPUESTO] perdidas de conector internas AP
L_RX = 1.0         # dB   - [SUPUESTO] perdidas en el dispositivo cliente
L_M = 10.0         # dB   - [SUPUESTO] margen de desvanecimiento interior (mobiliario, personas, clima seco -> 10 dB minimo, G2 1.2)
SENSIBILIDAD_RX = -75.0   # dBm  - [SUPUESTO] sensibilidad tipica de un AP/cliente empresarial Wi-Fi 5/6 (rango de referencia G2: -75 dBm)
RSSI_OBJETIVO_MIN = -67.0  # dBm - Umbral minimo recomendado por G2/G3 para aplicaciones en tiempo real

FRECUENCIAS = {
    "2.4 GHz (Canal 6)": 2437,   # MHz
    "5 GHz (Canal 36)": 5180,    # MHz
}

# Zonas de cobertura propuestas (ver Figura 2 del documento academico).
# distancia_max_m = distancia estimada AP -> punto mas alejado de la zona
# (semi-diagonal de la zona, ver seccion "Analisis del plano" del documento;
# etiquetado como SUPUESTO por no contarse con planos acotados en metros).
ZONAS = [
    {"ap": "AP1", "zona": "Entrada Principal + Sala Audiovisual", "area_m2": 27.28, "distancia_max_m": 3.80},
    {"ap": "AP2", "zona": "Sala de Estudio Colaborativo + Zaguan", "area_m2": 45.09, "distancia_max_m": 4.88},
    {"ap": "AP3", "zona": "Atencion/Circulacion + Deposito + Informatica + Sanitarios", "area_m2": 55.65, "distancia_max_m": 5.42},
    {"ap": "AP4", "zona": "Hemeroteca + Sala de Lectura", "area_m2": 58.85, "distancia_max_m": 5.58},
]


def tabla_distancias_referencia():
    """Reproduce la tabla comparativa 2.4 GHz vs 5 GHz del documento G1,
    adaptada a distancias tipicas de interior de biblioteca (5/10/15/20 m)."""
    distancias = [5, 10, 15, 20]
    print("\n" + "=" * 100)
    print("TABLA DE REFERENCIA: PRESUPUESTO DE ENLACE POR BANDA Y DISTANCIA")
    print("=" * 100)
    print(f"{'Distancia (m)':<15}|{'Banda':<20}|{'FSPL (dB)':<12}|{'RSSI (dBm)':<12}|{'SOM (dB)':<10}|{'Veredicto'}")
    print("-" * 100)
    for d in distancias:
        for banda, freq in FRECUENCIAS.items():
            fspl = calcular_fspl(d, freq)
            rssi = calcular_rssi(P_TX, G_TX, L_TX, fspl, L_M, G_RX, L_RX)
            som = calcular_som(rssi, SENSIBILIDAD_RX)
            veredicto = evaluar_veredicto(som)
            print(f"{d:<15}|{banda:<20}|{fspl:<12}|{rssi:<12}|{som:<10}|{veredicto}")
    print("-" * 100)


def tabla_diseno_ap():
    """Calcula el enlace real para cada AP propuesto, a la distancia maxima
    de su zona de cobertura (peor caso dentro de la zona), en 5 GHz
    (banda priorizada) y 2.4 GHz (banda de respaldo)."""
    print("\n" + "=" * 110)
    print("DISENO FINAL DE PUNTOS DE ACCESO (peor caso: usuario en el limite de cada zona)")
    print("=" * 110)
    header = f"{'AP':<5}{'Zona':<48}{'d_max(m)':<10}{'Banda':<18}{'FSPL(dB)':<10}{'RSSI(dBm)':<11}{'SOM(dB)':<9}{'Veredicto'}"
    print(header)
    print("-" * 110)
    resultados = []
    for z in ZONAS:
        for banda, freq in FRECUENCIAS.items():
            fspl = calcular_fspl(z["distancia_max_m"], freq)
            rssi = calcular_rssi(P_TX, G_TX, L_TX, fspl, L_M, G_RX, L_RX)
            som = calcular_som(rssi, SENSIBILIDAD_RX)
            veredicto = evaluar_veredicto(som)
            resultados.append({**z, "banda": banda, "fspl": fspl, "rssi": rssi, "som": som, "veredicto": veredicto})
            print(f"{z['ap']:<5}{z['zona']:<48}{z['distancia_max_m']:<10}{banda:<18}{fspl:<10}{rssi:<11}{som:<9}{veredicto}")
    print("-" * 110)
    return resultados


def main():
    print("PROYECTO: AUDITORIA Y REDISENO DE RED WI-FI - BIBLIOTECA UNIVERSITARIA")
    print(f"Longitud de onda a 2.4 GHz: {round(calcular_longitud_onda(2_400_000_000)*100,2)} cm")
    print(f"Longitud de onda a 5 GHz:   {round(calcular_longitud_onda(5_000_000_000)*100,2)} cm")

    tabla_distancias_referencia()
    resultados = tabla_diseno_ap()

    total_area = sum(z["area_m2"] for z in ZONAS)
    print(f"\nArea total cubierta por los 4 AP: {total_area:.2f} m^2 (Area total de referencia del plano: 186.87 m^2)")

    aprobados_5ghz = sum(1 for r in resultados if r["banda"].startswith("5") and r["veredicto"] == "APROBADO")
    print(f"AP con enlace APROBADO en 5 GHz (banda priorizada) en el peor caso de su zona: {aprobados_5ghz}/4")


if __name__ == "__main__":
    main()
