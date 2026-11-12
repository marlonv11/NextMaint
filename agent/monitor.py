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


def medir(nombre: str) -> dict:
    disco = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
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
            r = httpx.post(f"{args.url}/api/mediciones", json=datos, headers=cabeceras, timeout=15)
            if r.status_code == 401:
                print("  (el servidor rechazó la clave: revisa --clave)")
            elif r.status_code >= 400:
                print(f"  (el servidor respondió {r.status_code})")
        except httpx.HTTPError as e:
            print(f"  (no se pudo enviar: {e})")
        time.sleep(args.intervalo)


if __name__ == "__main__":
    main()
