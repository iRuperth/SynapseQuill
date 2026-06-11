<div align="center">

<img src="frontend/public/logo.png" alt="F88tball" width="380" />

### Generador automático de vídeos resumen del Mundial 2026 para YouTube, con LLMs, LangChain / LangGraph y IA de capa gratuita.

[![English](https://img.shields.io/badge/English-1a1a1a?style=for-the-badge)](README.md) **·** [![Español](https://img.shields.io/badge/Espa%C3%B1ol-1a1a1a?style=for-the-badge)](README.es.md)

[![Python](https://img.shields.io/badge/Python-3.12-1a1a1a?style=flat&logo=python&logoColor=white&labelColor=1a1a1a)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-1a1a1a?style=flat&logo=fastapi&logoColor=white&labelColor=1a1a1a)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-1a1a1a?style=flat&logo=react&logoColor=white&labelColor=1a1a1a)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-7.x-1a1a1a?style=flat&logo=vite&logoColor=white&labelColor=1a1a1a)](https://vitejs.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-1a1a1a?style=flat&logo=typescript&logoColor=white&labelColor=1a1a1a)](https://www.typescriptlang.org/)
[![LangChain](https://img.shields.io/badge/LangChain-LangGraph-1a1a1a?style=flat&logo=langchain&logoColor=white&labelColor=1a1a1a)](https://www.langchain.com/)
[![MoviePy](https://img.shields.io/badge/MoviePy-ffmpeg-1a1a1a?style=flat&labelColor=1a1a1a)](https://zulko.github.io/moviepy/)
[![Edge TTS](https://img.shields.io/badge/Edge--TTS-voz-1a1a1a?style=flat&labelColor=1a1a1a)](https://github.com/rany2/edge-tts)
[![Docker](https://img.shields.io/badge/Docker-compose-1a1a1a?style=flat&logo=docker&logoColor=white&labelColor=1a1a1a)](https://www.docker.com/)
[![pnpm](https://img.shields.io/badge/pnpm-gestor-1a1a1a?style=flat&logo=pnpm&logoColor=white&labelColor=1a1a1a)](https://pnpm.io/)
[![uv](https://img.shields.io/badge/uv-gestor%20python-1a1a1a?style=flat&logo=astral&logoColor=white&labelColor=1a1a1a)](https://docs.astral.sh/uv/)
[![Coste](https://img.shields.io/badge/coste-capa%20gratuita-1a1a1a?style=flat&labelColor=1a1a1a)](#stack-tecnologico)

</div>

---

## Que es F88tball?

F88tball convierte un partido terminado en un vídeo resumen listo para publicar.
Le das un partido y construye una narración emocionante escrita por un LLM, una
voz real (Edge-TTS), elementos visuales sin problemas de copyright (escudos de
los equipos, un marcador animado, ambiente con IA opcional), subtítulos
incrustados y una subida automática **privada** a YouTube. También redacta el
texto para blog / X / Instagram / LinkedIn del mismo partido.

Todo funciona en **capas gratuitas** (Groq, ESPN, Edge-TTS, imágenes FLUX,
embeddings locales), así que la prueba de concepto completa no cuesta nada.

El panel web añade un calendario del Mundial 2026, un cuadro de eliminatorias
que se rellena solo, un power ranking FIFA de las 48 selecciones, una biblioteca
de contenido con subidas masivas y programadas a YouTube, y un Laboratorio IA
(RAG de arXiv, noticias financieras en vivo, enrutado multiagente). La interfaz
viene en **español e inglés** con temas claro, oscuro y para daltónicos.

## Como funciona (flujo de datos)

```
ESPN / openfootball                    .env + profiles/<id>
 (partidos, goleadores,                (equipo, idioma, voz,
  banderas, calendario)                 proveedores, marca/persona)
        |                                        |
        v                                        v
  match_monitor.py  ----- partido terminado --> runner.py  (orquestacion)
                                                  |
        +-----------------+-----------------+-----+-----------------+
        v                 v                 v                       v
   narrator.py      media_provider.py   voice_generator.py   content_generator.py
   (narracion LLM   (escudos, marcador  (voz Edge-TTS +      (texto blog / X /
    + caracter       animado, ambiente   subtitulos           IG / LinkedIn)
    del partido)     FLUX)               sincronizados)
        |                 |                 |
        v                 |                 |
   guardrail.py           |                 |
   (verifica los datos    |                 |
    + LLM como juez,      |                 |
    regenera si falla)    |                 |
        +-----------------+-----------------+
                          v
                  video_assembler.py
                 (MoviePy + ffmpeg -> .mp4,
                  subtitulos incrustados)
                          v
                  publishers.py
              (YouTube Data API v3 OAuth,
               sube privado por defecto)
```

Los datos del partido y la configuración de marca alimentan el orquestador. La
narración la verifica un guardrail (y la regenera si se inventa un resultado)
antes de componer voz, visuales y subtítulos en un MP4 y subirlo.

## Estructura del proyecto

```
F88tball/
├── core/
│   ├── brand_config.py      BrandProfile: configuracion por perfil (equipo, idioma, voz, persona)
│   ├── competitions.py      presets de competicion (La Liga, Mundial 2026, ...)
│   ├── voices.py            presets de voces de relator
│   ├── architecture.py      mapa del sistema servido a la interfaz
│   ├── llm/                 LLMs intercambiables: groq · gemini · cerebras · ollama (+ respaldos)
│   └── tracing.py           activacion de LangSmith
├── pipeline/
│   ├── match_monitor.py     deteccion de partido terminado + modelo Match / Goal
│   ├── data_sources/        ESPN (por defecto), API-Football, TheSportsDB, cache en disco
│   ├── wc_calendar.py       calendario del Mundial 2026 (openfootball)
│   ├── wc_bracket.py        cuadro de eliminatorias que se rellena solo
│   ├── power_ranking.py     power ranking FIFA de las 48 selecciones del Mundial
│   ├── narrator.py          narracion multiidioma + tono segun el partido + metadatos
│   ├── media_provider.py    visuales: escudos · marcador/timeline · ambiente FLUX
│   ├── voice_generator.py   voz Edge-TTS + subtitulos sincronizados
│   ├── video_assembler.py   slideshow MoviePy + audio + subtitulos -> .mp4
│   ├── content_generator.py texto blog / X / Instagram / LinkedIn
│   ├── publishers.py        subida OAuth a YouTube Data API v3 (privado)
│   ├── runner.py            orquestacion por partido (con guardrail)
│   └── tools/               finanzas (Finnhub) · arxiv_rag (Chroma) · graph_rag (NetworkX)
├── agents/
│   ├── guardrail.py         anti-alucinacion: verificacion de datos + LLM como juez
│   └── graph.py             supervisor LangGraph que enruta agentes especializados
├── api/server.py            backend FastAPI (perfiles, partidos, generar, rankings, ...)
├── frontend/                panel React 19 + Vite 7 + TypeScript (ES / EN, temas)
│   ├── public/              logo + favicons
│   └── src/                 paginas, cliente api, catalogo i18n, componentes
├── profiles/<id>/           profile.json + .env + tokens + salida
├── scripts/                 servicio en segundo plano (launchd)
├── main.py                  CLI (fixtures, partido, scheduler, informe)
└── docker-compose.yml       backend + frontend (nginx)
```

## Stack tecnologico

| Capa | Eleccion | Capa gratuita |
|------|----------|---------------|
| LLM de texto | Groq (Llama 3.3 70B) mas Gemini / Cerebras / Ollama | si |
| Orquestacion | LangChain, LangGraph, LangSmith | 5k trazas/mes |
| Datos de futbol | ESPN (por defecto), API-Football, TheSportsDB | gratis |
| Imagenes | FLUX (Together / FAL) luego Cloudflare / HF / local | capas gratuitas |
| Voz | Edge-TTS (sin clave) luego Piper / gTTS | gratis |
| Video | MoviePy mas ffmpeg | local |
| RAG | arXiv mas Chroma mas BAAI/bge-small (local) | gratis |
| Graph RAG | LLMGraphTransformer mas NetworkX | gratis |
| Finanzas | Finnhub (mas yfinance) | 60 req/min |
| Frontend | React 19, Vite 7, TypeScript | local |
| Herramientas | uv (Python), pnpm (Node), Docker | local |

## Inicio rapido

Necesitas Python 3.12 y Node 18+. El backend se gestiona con
[uv](https://docs.astral.sh/uv/) y el frontend con [pnpm](https://pnpm.io/).

### macOS / Linux

```bash
# 1. Backend
uv sync
cp .env.example .env          # anade GROQ_API_KEY (gratis); ESPN no necesita clave
uv run uvicorn api.server:app --reload --port 5001

# 2. Frontend (otra terminal)
cd frontend
pnpm install
pnpm run dev                  # http://localhost:5173
```

### Windows (PowerShell)

```powershell
# 1. Backend
uv sync
Copy-Item .env.example .env   # anade GROQ_API_KEY (gratis); ESPN no necesita clave
uv run uvicorn api.server:app --reload --port 5001

# 2. Frontend (otra terminal)
cd frontend
pnpm install
pnpm run dev                  # http://localhost:5173
```

Las imagenes (FLUX) y la voz (Edge-TTS) no necesitan clave. Abre
`http://localhost:5173` y el panel habla con el backend en el puerto 5001.

### Atajos con make (macOS / Linux)

El Makefile envuelve los pasos de arriba:

```bash
make install   # uv sync + pnpm install
make dev       # backend (:5001) y frontend (:5173) a la vez — Ctrl+C para los dos
make backend   # solo el backend
make frontend  # solo el frontend
make build     # build de produccion del frontend
make docker    # todo el stack en Docker (frontend :8080, backend :5001)
make clean     # borra los artefactos generados
```

## CLI

```bash
python main.py --profile worldcup_es --fixtures              # partidos de hoy
python main.py --profile worldcup_es --match 12345           # genera un video
python main.py --profile worldcup_es --scheduler             # genera al terminar cada partido
python main.py --profile worldcup_es --match 12345 --upload --social
```

## Docker

```bash
cp .env.example .env
docker compose up --build      # frontend :8080  ·  backend :5001
```

## Servicio en segundo plano (macOS)

Ejecuta el scheduler como un servicio que genera y sube un resumen al terminar
cada partido. Sobrevive al cierre de la terminal y del IDE, se reinicia si falla
y arranca al iniciar sesion.

```bash
bash scripts/f88ball_scheduler_ctl.sh install    # instala y arranca
bash scripts/f88ball_scheduler_ctl.sh status     # esta corriendo?
bash scripts/f88ball_scheduler_ctl.sh logs       # sigue el log en vivo
bash scripts/f88ball_scheduler_ctl.sh stop       # detener
bash scripts/f88ball_scheduler_ctl.sh uninstall  # eliminar
```

Logs en `profiles/worldcup_es/output/logs/scheduler.log`. La etiqueta launchd es
`com.f88ball.scheduler`, unica por app para que varios proyectos puedan correr el suyo.

## Claves de API

Necesario para una demo: `GROQ_API_KEY` (gratis). ESPN (la fuente por defecto)
no necesita clave. Para subir a YouTube: por perfil
`profiles/<id>/tokens/client_secret.json` (OAuth). Extras opcionales:
`GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `TOGETHER_API_KEY`, `LANGSMITH_API_KEY`,
`FINNHUB_API_KEY`.

## Privacidad y modo prueba

`PRACTICE_MODE=true` (por defecto) fuerza cada subida a YouTube a **privada**.
Cambia `YOUTUBE_PRIVACY=private|unlisted|public` para ajustar la visibilidad
cuando estes listo.

## Cobertura del briefing

| Nivel | Requisito | Donde |
|-------|-----------|-------|
| Esencial | Texto multiplataforma desde prompts; interfaz web; git | `content_generator.py`, `frontend/` |
| Medio | Docker; dos o mas LLMs; preambulo de empresa / persona; imagenes en el contenido | `docker-compose.yml`, `core/llm/`, `brand_config.system_preamble`, `media_provider.py` |
| Avanzado | Trazabilidad; ES / EN / FR / IT; noticias financieras en vivo; RAG de arXiv | `tracing.py`, `narrator.py`, `tools/finance.py`, `tools/arxiv_rag.py` |
| Experto | Graph RAG; sistema multiagente; guardrails | `tools/graph_rag.py`, `agents/graph.py`, `agents/guardrail.py` |
