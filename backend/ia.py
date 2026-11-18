"""IA de NextMaint: detección de anomalías con IsolationForest (scikit-learn).

Qué hace
--------
Aprende cómo luce el funcionamiento *normal* (CPU, RAM y disco) y, para cada medición nueva,
devuelve un índice de anomalía de 0 a 100: 0 = muy normal, 100 = muy raro.
Es un aprendizaje NO supervisado: no necesita datos etiquetados, solo mediciones.

De dónde salen los datos de entrenamiento
-----------------------------------------
- Mediciones reales guardadas en la base de datos (se excluye el equipo de demostración).
- Si hay pocas, se completan con datos simulados de uso normal. La fuente queda registrada
  (reales / mixtos / simulados) y se muestra en el dashboard: no se esconde.

El modelo se reentrena solo cada NEXMAINT_REENTRENAR_MIN minutos (10 por defecto), así que
mejora a medida que los equipos acumulan mediciones. Las reglas de risk.py siguen siendo la
base: si la IA no está disponible, el sistema sigue funcionando igual.
"""
import os
import threading
import time
from datetime import datetime

from sqlalchemy import text

CARACTERISTICAS = ("cpu", "ram", "disco")
MIN_FILAS = int(os.environ.get("NEXMAINT_IA_MIN_FILAS", "2000"))  # por debajo se completa con simuladas
MAX_FILAS_REALES = 20000
REENTRENAR_SEG = int(os.environ.get("NEXMAINT_REENTRENAR_MIN", "10")) * 60
EXCLUIR = ("PC-DEMO",)

_modelo = None          # dict con el modelo y su calibración (se reemplaza completo, nunca a medias)
_estado = {"disponible": False, "entrenando": False, "error": None}
_candado = threading.Lock()


def _simuladas(n: int, semilla: int = 7):
    """Uso normal de un PC de laboratorio: CPU baja con picos, RAM y disco medios."""
    import numpy as np
    rng = np.random.default_rng(semilla)
    cpu = np.clip(rng.gamma(2.0, 10.0, n), 1, 75)
    ram = np.clip(rng.normal(52, 13, n) + 0.2 * (cpu - 20), 15, 85)
    disco = np.clip(rng.normal(55, 14, n), 15, 85)
    return np.column_stack([cpu, ram, disco])


def _leer_reales(engine):
    import numpy as np
    marcas = ", ".join(f":x{i}" for i in range(len(EXCLUIR)))
    sql = (
        "SELECT m.cpu, m.ram, m.disco FROM mediciones m JOIN equipos e ON e.id = m.equipo_id "
        f"WHERE e.nombre NOT IN ({marcas}) AND m.cpu IS NOT NULL AND m.ram IS NOT NULL "
        "AND m.disco IS NOT NULL ORDER BY m.id DESC LIMIT :lim"
    )
    params = {f"x{i}": n for i, n in enumerate(EXCLUIR)} | {"lim": MAX_FILAS_REALES}
    with engine.connect() as conn:
        filas = conn.execute(text(sql), params).all()
    return np.array(filas, dtype=float).reshape(-1, 3)


def entrenar(engine) -> dict:
    """Entrena el modelo con los datos disponibles y lo deja listo para puntuar."""
    global _modelo
    import numpy as np
    from sklearn.ensemble import IsolationForest

    with _candado:
        if _estado["entrenando"]:
            return info()
        _estado["entrenando"] = True
    try:
        reales = _leer_reales(engine)
        if len(reales) < 50:            # casi sin datos reales: se entrena solo con uso normal simulado
            X, n_real, n_sim, fuente = _simuladas(MIN_FILAS), 0, MIN_FILAS, "simulados"
        elif len(reales) < MIN_FILAS:   # pocos: se completan con simulados
            n_sim = MIN_FILAS - len(reales)
            X, n_real, fuente = np.vstack([reales, _simuladas(n_sim)]), len(reales), "mixtos"
        else:
            X, n_real, n_sim, fuente = reales, len(reales), 0, "reales"

        bosque = IsolationForest(n_estimators=150, max_samples=min(256, len(X)), random_state=42)
        bosque.fit(X)
        rareza = -bosque.score_samples(X)              # más alto = más raro
        centro = float(np.percentile(rareza, 50))      # una medición típica queda en 0
        # 100 = tan raro como un equipo al límite en todo (CPU, RAM y disco casi al 100 %)
        extremo = float(-bosque.score_samples(np.array([[98.0, 97.0, 97.0]]))[0])
        limite = max(extremo, float(np.percentile(rareza, 99.5)) + 0.01)
        _modelo = {
            "bosque": bosque, "centro": centro, "ancho": max(limite - centro, 1e-6),
            "n_reales": int(n_real), "n_simuladas": int(n_sim),
            "fuente": fuente, "entrenado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _estado.update(disponible=True, error=None)
    except Exception as e:  # la IA es opcional: si falla, el sistema sigue con las reglas
        _estado.update(disponible=_modelo is not None, error=f"{type(e).__name__}: {e}")
    finally:
        _estado["entrenando"] = False
    return info()


def puntuar(filas) -> list:
    """filas: lista de (cpu, ram, disco). Devuelve un índice 0-100 por fila (None si no hay modelo)."""
    m = _modelo
    filas = list(filas)
    if m is None or not filas:
        return [None] * len(filas)
    import numpy as np
    validas = [i for i, f in enumerate(filas) if all(v is not None for v in f)]
    salida = [None] * len(filas)
    if not validas:
        return salida
    X = np.array([filas[i] for i in validas], dtype=float)
    rareza = -m["bosque"].score_samples(X)
    pts = np.clip((rareza - m["centro"]) / m["ancho"] * 100, 0, 100)
    for i, p in zip(validas, pts):
        salida[i] = int(round(float(p)))
    return salida


def nivel(p) -> str | None:
    if p is None:
        return None
    return "alta" if p >= 70 else "moderada" if p >= 40 else "normal"


def info() -> dict:
    m = _modelo
    return {
        "disponible": m is not None,
        "entrenando": _estado["entrenando"],
        "error": _estado["error"],
        "algoritmo": "IsolationForest (scikit-learn)",
        "caracteristicas": list(CARACTERISTICAS),
        **({k: m[k] for k in ("fuente", "n_reales", "n_simuladas", "entrenado")} if m else {}),
    }


def iniciar(engine) -> None:
    """Entrena al arrancar y luego reentrena cada cierto tiempo, en segundo plano."""
    def ciclo():
        while True:
            entrenar(engine)
            time.sleep(REENTRENAR_SEG)
    threading.Thread(target=ciclo, daemon=True, name="ia-entrenamiento").start()
