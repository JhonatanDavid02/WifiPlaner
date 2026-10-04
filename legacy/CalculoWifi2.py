"""
=============================================================================
CALCULADORA DE INGENIERIA WLAN - BIBLIOTECA UNIVERSITARIA
Auditoria y Rediseno de Red Wi-Fi

Corporacion Unificada Nacional de Educacion Superior (CUN)
Asignatura: Redes Inalambricas

METODOLOGIA:
- G1: Fundamentos de Redes Inalambricas
- G2: Diseno y Configuracion de WLAN
- G3: Seguridad en Redes Inalambricas

IMPORTANTE:
Los valores marcados como SUPUESTO deben justificarse en el documento
academico. Las distancias de cada zona son estimaciones realizadas sobre
el plano de referencia y NO representan mediciones de campo.

=============================================================================
"""

import math


# ============================================================================
# 1. FUNCIONES DE FISICA DE RF - G1
# ============================================================================

def calcular_longitud_onda(frecuencia_hz):
    """
    Longitud de onda:
        lambda = c / f

    Retorna la longitud de onda en metros.
    """
    c = 300_000_000  # m/s
    return c / frecuencia_hz


def calcular_fspl(distancia_m, frecuencia_mhz):
    """
    Perdida en el Espacio Libre (FSPL).

    Formula utilizada en G1/G2:

        FSPL(dB) =
        20*log10(d) + 20*log10(f_MHz) - 27.55

    d = distancia en metros
    f = frecuencia en MHz
    """

    if distancia_m <= 0:
        raise ValueError("La distancia debe ser mayor que 0.")

    if frecuencia_mhz <= 0:
        raise ValueError("La frecuencia debe ser mayor que 0.")

    return round(
        (20 * math.log10(distancia_m))
        + (20 * math.log10(frecuencia_mhz))
        - 27.55,
        2
    )


# ============================================================================
# 2. PRESUPUESTO DE ENLACE - G2
# ============================================================================

def calcular_rssi(
    p_tx,
    g_tx,
    l_tx,
    fspl,
    l_m,
    g_rx,
    l_rx
):
    """
    Presupuesto de enlace:

        P_rx = P_tx + G_tx - L_tx - FSPL - L_m + G_rx - L_rx

    Retorna la potencia recibida estimada en dBm.
    """

    p_rx = (
        p_tx
        + g_tx
        - l_tx
        - fspl
        - l_m
        + g_rx
        - l_rx
    )

    return round(p_rx, 2)


def calcular_som(p_rx, sensibilidad_rx):
    """
    System Operating Margin:

        SOM = P_rx - Sensibilidad del receptor

    Retorna el margen del sistema en dB.
    """

    return round(p_rx - sensibilidad_rx, 2)


# ============================================================================
# 3. EVALUACION DEL RSSI - G1
# ============================================================================

def evaluar_rssi(rssi, objetivo=-67.0):
    """
    G1 establece -67 dBm como referencia minima para aplicaciones
    de voz o datos en tiempo real.

    Se utiliza:
        RSSI >= -67 dBm -> CUMPLE
        RSSI <  -67 dBm -> NO CUMPLE
    """

    if rssi >= objetivo:
        return "CUMPLE"

    return "NO CUMPLE"


# ============================================================================
# 4. EVALUACION DEL SOM - G2
# ============================================================================

def evaluar_som(som, criterio_som):
    """
    Evaluacion del SOM segun el criterio seleccionado.

    G2 utiliza como referencia:
        - SOM > 10 dB: margen recomendado en condiciones secas.
        - SOM > 20 dB: criterio mas conservador para condiciones lluviosas.

    El limite se recibe como parametro para evitar tratar 20 dB como
    una exigencia universal para cualquier escenario.
    """

    if som > criterio_som:
        return "APROBADO"

    elif som >= 10:
        return "RIESGO"

    else:
        return "FALLIDO"


# ============================================================================
# 5. PARAMETROS DEL PROYECTO
# ============================================================================

# -------------------------
# Parametros de radio
# -------------------------

P_TX = 20.0
# dBm
# SUPUESTO: potencia de transmision de referencia.

G_TX = 3.0
# dBi
# G1: antenas omnidireccionales tipicas aproximadamente entre 2 y 5 dBi.

G_RX = 0.0
# dBi
# SUPUESTO conservador para representar un dispositivo cliente de menor
# capacidad de antena.

L_TX = 1.0
# dB
# SUPUESTO: perdida interna/conectores del transmisor.

L_RX = 1.0
# dB
# SUPUESTO: perdida del lado del receptor.

L_M = 10.0
# dB
# SUPUESTO: margen de desvanecimiento para entorno interior.
# G2 plantea un margen de referencia de 10-20 dB.

SENSIBILIDAD_RX = -75.0
# dBm
# SUPUESTO de referencia para el receptor.
# Debe sustituirse por la sensibilidad de un equipo concreto si se dispone
# de su hoja tecnica.


# -------------------------
# Objetivo de RSSI
# -------------------------

RSSI_OBJETIVO_MIN = -67.0
# dBm
# Referencia de G1 para aplicaciones de voz/datos en tiempo real.


# -------------------------
# Criterios SOM
# -------------------------

SOM_MIN_SECO = 10.0
# dB
# Referencia de G2 para condiciones secas.

SOM_MIN_LLUVIA = 20.0
# dB
# Referencia conservadora de G2 para zonas lluviosas.


# -------------------------
# Frecuencias
# -------------------------

FRECUENCIAS = {
    "2.4 GHz (Canal 6)": 2437,
    "5 GHz (Canal 36)": 5180,
}


# ============================================================================
# 6. ZONAS DE COBERTURA
# ============================================================================

ZONAS = [
    {
        "ap": "AP1",
        "zona": "Entrada Principal + Sala Audiovisual",
        "area_m2": 27.28,
        "distancia_max_m": 3.80
    },

    {
        "ap": "AP2",
        "zona": "Sala de Estudio Colaborativo + Zaguan",
        "area_m2": 45.09,
        "distancia_max_m": 4.88
    },

    {
        "ap": "AP3",
        "zona": "Atencion/Circulacion + Deposito + Informatica + Sanitarios",
        "area_m2": 55.65,
        "distancia_max_m": 5.42
    },

    {
        "ap": "AP4",
        "zona": "Hemeroteca + Sala de Lectura",
        "area_m2": 58.85,
        "distancia_max_m": 5.58
    },
]


# ============================================================================
# 7. TABLA DE REFERENCIA
# ============================================================================

def tabla_distancias_referencia():

    distancias = [5, 10, 15, 20]

    print("\n" + "=" * 120)
    print("TABLA DE REFERENCIA: PRESUPUESTO DE ENLACE POR BANDA Y DISTANCIA")
    print("=" * 120)

    print(
        f"{'Distancia (m)':<15}"
        f"{'Banda':<20}"
        f"{'FSPL (dB)':<12}"
        f"{'RSSI (dBm)':<13}"
        f"{'SOM (dB)':<10}"
        f"{'RSSI':<12}"
        f"{'SOM >10':<12}"
        f"{'SOM >20'}"
    )

    print("-" * 120)

    for d in distancias:

        for banda, frecuencia in FRECUENCIAS.items():

            fspl = calcular_fspl(d, frecuencia)

            rssi = calcular_rssi(
                P_TX,
                G_TX,
                L_TX,
                fspl,
                L_M,
                G_RX,
                L_RX
            )

            som = calcular_som(
                rssi,
                SENSIBILIDAD_RX
            )

            rssi_veredicto = evaluar_rssi(
                rssi,
                RSSI_OBJETIVO_MIN
            )

            som_seco = evaluar_som(
                som,
                SOM_MIN_SECO
            )

            som_lluvia = evaluar_som(
                som,
                SOM_MIN_LLUVIA
            )

            print(
                f"{d:<15}"
                f"{banda:<20}"
                f"{fspl:<12}"
                f"{rssi:<13}"
                f"{som:<10}"
                f"{rssi_veredicto:<12}"
                f"{som_seco:<12}"
                f"{som_lluvia}"
            )

    print("-" * 120)


# ============================================================================
# 8. DISEÑO FINAL DE AP
# ============================================================================

def tabla_diseno_ap():

    print("\n" + "=" * 145)
    print("DISENO FINAL DE PUNTOS DE ACCESO")
    print("Peor caso: usuario ubicado en el limite estimado de cada zona")
    print("=" * 145)

    header = (
        f"{'AP':<5}"
        f"{'Zona':<48}"
        f"{'d_max(m)':<10}"
        f"{'Banda':<18}"
        f"{'FSPL':<10}"
        f"{'RSSI':<11}"
        f"{'SOM':<9}"
        f"{'RSSI -67':<12}"
        f"{'SOM >10':<12}"
        f"{'SOM >20':<12}"
    )

    print(header)
    print("-" * 145)

    resultados = []

    for zona in ZONAS:

        for banda, frecuencia in FRECUENCIAS.items():

            fspl = calcular_fspl(
                zona["distancia_max_m"],
                frecuencia
            )

            rssi = calcular_rssi(
                P_TX,
                G_TX,
                L_TX,
                fspl,
                L_M,
                G_RX,
                L_RX
            )

            som = calcular_som(
                rssi,
                SENSIBILIDAD_RX
            )

            rssi_veredicto = evaluar_rssi(
                rssi,
                RSSI_OBJETIVO_MIN
            )

            som_seco = evaluar_som(
                som,
                SOM_MIN_SECO
            )

            som_lluvia = evaluar_som(
                som,
                SOM_MIN_LLUVIA
            )

            resultado = {
                **zona,
                "banda": banda,
                "fspl": fspl,
                "rssi": rssi,
                "som": som,
                "rssi_veredicto": rssi_veredicto,
                "som_seco": som_seco,
                "som_lluvia": som_lluvia
            }

            resultados.append(resultado)

            print(
                f"{zona['ap']:<5}"
                f"{zona['zona']:<48}"
                f"{zona['distancia_max_m']:<10.2f}"
                f"{banda:<18}"
                f"{fspl:<10.2f}"
                f"{rssi:<11.2f}"
                f"{som:<9.2f}"
                f"{rssi_veredicto:<12}"
                f"{som_seco:<12}"
                f"{som_lluvia:<12}"
            )

    print("-" * 145)

    return resultados


# ============================================================================
# 9. RESUMEN DEL PROYECTO
# ============================================================================

def resumen_proyecto(resultados):

    total_area = sum(
        zona["area_m2"]
        for zona in ZONAS
    )

    resultados_5ghz = [
        r for r in resultados
        if r["banda"].startswith("5")
    ]

    rssi_ok = sum(
        1 for r in resultados_5ghz
        if r["rssi_veredicto"] == "CUMPLE"
    )

    som_seco_ok = sum(
        1 for r in resultados_5ghz
        if r["som_seco"] == "APROBADO"
    )

    som_lluvia_ok = sum(
        1 for r in resultados_5ghz
        if r["som_lluvia"] == "APROBADO"
    )

    print("\n" + "=" * 80)
    print("RESUMEN DEL DISENO")
    print("=" * 80)

    print(
        f"Area total de referencia cubierta: "
        f"{total_area:.2f} m²"
    )

    print(
        "Area total de referencia del plano: "
        "186.87 m²"
    )

    print(
        f"AP propuestos: {len(ZONAS)}"
    )

    print(
        f"AP evaluados en 5 GHz: "
        f"{len(resultados_5ghz)}"
    )

    print(
        f"Enlaces 5 GHz que cumplen RSSI >= -67 dBm: "
        f"{rssi_ok}/{len(resultados_5ghz)}"
    )

    print(
        f"Enlaces 5 GHz con SOM > 10 dB: "
        f"{som_seco_ok}/{len(resultados_5ghz)}"
    )

    print(
        f"Enlaces 5 GHz con SOM > 20 dB: "
        f"{som_lluvia_ok}/{len(resultados_5ghz)}"
    )

    print("=" * 80)


# ============================================================================
# 10. PROGRAMA PRINCIPAL
# ============================================================================

def main():

    print("=" * 80)
    print("PROYECTO: AUDITORIA Y REDISENO DE RED WI-FI")
    print("BIBLIOTECA UNIVERSITARIA")
    print("=" * 80)

    longitud_24 = calcular_longitud_onda(
        2_400_000_000
    ) * 100

    longitud_5 = calcular_longitud_onda(
        5_000_000_000
    ) * 100

    print(
        f"\nLongitud de onda a 2.4 GHz: "
        f"{longitud_24:.2f} cm"
    )

    print(
        f"Longitud de onda a 5 GHz: "
        f"{longitud_5:.2f} cm"
    )

    tabla_distancias_referencia()

    resultados = tabla_diseno_ap()

    resumen_proyecto(resultados)


# ============================================================================
# EJECUCION
# ============================================================================

if __name__ == "__main__":
    main()

