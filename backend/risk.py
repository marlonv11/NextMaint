"""Evaluación de riesgo por reglas (línea base antes del modelo de ML)."""


def _puntos(valor: float, medio: float, alto: float) -> int:
    if valor >= alto:
        return 2
    if valor >= medio:
        return 1
    return 0


def _puntos(valor: float, medio: float, alto: float) -> int:
    if valor >= alto:
        return 2
    if valor >= medio:
        return 1
    return 0


def evaluar(
    cpu: float,
    ram: float,
    disco: float,
    temperatura: float,
    temp_estimada: bool = False,
) -> dict:
    """Devuelve nivel (bajo/medio/alto), mensaje y recomendación."""
    factores = {
        "CPU": _puntos(cpu, 75, 90),
        "RAM": _puntos(ram, 75, 90),
        "disco": _puntos(disco, 75, 90),
    }

    if not temp_estimada:
        factores["temperatura"] = _puntos(temperatura, 65, 80)

    score = sum(factores.values())
    temperatura_critica = not temp_estimada and temperatura >= 85

    if score >= 6 or temperatura_critica:
        nivel = "alto"
    elif score >= 3:
        nivel = "medio"
    else:
        nivel = "bajo"

    criticos = [k for k, v in factores.items() if v == 2]
    elevados = [k for k, v in factores.items() if v >= 1]

    if nivel == "bajo":
        mensaje = "Funcionamiento normal."
        recomendacion = "Sin acciones necesarias."
    else:
        lista = criticos if criticos else elevados
        mensaje = "Se detecta consumo elevado de " + ", ".join(lista) + "."

        if nivel == "alto":
            recomendacion = "Realizar mantenimiento preventivo."
        else:
            recomendacion = "Programar revisión y monitorear la evolución del equipo."

        if "temperatura" in elevados:
            recomendacion += " Revisar la refrigeración, los ventiladores y la limpieza interna."
        if "disco" in elevados:
            recomendacion += " Liberar espacio en disco."

    return {
        "nivel": nivel,
        "score": score,
        "mensaje": mensaje,
        "recomendacion": recomendacion,
    }
