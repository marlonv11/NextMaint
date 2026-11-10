"""Simula varios PCs del laboratorio enviando mediciones al backend.

Uso:  python agent/simulador.py [--url http://localhost:8000] [--intervalo 3]
"""
import argparse
import random
import time

import httpx

# (nombre, cpu, ram, disco, temperatura) base de cada perfil
PERFILES = {
    "PC-01": (35, 48, 52, 48),
    "PC-02": (78, 82, 76, 69),
    "PC-03": (96, 94, 91, 87),
    "PC-04": (20, 35, 40, 42),
    "PC-05": (60, 70, 85, 60),
}


def jitter(v: float, rango: float = 3, tope: float = 100) -> float:
    return round(max(0, min(tope, v + random.uniform(-rango, rango))), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--intervalo", type=float, default=3)
    args = ap.parse_args()

    while True:
        for nombre, (cpu, ram, disco, temp) in PERFILES.items():
            datos = {
                "equipo": nombre,
                "cpu": jitter(cpu),
                "ram": jitter(ram),
                "disco": jitter(disco, 0.5),
                "temperatura": jitter(temp, 2, 110),
                "espacio_libre": round(max(0, 500 * (100 - disco) / 100), 1),
            }
            try:
                r = httpx.post(f"{args.url}/api/mediciones", json=datos, timeout=5).json()
                print(f'{nombre}: {r["nivel"]}')
            except httpx.HTTPError as e:
                print(f"No se pudo enviar: {e}")
        time.sleep(args.intervalo)


if __name__ == "__main__":
    main()
