import os
import random
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import risk
from .db import ZONA, ahora, asegurar_equipo, borrar_equipo, engine, init_db, limpiar_antiguas

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# Seguridad (opcional): si las variables no existen, todo queda abierto como antes.
#   NEXMAINT_KEY      -> clave que deben enviar los agentes (cabecera X-API-Key)
#   NEXMAINT_PASSWORD -> contraseña para ver el dashboard (el usuario puede ser cualquiera)
API_KEY = os.environ.get("NEXMAINT_KEY", "")
VIEW_PASSWORD = os.environ.get("NEXMAINT_PASSWORD", "")
basic = HTTPBasic(auto_error=False)

# Un equipo que lleva más de este tiempo sin enviar datos se muestra como "Sin conexión".
OFFLINE_SEG = int(os.environ.get("NEXMAINT_OFFLINE_SEG", "30"))
# Botón "Simular fallo" del dashboard. Ponlo en 0 cuando el sistema quede en uso real.
DEMO_ACTIVA = os.environ.get("NEXMAINT_DEMO", "1") != "0"
NOMBRE_DEMO = "PC-DEMO"


def _iguales(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def exigir_clave_agente(x_api_key: str = Header(default="")) -> None:
    if API_KEY and not _iguales(x_api_key, API_KEY):
        raise HTTPException(401, "Clave de agente inválida")


def exigir_contrasena(creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
    if VIEW_PASSWORD and (creds is None or not _iguales(creds.password, VIEW_PASSWORD)):
        raise HTTPException(401, "Se requiere contraseña", headers={"WWW-Authenticate": 'Basic realm="NexMaint"'})


app = FastAPI(title="NexMaint")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")  # css/ y js/
init_db()


class Medicion(BaseModel):
    equipo: str = Field(min_length=1, max_length=64)
    cpu: float = Field(ge=0, le=100)
    ram: float = Field(ge=0, le=100)
    disco: float = Field(ge=0, le=100)
    temperatura: float = Field(ge=-20, le=150)
    espacio_libre: float = Field(default=0, ge=0, le=100000)
    # True si el equipo no tiene sensor legible y la temperatura se calculó a partir de la CPU
    temperatura_estimada: bool = False
    uptime_segundos: int | None = Field(default=None, ge=0, le=2_147_483_647)


def _conexion(fecha: str | None) -> tuple[bool, int | None]:
    """(conectado, segundos desde la última medición) según la hora del servidor."""
    if not fecha:
        return False, None
    try:
        t = datetime.strptime(fecha, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZONA)
    except ValueError:
        return False, None
    seg = max(0, int((datetime.now(ZONA) - t).total_seconds()))
    return seg <= OFFLINE_SEG, seg


def registrar_medicion(m: Medicion) -> dict:
    """Guarda una medición, evalúa el riesgo y crea la alerta si el nivel cambió."""
    resultado = risk.evaluar(m.cpu, m.ram, m.disco, m.temperatura, m.temperatura_estimada)
    asegurar_equipo(m.equipo)
    fecha = ahora()
    with engine.begin() as conn:
        equipo = conn.execute(
            text("SELECT id, estado FROM equipos WHERE nombre = :n"), {"n": m.equipo}
        ).one()
        conn.execute(
            text(
                "INSERT INTO mediciones "
                "(equipo_id, cpu, ram, disco, temperatura, espacio_libre, fecha, temp_estimada, uptime_segundos) "
                "VALUES (:eq, :cpu, :ram, :disco, :temp, :libre, :fecha, :est, :uptime)"
            ),
            {"eq": equipo.id, "cpu": m.cpu, "ram": m.ram, "disco": m.disco, "temp": m.temperatura,
             "libre": m.espacio_libre, "fecha": fecha, "est": m.temperatura_estimada, "uptime": m.uptime_segundos},
        )
        # Alerta solo cuando el riesgo cambia a medio/alto (evita duplicados)
        if resultado["nivel"] != "bajo" and resultado["nivel"] != equipo.estado:
            conn.execute(
                text(
                    "INSERT INTO alertas (equipo_id, riesgo, mensaje, fecha, estado) "
                    "VALUES (:eq, :r, :msg, :fecha, 'activa')"
                ),
                {"eq": equipo.id, "r": resultado["nivel"], "fecha": fecha,
                 "msg": f'{resultado["mensaje"]} {resultado["recomendacion"]}'},
            )
        conn.execute(
            text("UPDATE equipos SET estado = :e WHERE id = :id"),
            {"e": resultado["nivel"], "id": equipo.id},
        )
        if random.random() < 0.002:  # mantenimiento ocasional de la base de datos
            limpiar_antiguas(conn)
    return {"equipo": m.equipo, **resultado}


@app.get("/healthz")
def salud():
    """Sin contraseña: Render lo usa para saber si el servidor está vivo."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


@app.post("/api/mediciones", dependencies=[Depends(exigir_clave_agente)])
def recibir_medicion(m: Medicion):
    return registrar_medicion(m)


def _con_estado(d: dict) -> dict:
    """Agrega riesgo y conexión a una fila con la última medición de un equipo."""
    d["temp_estimada"] = bool(d.get("temp_estimada"))
    d["conectado"], d["segundos_sin_datos"] = _conexion(d.get("fecha"))
    if d.get("cpu") is not None:
        d.update(risk.evaluar(d["cpu"], d["ram"], d["disco"], d["temperatura"], d["temp_estimada"]))
    else:
        d.update({"nivel": "bajo", "score": 0, "mensaje": "Sin datos.", "recomendacion": ""})
    return d


@app.get("/api/equipos", dependencies=[Depends(exigir_contrasena)])
def listar_equipos():
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                """
                SELECT e.id, e.nombre, e.ubicacion, m.cpu, m.ram, m.disco, m.temperatura,
                       m.espacio_libre, m.fecha, m.temp_estimada, m.uptime_segundos
                FROM equipos e
                LEFT JOIN mediciones m ON m.id = (
                    SELECT id FROM mediciones WHERE equipo_id = e.id ORDER BY id DESC LIMIT 1
                )
                ORDER BY e.nombre
                """
            )
        ).mappings().all()
    return [_con_estado(dict(f)) for f in filas]


@app.get("/api/equipos/{nombre}", dependencies=[Depends(exigir_contrasena)])
def detalle_equipo(nombre: str):
    with engine.connect() as conn:
        eq = conn.execute(text("SELECT * FROM equipos WHERE nombre = :n"), {"n": nombre}).mappings().first()
        if not eq:
            raise HTTPException(404, "Equipo no encontrado")
        historial = conn.execute(
            text(
                "SELECT cpu, ram, disco, temperatura, espacio_libre, fecha, temp_estimada, uptime_segundos "
                "FROM mediciones "
                "WHERE equipo_id = :id ORDER BY id DESC LIMIT 60"
            ),
            {"id": eq["id"]},
        ).mappings().all()
        alertas = conn.execute(
            text(
                "SELECT riesgo, mensaje, fecha, estado FROM alertas "
                "WHERE equipo_id = :id ORDER BY id DESC LIMIT 20"
            ),
            {"id": eq["id"]},
        ).mappings().all()
    if not historial:
        raise HTTPException(404, "Sin mediciones")
    return {
        "equipo": dict(eq),
        "actual": _con_estado(dict(historial[0])),
        "historial": [{**dict(h), "temp_estimada": bool(h["temp_estimada"])} for h in reversed(historial)],
        "alertas": [dict(a) for a in alertas],
    }


@app.get("/api/alertas", dependencies=[Depends(exigir_contrasena)])
def listar_alertas():
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                "SELECT a.id, e.nombre AS equipo, a.riesgo, a.mensaje, a.fecha, a.estado "
                "FROM alertas a JOIN equipos e ON e.id = a.equipo_id ORDER BY a.id DESC LIMIT 50"
            )
        ).mappings().all()
    return [dict(f) for f in filas]


@app.post("/api/alertas/{alerta_id}/resolver", dependencies=[Depends(exigir_contrasena)])
def resolver_alerta(alerta_id: int):
    with engine.begin() as conn:
        conn.execute(text("UPDATE alertas SET estado = 'resuelta' WHERE id = :id"), {"id": alerta_id})
    return {"ok": True}


# ---------------------------------------------------------------- Modo demostración
# "Simular fallo" crea un equipo ficticio (PC-DEMO) que el propio servidor lleva de normal a
# crítico en ~30 s, para mostrar cómo reaccionan el semáforo, la alerta y la recomendación.
# No toca los datos de los equipos reales.
_demo_hilo: threading.Thread | None = None
_demo_parar = threading.Event()
_demo_candado = threading.Lock()


def _guion_demo() -> None:
    inicio = (25.0, 40.0, 55.0, 45.0)  # cpu, ram, disco, temperatura
    fin = (97.0, 94.0, 91.0, 89.0)
    pasos_subida, pasos_total = 15, 25  # 2 s por paso: sube ~30 s y se mantiene ~20 s
    for i in range(pasos_total):
        if _demo_parar.is_set():
            return
        p = min(1.0, i / pasos_subida)
        cpu, ram, disco, temp = (min(100.0, max(0.0, a + (b - a) * p + random.uniform(-1.5, 1.5)))
                                 for a, b in zip(inicio, fin))
        registrar_medicion(Medicion(equipo=NOMBRE_DEMO, cpu=round(cpu, 1), ram=round(ram, 1),
                                    disco=round(disco, 1), temperatura=round(temp, 1), espacio_libre=40))
        _demo_parar.wait(2)


def _demo_activo() -> bool:
    return _demo_hilo is not None and _demo_hilo.is_alive()


def _exigir_demo() -> None:
    if not DEMO_ACTIVA:
        raise HTTPException(404, "El modo demostración está desactivado")


@app.get("/api/config", dependencies=[Depends(exigir_contrasena)])
def configuracion():
    return {"demo": DEMO_ACTIVA, "offline_seg": OFFLINE_SEG}


@app.get("/api/demo", dependencies=[Depends(exigir_contrasena)])
def estado_demo():
    return {"activo": _demo_activo()}


@app.post("/api/demo/fallo", dependencies=[Depends(exigir_contrasena)])
def iniciar_demo():
    global _demo_hilo
    _exigir_demo()
    with _demo_candado:
        if _demo_activo():
            raise HTTPException(409, "La simulación ya está en curso")
        _demo_parar.clear()
        _demo_hilo = threading.Thread(target=_guion_demo, daemon=True)
        _demo_hilo.start()
    return {"ok": True, "equipo": NOMBRE_DEMO}


@app.post("/api/demo/reset", dependencies=[Depends(exigir_contrasena)])
def quitar_demo():
    _exigir_demo()
    with _demo_candado:
        _demo_parar.set()
        if _demo_hilo is not None:
            _demo_hilo.join(timeout=5)
            if _demo_hilo.is_alive():
                raise HTTPException(409, "La simulación todavía se está deteniendo")
        borrar_equipo(NOMBRE_DEMO)
    return {"ok": True}


@app.get("/", dependencies=[Depends(exigir_contrasena)])
def index():
    return FileResponse(FRONTEND / "index.html")
