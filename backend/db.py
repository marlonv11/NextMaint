"""Base de datos: SQLite en tu PC (por defecto) o PostgreSQL en la nube.

- Sin variables de entorno: usa SQLite en ~/.nex-maint/nex-maint.db (fuera de OneDrive).
- NEXMAINT_DB=ruta.db   -> otra ruta para SQLite.
- DATABASE_URL=postgresql://...  -> PostgreSQL (Render la define automáticamente).
- NEXMAINT_TZ           -> zona horaria de las fechas guardadas (por defecto America/Bogota).
- NEXMAINT_RETENCION_DIAS -> días de mediciones que se conservan (por defecto 14).
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text,
    create_engine, false, insert, inspect, select, text,
)
from sqlalchemy.exc import IntegrityError

ZONA = ZoneInfo(os.environ.get("NEXMAINT_TZ", "America/Bogota"))
RETENCION_DIAS = int(os.environ.get("NEXMAINT_RETENCION_DIAS", "14"))


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Render entrega postgres:// o postgresql://; SQLAlchemy necesita saber el driver (psycopg 3).
        for prefijo in ("postgres://", "postgresql://"):
            if url.startswith(prefijo):
                return "postgresql+psycopg://" + url[len(prefijo):]
        return url
    ruta = Path(os.environ.get("NEXMAINT_DB") or Path.home() / ".nex-maint" / "nex-maint.db")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{ruta.as_posix()}"


_URL = _url()
engine = create_engine(_URL) if _URL.startswith("sqlite") else \
    create_engine(_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)

metadata = MetaData()

equipos = Table(
    "equipos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nombre", String(64), nullable=False, unique=True),
    Column("ubicacion", String(100), default="Laboratorio"),
    Column("estado", String(10), default="bajo"),
)

mediciones = Table(
    "mediciones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("equipo_id", Integer, ForeignKey("equipos.id"), nullable=False),
    Column("cpu", Float), Column("ram", Float), Column("disco", Float),
    Column("temperatura", Float), Column("espacio_libre", Float),
    Column("fecha", String(19), nullable=False),
    # True cuando el equipo no tiene sensor legible y la temperatura se calculó a partir de la CPU
    Column("temp_estimada", Boolean, nullable=False, default=False, server_default=false()),
    Column("uptime_segundos", Integer),
    Index("ix_mediciones_equipo_id", "equipo_id", "id"),
)

alertas = Table(
    "alertas", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("equipo_id", Integer, ForeignKey("equipos.id"), nullable=False),
    Column("riesgo", String(10), nullable=False),
    Column("mensaje", Text, nullable=False),
    Column("fecha", String(19), nullable=False),
    Column("estado", String(10), default="activa"),
)


def init_db() -> None:
    metadata.create_all(engine)
    _migrar()


def _migrar() -> None:
    """Agrega columnas nuevas a bases de datos creadas con versiones anteriores."""
    with engine.begin() as conn:
        columnas = {c["name"] for c in inspect(conn).get_columns("mediciones")}
        if "temp_estimada" not in columnas:
            tipo = "BOOLEAN NOT NULL DEFAULT FALSE" if conn.dialect.name == "postgresql" else "INTEGER NOT NULL DEFAULT 0"
            conn.execute(text(f"ALTER TABLE mediciones ADD COLUMN temp_estimada {tipo}"))
        if "uptime_segundos" not in columnas:
            conn.execute(text("ALTER TABLE mediciones ADD COLUMN uptime_segundos INTEGER"))


def ahora() -> str:
    """Fecha y hora local como texto 'AAAA-MM-DD HH:MM:SS' (igual en SQLite y PostgreSQL)."""
    return datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S")


def asegurar_equipo(nombre: str) -> None:
    """Crea el equipo si no existe (tolera dos agentes nuevos llegando a la vez)."""
    with engine.connect() as conn:
        if conn.execute(select(equipos.c.id).where(equipos.c.nombre == nombre)).first():
            return
    try:
        with engine.begin() as conn:
            conn.execute(insert(equipos).values(nombre=nombre, ubicacion="Laboratorio", estado="bajo"))
    except IntegrityError:
        pass  # otro agente lo creó justo antes


def borrar_equipo(nombre: str) -> None:
    """Elimina un equipo con sus mediciones y alertas (se usa para quitar el equipo de demostración)."""
    with engine.begin() as conn:
        fila = conn.execute(text("SELECT id FROM equipos WHERE nombre = :n"), {"n": nombre}).first()
        if not fila:
            return
        for tabla in ("alertas", "mediciones"):
            conn.execute(text(f"DELETE FROM {tabla} WHERE equipo_id = :id"), {"id": fila.id})
        conn.execute(text("DELETE FROM equipos WHERE id = :id"), {"id": fila.id})


def limpiar_antiguas(conn) -> None:
    """Borra mediciones más viejas que RETENCION_DIAS para no llenar la base de datos."""
    limite = (datetime.now(ZONA) - timedelta(days=RETENCION_DIAS)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(text("DELETE FROM mediciones WHERE fecha < :limite"), {"limite": limite})
