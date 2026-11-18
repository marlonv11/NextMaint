"""Asistente de NextMaint: responde preguntas básicas con los datos reales de los equipos.

No es un modelo de lenguaje: entiende la pregunta por palabras clave (intenciones) y arma la
respuesta con lo que el sistema ya sabe — mediciones, reglas de riesgo, procesos que más
consumen y el índice de anomalía de la IA. Así funciona sin internet, sin costo y sin inventar
datos. Cada afirmación sale de una medición; las causas se ordenan por la evidencia disponible
(cualitativa: "muy probable", "probable", "posible"), no con porcentajes inventados.
"""
import re
import unicodedata

METRICAS = {
    "ram": (r"\b(ram|memoria)\b", "RAM"),
    "cpu": (r"\b(cpu|procesador)\b", "CPU"),
    "disco": (r"\b(disco|almacenamiento|espacio)\b", "disco"),
    "temperatura": (r"\b(temperatura|temp|calor|caliente|calienta|calentando|sobrecalent\w*)\b", "temperatura"),
}
RANGO = {"alto": 3, "medio": 2, "bajo": 1}
SUGERENCIAS = ["¿Cuál equipo está peor?", "Resumen del laboratorio", "¿Por qué está alta la RAM?", "¿Cómo funciona la IA?"]


def _n(texto: str) -> str:
    """Minúsculas, sin tildes y sin signos: para comparar palabras sin importar cómo se escriban."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _tiene(q: str, patron: str) -> bool:
    return re.search(patron, q) is not None


def _dur(seg) -> str:
    if seg is None:
        return "un tiempo desconocido"
    if seg < 60:
        return f"{seg} s"
    if seg < 3600:
        return f"{seg // 60} min"
    if seg < 86400:
        return f"{seg // 3600} h"
    return f"{seg // 86400} d"


def _mem(mb: float) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def _uso(v: float) -> str:
    return "crítico" if v >= 90 else "elevado" if v >= 75 else "normal"


def _buscar_equipo(q: str, equipos: list[dict]):
    """Encuentra el equipo mencionado: 'PC-03', 'pc 3' y 'pc03' apuntan al mismo equipo."""
    for e in sorted(equipos, key=lambda e: -len(e["nombre"])):
        partes = re.findall(r"[a-z]+|[0-9]+", _n(e["nombre"]))
        if not partes:
            continue
        patron = r"\s*".join(("0*" + str(int(p))) if p.isdigit() else re.escape(p) for p in partes)
        if re.search(rf"(?<![a-z0-9]){patron}(?![a-z0-9])", q):
            return e
    return None


def _peor(equipos: list[dict]):
    vivos = [e for e in equipos if e.get("conectado") and e.get("cpu") is not None]
    if not vivos:
        return None
    return max(vivos, key=lambda e: (RANGO.get(e["nivel"], 1), e.get("score", 0), e.get("anomalia") or 0, e["cpu"] + e["ram"] + e["disco"]))


def _linea_ia(e: dict) -> str:
    a = e.get("anomalia")
    if a is None:
        return "IA: el modelo todavía se está entrenando, vuelve a preguntar en unos segundos."
    base = f"Índice de anomalía de la IA: {a}/100 ({e['anomalia_nivel']})."
    if a >= 70 and e["nivel"] == "bajo":
        return base + " Ojo: las reglas lo ven normal, pero la combinación de CPU, RAM y disco se aleja mucho de lo habitual."
    if a >= 70:
        return base + " La combinación de CPU, RAM y disco se aleja mucho de lo habitual: coincide con las reglas."
    if a < 40 and e["nivel"] == "alto":
        return base + " Las reglas marcan riesgo por umbrales, aunque el patrón no es raro para la IA."
    if a < 40:
        return base + " El comportamiento es el esperado."
    return base + " Hay señales de desvío, conviene vigilarlo."


def _procesos(e: dict, clave: str) -> list[dict]:
    return sorted((p for p in e.get("procesos") or [] if p.get(clave, 0) > 0), key=lambda p: -p[clave])


def _fuera_de_linea(e: dict) -> str:
    return (f"{e['nombre']} está sin conexión: no envía datos hace {_dur(e.get('segundos_sin_datos'))}.\n"
            "• Revisa que el equipo esté encendido y conectado a la red.\n"
            "• Comprueba que el agente (NextMaintAgent) siga abierto.")


def _explicar_metrica(e: dict, k: str) -> tuple[str, bool]:
    """Texto sobre por qué una métrica está alta en un equipo. Devuelve (texto, hubo_evidencia)."""
    nombre = METRICAS[k][1]
    if not e.get("conectado"):
        return _fuera_de_linea(e), False
    if k == "temperatura":
        if e.get("temp_estimada"):
            return (f"La temperatura de {e['nombre']} es estimada (el equipo no tiene un sensor que podamos leer) "
                    f"y se calcula a partir de la CPU, que está en {e['cpu']:.0f} %. No cuenta para el riesgo, "
                    "así que no puedo darte un diagnóstico térmico fiable de este equipo.", False)
        v, umbral = e["temperatura"], (80, 65)
        estado = "crítica" if v >= umbral[0] else "elevada" if v >= umbral[1] else "normal"
        cab = f"{e['nombre']} — temperatura: {v:.0f} °C → {estado}."
        if estado == "normal":
            return cab + "\nEstá dentro de lo normal, no es la causa del riesgo.", False
        return (cab + "\nCausas probables (de más a menos probable):\n"
                f"• Probable: ventiladores o disipador con polvo, o poca ventilación.\n"
                f"• Posible: carga alta sostenida (CPU en {e['cpu']:.0f} %).\n"
                "• Posible: temperatura ambiente alta en el laboratorio.\n"
                "Qué hacer: limpiar el equipo por dentro, revisar los ventiladores y no bloquear las rejillas.", False)

    v = e[k]
    cab = f"{e['nombre']} — {nombre}: {v:.0f} % → uso {_uso(v)}."
    if v < 75:
        extra = f"\nEl riesgo de este equipo viene de otra parte: {e['mensaje']}" if e["nivel"] != "bajo" else ""
        return cab + "\nEstá dentro de lo normal, no es la causa del riesgo." + extra, False

    causas, acciones, evidencia = [], [], False
    if k == "ram":
        top = _procesos(e, "ram_mb")
        if top and top[0]["ram_mb"] >= 300:
            evidencia = True
            causas.append(f"Muy probable: {top[0]['nombre']} usa {_mem(top[0]['ram_mb'])} de memoria.")
            if len(top) > 1:
                causas.append(f"Probable: también pesan {top[1]['nombre']} ({_mem(top[1]['ram_mb'])}).")
        elif not e.get("procesos"):
            causas.append("No tengo la lista de procesos de este equipo (el agente es una versión anterior).")
        up = e.get("uptime_segundos")
        if up is not None and up >= 7 * 86400:
            evidencia = True
            causas.append(f"Probable: lleva {_dur(up)} encendido sin reiniciar; las fugas de memoria se acumulan con el tiempo.")
        causas.append("Posible: muchas aplicaciones o pestañas abiertas a la vez.")
        acciones = ["Cerrar los programas que no se usan" + (f" (empezando por {top[0]['nombre']})" if evidencia and top else "") + ".",
                    "Reiniciar el equipo si lleva mucho tiempo encendido."]
    elif k == "cpu":
        top = _procesos(e, "cpu")
        if top and top[0]["cpu"] >= 15:
            evidencia = True
            causas.append(f"Muy probable: {top[0]['nombre']} consume {top[0]['cpu']:.0f} % de CPU.")
            if len(top) > 1 and top[1]["cpu"] >= 10:
                causas.append(f"Probable: {top[1]['nombre']} aporta {top[1]['cpu']:.0f} %.")
        elif not e.get("procesos"):
            causas.append("No tengo la lista de procesos de este equipo (el agente es una versión anterior).")
        causas.append("Posible: tareas en segundo plano (actualizaciones, antivirus, indexado).")
        causas.append("Posible: un programa bloqueado en bucle.")
        acciones = ["Abrir el administrador de tareas y cerrar el proceso que más consume.",
                    "Si la CPU sigue alta con todo cerrado, programar una revisión del equipo."]
    else:  # disco
        libre = e.get("espacio_libre")
        if libre is not None:
            evidencia = True
            causas.append(f"Dato: quedan {libre:.0f} GB libres.")
        causas.append("Probable: archivos temporales, descargas y papelera acumulados.")
        causas.append("Posible: copias de actualizaciones del sistema o programas instalados que ya no se usan.")
        acciones = ["Vaciar la papelera, descargas y archivos temporales.", "Desinstalar programas que no se usan."]

    texto = (cab + "\nCausas probables (de más a menos probable):\n" + "\n".join("• " + c for c in causas)
             + "\nQué hacer:\n" + "\n".join("• " + a for a in acciones)
             + f"\nConfianza del diagnóstico: {'alta (hay datos del equipo que lo respaldan)' if evidencia else 'media (causas generales, sin datos específicos)'}.")
    return texto, evidencia


def _explicar_equipo(e: dict) -> str:
    if not e.get("conectado"):
        return _fuera_de_linea(e)
    if e.get("cpu") is None:
        return f"{e['nombre']} todavía no ha enviado mediciones."
    altos = [f"{n} {e[k]:.0f} % ({_uso(e[k])})" for k, (_, n) in METRICAS.items() if k != "temperatura" and e[k] >= 75]
    if not e.get("temp_estimada") and e["temperatura"] >= 65:
        altos.append(f"temperatura {e['temperatura']:.0f} °C")
    lineas = [f"{e['nombre']} — riesgo {e['nivel']} (puntaje {e['score']})."]
    lineas.append(("Lo que sube el riesgo: " + ", ".join(altos) + ".") if altos else "Todas las métricas están dentro de lo normal.")
    if e["nivel"] != "bajo":
        lineas.append("Recomendación: " + e["recomendacion"])
    top = _procesos(e, "ram_mb")
    if altos and top:
        lineas.append(f"Proceso que más memoria usa: {top[0]['nombre']} ({_mem(top[0]['ram_mb'])}).")
    lineas.append(_linea_ia(e))
    return "\n".join(lineas)


def _ranking(equipos: list[dict]) -> str:
    vivos = [e for e in equipos if e.get("conectado") and e.get("cpu") is not None]
    if not vivos:
        return "Ningún equipo está enviando datos ahora mismo."
    orden = sorted(vivos, key=lambda e: (-RANGO.get(e["nivel"], 1), -e.get("score", 0), -(e.get("anomalia") or 0)))[:3]
    lineas = ["Los equipos con más atención hoy:"]
    for i, e in enumerate(orden, 1):
        ia = f" · IA {e['anomalia']}/100" if e.get("anomalia") is not None else ""
        lineas.append(f"{i}. {e['nombre']} — riesgo {e['nivel']} · CPU {e['cpu']:.0f} % · RAM {e['ram']:.0f} % · disco {e['disco']:.0f} %{ia}")
    if all(e["nivel"] == "bajo" for e in orden):
        lineas.append("Todos están en riesgo bajo: no hay nada urgente.")
    return "\n".join(lineas)


def _resumen(equipos: list[dict], alertas: list[dict]) -> str:
    if not equipos:
        return "Aún no hay equipos registrados. Inicia el agente en un PC y aparecerá aquí."
    vivos = [e for e in equipos if e.get("conectado")]
    off = [e["nombre"] for e in equipos if not e.get("conectado")]
    c = {n: sum(1 for e in vivos if e["nivel"] == n) for n in ("alto", "medio", "bajo")}
    lineas = [f"Laboratorio: {len(equipos)} equipos, {len(vivos)} conectados.",
              f"• Riesgo alto: {c['alto']} · medio: {c['medio']} · bajo: {c['bajo']}"]
    if off:
        lineas.append("• Sin conexión: " + ", ".join(off))
    lineas.append(f"• Alertas activas: {len(alertas)}")
    p = _peor(equipos)
    if p and p["nivel"] != "bajo":
        lineas.append(f"El más delicado: {p['nombre']} (riesgo {p['nivel']}).")
    elif vivos:
        lineas.append("Todo funciona con normalidad.")
    return "\n".join(lineas)


def _sin_conexion(equipos: list[dict]) -> str:
    off = [e for e in equipos if not e.get("conectado")]
    if not off:
        return "Todos los equipos están enviando datos."
    return "Equipos sin conexión:\n" + "\n".join(f"• {e['nombre']} — sin datos hace {_dur(e.get('segundos_sin_datos'))}" for e in off) \
        + "\nRevisa que estén encendidos, en la red y con el agente abierto."


def _alertas(alertas: list[dict]) -> str:
    if not alertas:
        return "No hay alertas activas."
    return f"Alertas activas ({len(alertas)}):\n" + "\n".join(f"• {a['equipo']} — riesgo {a['riesgo']}: {a['mensaje']}" for a in alertas[:5])


def _explicar_ia(info: dict) -> str:
    base = ("La IA es un modelo IsolationForest (aprendizaje automático no supervisado). Aprende cómo se ve el funcionamiento "
            "normal de CPU, RAM y disco, y da a cada equipo un índice de anomalía de 0 a 100: cuanto más alto, más raro es "
            "su comportamiento frente a lo habitual. Complementa las reglas: las reglas avisan por umbrales fijos; la IA detecta "
            "combinaciones raras aunque ningún número pase el umbral.")
    if not info.get("disponible"):
        return base + "\nEn este momento el modelo se está entrenando."
    fuente = {"reales": "mediciones reales", "mixtos": "mediciones reales completadas con datos simulados",
              "simulados": "datos simulados de uso normal, porque aún no hay suficientes mediciones reales"}[info["fuente"]]
    return (base + f"\nSe entrenó con {fuente} ({info['n_reales']} reales y {info['n_simuladas']} simuladas) el {info['entrenado']} "
            "y se reentrena solo a medida que llegan datos. El índice no es una probabilidad exacta: mide qué tan atípico es el equipo.")


AYUDA = ("Soy el asistente de NextMaint. Respondo con los datos reales de tus equipos. Prueba preguntarme:\n"
         "• ¿Cuál equipo está peor?\n• ¿Por qué está alta la RAM de PC-03?\n• ¿Qué hago con PC-03?\n"
         "• Resumen del laboratorio\n• ¿Qué equipos están sin conexión?\n• ¿Cómo funciona la IA?")


def responder(pregunta: str, equipos: list[dict], alertas: list[dict], info_ia: dict) -> dict:
    q = _n(pregunta)
    e = _buscar_equipo(q, equipos)
    metrica = next((k for k, (pat, _) in METRICAS.items() if _tiene(q, pat)), None)
    quiere_accion = _tiene(q, r"\b(que hago|que hacer|recomend\w*|solucion\w*|arreglar|resolver|mantenimiento|como lo)\b")

    def salir(texto: str, equipo: str | None = None) -> dict:
        sug = [f"¿Por qué {e2['nombre']} tiene ese riesgo?" for e2 in [_peor(equipos)] if e2 and e2["nivel"] != "bajo"] + SUGERENCIAS
        return {"respuesta": texto, "equipo": equipo, "sugerencias": list(dict.fromkeys(sug))[:4]}

    if not q:
        return salir(AYUDA)
    if _tiene(q, r"\b(gracias|thanks|genial|perfecto)\b"):
        return salir("¡Con gusto! Si quieres, pregúntame por otro equipo o por el resumen del laboratorio.")
    if _tiene(q, r"\b(hola|buenas|buenos dias|buenas tardes|hey|ayuda|help|que puedes|que sabes|que haces)\b") and not metrica and not e:
        return salir(AYUDA)
    if _tiene(q, r"\b(ia|inteligencia|anomalia\w*|modelo|isolation\w*|machine learning|aprendizaje|algoritmo)\b") and not e:
        return salir(_explicar_ia(info_ia))
    if _tiene(q, r"\b(sin conexion|offline|desconectad\w*|apagad\w*|no responde\w*|no reporta\w*|sin datos)\b") and not e:
        return salir(_sin_conexion(equipos))
    if _tiene(q, r"\balertas?\b") and not e:
        return salir(_alertas(alertas))

    if metrica:
        objetivo = e
        nota = ""
        if objetivo is None:
            vivos = [x for x in equipos if x.get("conectado") and x.get("cpu") is not None]
            clave = "temperatura" if metrica == "temperatura" else metrica
            if not vivos:
                return salir("Ningún equipo está enviando datos ahora mismo, así que no puedo medir eso.")
            objetivo = max(vivos, key=lambda x: x[clave])
            nota = f"(Hablo de {objetivo['nombre']}, el equipo con más {METRICAS[metrica][1]}. Si te refieres a otro, menciona su nombre.)\n"
        texto, _ = _explicar_metrica(objetivo, metrica)
        return salir(nota + texto + "\n" + _linea_ia(objetivo) if objetivo.get("conectado") and objetivo.get("cpu") is not None else nota + texto,
                     objetivo["nombre"])

    if e is not None:
        if quiere_accion and e.get("conectado") and e.get("cpu") is not None:
            return salir(f"Para {e['nombre']} (riesgo {e['nivel']}): {e['recomendacion']}\n" + _linea_ia(e), e["nombre"])
        return salir(_explicar_equipo(e), e["nombre"])

    if quiere_accion:
        p = _peor(equipos)
        if p is None:
            return salir("Ningún equipo está enviando datos ahora mismo.")
        return salir(f"El que más lo necesita es {p['nombre']} (riesgo {p['nivel']}): {p['recomendacion']}\n" + _linea_ia(p), p["nombre"])
    if _tiene(q, r"\b(peor|critico\w*|urgente|problema\w*|mal|riesgo|atencion|cargado|lento)\b"):
        return salir(_ranking(equipos))
    if _tiene(q, r"\b(resumen|estado|como esta\w*|como va\w*|laboratorio|cuantos|general|todos)\b"):
        return salir(_resumen(equipos, alertas))
    return salir("No estoy seguro de haber entendido. " + AYUDA)
