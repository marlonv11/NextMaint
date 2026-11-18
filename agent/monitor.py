"""Agente de monitoreo: lee métricas del equipo y las envía al backend.

Uso:  python agent/monitor.py [--url http://localhost:8000] [--intervalo 5] [--clave CLAVE]
La clave también puede venir de la variable de entorno NEXMAINT_KEY.
"""
import argparse
import json
import os
import platform
import random
import socket
import time

import httpx
import psutil


def leer_temperatura(cpu: float) -> tuple[float, bool]:
    """Devuelve (temperatura, es_real). En Windows psutil no la soporta: se simula."""
    try:
        sensores = psutil.sensors_temperatures()
        for lecturas in sensores.values():
            if lecturas:
                return round(lecturas[0].current, 1), True
    except (AttributeError, NotImplementedError):
        pass
    # Simulada a partir de la carga de CPU (limitación documentada en el README)
    return round(40 + cpu * 0.4 + random.uniform(-2, 2), 1), False


IGNORAR = {"system idle process", "idle", "system", "registry", "memory compression"}


def _preparar_procesos() -> list:
    """Lista los procesos y arranca su medición de CPU (la lectura útil llega 1 s después)."""
    procesos = []
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
            procesos.append(p)
        except psutil.Error:
            pass
    return procesos


def _top_procesos(procesos: list) -> list[dict]:
    """Los programas que más memoria y CPU usan, agrupados por nombre (Chrome tiene muchos procesos)."""
    nucleos = psutil.cpu_count() or 1
    grupos: dict[str, list[float]] = {}
    for p in procesos:
        try:
            nombre = p.name()
            if nombre.lower() in IGNORAR:
                continue
            g = grupos.setdefault(nombre, [0.0, 0.0])
            g[0] += p.cpu_percent(None) / nucleos
            g[1] += p.memory_info().rss / 1024**2
        except psutil.Error:
            continue
    lista = [{"nombre": n[:60], "cpu": round(min(c, 100.0), 1), "ram_mb": round(m)} for n, (c, m) in grupos.items()]
    por_ram = sorted(lista, key=lambda x: -x["ram_mb"])[:3]
    por_cpu = [x for x in sorted(lista, key=lambda x: -x["cpu"])[:3] if x["cpu"] > 0 and x not in por_ram]
    return (por_ram + por_cpu)[:6]


def medir(nombre: str) -> dict:
    disco = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
    procesos = _preparar_procesos()
    cpu = psutil.cpu_percent(interval=1)
    temp, es_real = leer_temperatura(cpu)
    return {
        "equipo": nombre,
        "cpu": cpu,
        "ram": psutil.virtual_memory().percent,
        "disco": disco.percent,
        "temperatura": temp,
        "temperatura_estimada": not es_real,  # el dashboard la rotula y no la usa para el riesgo
        "espacio_libre": round(disco.free / 1024**3, 1),
        "uptime_segundos": max(0, int(time.time() - psutil.boot_time())),
        "procesos": _top_procesos(procesos),  # para que el asistente diga qué programa consume
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--intervalo", type=int, default=5)
    ap.add_argument("--nombre", default=socket.gethostname())
    ap.add_argument("--clave", default=os.environ.get("NEXMAINT_KEY", ""))
    args = ap.parse_args()
    cabeceras = {"X-API-Key": args.clave} if args.clave else {}

    while True:
        datos = medir(args.nombre)
        print(json.dumps(datos, ensure_ascii=False))
        try:
            r = httpx.post(f"{args.url}/api/mediciones", json=datos, headers=cabeceras, timeout=5)
            if r.status_code == 401:
                print("  (el servidor rechazó la clave: revisa --clave)")
            elif r.status_code >= 400:
                print(f"  (el servidor respondió {r.status_code})")
        except httpx.HTTPError as e:
            print(f"  (no se pudo enviar: {e})")
        time.sleep(args.intervalo)


if __name__ == "__main__":
    main()
