SmartMaintenance Lab
MVP de monitoreo preventivo de computadores de un laboratorio.
Flujo: agente → backend (FastAPI) → SQLite → evaluación de riesgo → alertas → dashboard.
Estructura
nextMaint/
├── agent/
│   ├── monitor.py      # agente real (psutil) que corre en cada PC
│   └── simulador.py    # simula 5 PCs para probar/demostrar
├── backend/
│   ├── main.py         # API FastAPI
│   ├── db.py           # SQLite: equipos, mediciones, alertas
│   └── risk.py         # riesgo por reglas (línea base antes del ML)
└── frontend/           # dashboard (HTML, CSS y JavaScript)
Cómo correrlo
python -m pip install -r requirements.txt

# Terminal 1: backend + dashboard
python -m uvicorn backend.main:app --reload

# Terminal 2: datos de ejemplo (PC-01 a PC-05)
python agent/simulador.py

# agente real en tu propia máquina
python agent/monitor.py
Abre http://localhost:8000 para el dashboard y http://localhost:8000/docs para la API.

SQLite guarda los datos en ~/.nex-maint/nex-maint.db por defecto. El servidor
agrega la columna del tiempo encendido a las bases existentes al arrancar.

El dashboard consulta la API cada 2 segundos y muestra la edad de la última
lectura por equipo. Si pasan más de 30 segundos sin datos, lo marca como
Sin conexión. El límite se puede cambiar con NEXMAINT_OFFLINE_SEG.
El agente real envía el tiempo desde el último arranque del equipo.

Para probar las alertas desde el dashboard, usa Simular fallo. El servidor
crea el equipo ficticio PC-DEMO y eleva su riesgo en unos 30 segundos.
Quitar simulación retira ese equipo y sus alertas de prueba.
Reglas de riesgo (backend/risk.py)
Cada métrica suma 0, 1 o 2 puntos según umbrales (CPU/RAM/disco: 75 / 90; temperatura: 65 / 80).
La temperatura estimada queda fuera del cálculo.
Score >= 6 o temperatura medida >= 85 → alto; score >= 3 → medio; si no → bajo.
Limitaciones conocidas
- La temperatura real no está disponible con psutil en Windows; el agente la simula a partir de la carga de CPU.
- Los umbrales son valores iniciales, no calibrados.
Siguiente paso: modelo de ML
1. Generar un CSV sintético con CPU, RAM, disco, temperatura, errores y uptime, etiquetado con risk.evaluar().
2. Entrenar un clasificador (scikit-learn, por ejemplo RandomForest) en backend/ai/.
3. Comparar su salida contra las reglas y usarlo en risk.py como alternativa.