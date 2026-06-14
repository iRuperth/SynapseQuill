"""
architecture.py — a self-describing map of the system, served to the frontend.

This is the single source of truth behind the "Arquitectura" page: the external
APIs, the building blocks, and the end-to-end flows (matches, create, lab,
agents). The page renders it in two modes — `simple` (plain-language) and
`technical` (endpoints, models, files, request/response) — and every step/service
is expandable into a `detail` paragraph that explains, in plain words, *what
actually happens there* (no unexplained jargon). Keeping the data here (not
hard-coded in the React page) means the docs follow the code from one place.

Each step carries:
  easy   one-line summary (always visible)
  tech   input -> api/model -> output (shown in technical mode)
  file   the module that implements it
  detail a full plain-language explanation, shown when the step is expanded
"""


# --- External services / APIs -------------------------------------------------
# `free`: "yes" (free, no card), "tier" (free tier / limited), "key" (needs a
# free key), "local" (runs on your machine), "oauth".
SERVICES = [
    {"group": "LLM (texto)", "items": [
        {"name": "Cerebras", "easy": "Escribe las narraciones y textos (muy rápido).",
         "model": "llama-3.3-70b (o gpt-oss-120b)", "env": "CEREBRAS_API_KEY (+ _2.._5)",
         "file": "core/llm/cerebras.py", "free": "tier",
         "detail": "Un 'LLM' es un modelo de lenguaje: le das un texto (el 'prompt') y "
                   "te devuelve texto escrito. Cerebras es el proveedor principal aquí "
                   "porque responde muy rápido. La app le manda los datos del partido y "
                   "las instrucciones de estilo, y él redacta la narración. Tienes 5 "
                   "claves (CEREBRAS_API_KEY_2..5): si una se queda sin cuota del día, la "
                   "app salta a la siguiente automáticamente."},
        {"name": "Groq", "easy": "Modelo de texto de respaldo y editor de estilo.",
         "model": "llama-3.3-70b-versatile", "env": "GROQ_API_KEY",
         "file": "core/llm/groq.py", "free": "yes",
         "detail": "Otro proveedor de LLM, también muy rápido y gratis. Se usa como "
                   "respaldo si Cerebras falla, y como 'editor' que repasa la narración "
                   "para que suene más natural en español sin cambiar los hechos."},
        {"name": "Gemini", "easy": "Modelo de texto alternativo de Google (opcional).",
         "model": "gemini-2.5-flash", "env": "GEMINI_API_KEY / GOOGLE_API_KEY",
         "file": "core/llm/gemini.py", "free": "tier",
         "detail": "El modelo de Google. Está integrado por si quieres cambiar de "
                   "proveedor, pero no se usa por defecto. Se activa poniendo su clave y "
                   "eligiéndolo como LLM_PROVIDER."},
        {"name": "Ollama", "easy": "Modelo de texto local, sin internet (opcional).",
         "model": "qwen2.5:7b", "env": "OLLAMA_HOST / OLLAMA_MODEL",
         "file": "core/llm/ollama.py", "free": "local",
         "detail": "Ollama corre un modelo de lenguaje en tu propio ordenador, sin "
                   "enviar nada a internet. Es la opción más privada y gratis, pero más "
                   "lenta y necesita un equipo potente. Último recurso de la cadena."},
    ]},
    {"group": "Imágenes (FLUX)", "items": [
        {"name": "Together.ai", "easy": "Genera los fondos de afición/ambiente del estadio.",
         "model": "FLUX.1-schnell", "env": "TOGETHER_API_KEY (+ _2)",
         "file": "pipeline/image_generator.py", "free": "tier",
         "detail": "FLUX es un modelo que crea imágenes a partir de una descripción de "
                   "texto ('una grada llena de aficionados del Atlético, luz dramática'). "
                   "'schnell' significa 'rápido' en alemán: es la versión veloz. Together "
                   "es el servicio que ejecuta ese modelo. La imagen se usa como fondo "
                   "del vídeo. Solo se genera si activas 'flux' en las fuentes de medios; "
                   "por defecto el vídeo usa gráficos animados propios."},
        {"name": "Fal.ai", "easy": "Generador de imágenes de respaldo.",
         "model": "fal-ai/flux/schnell", "env": "FAL_API_KEY",
         "file": "pipeline/image_generator.py", "free": "tier",
         "detail": "Otro servicio que ejecuta el mismo modelo FLUX. Si Together falla o "
                   "se queda sin cuota, la app prueba Fal automáticamente."},
        {"name": "Pollinations / Cloudflare / HuggingFace", "easy": "Más alternativas para generar imágenes.",
         "model": "FLUX.1-schnell", "env": "CF_ACCOUNT_ID / HF_TOKEN (opcional)",
         "file": "pipeline/image_generator.py", "free": "tier",
         "detail": "Tres proveedores más que también ejecutan FLUX, por si quieres "
                   "cambiar. Cloudflare da 10.000 generaciones gratis al día; "
                   "HuggingFace tiene capa gratuita; Pollinations no necesita clave."},
    ]},
    {"group": "Voz (TTS)", "items": [
        {"name": "Edge-TTS", "easy": "Voz del narrador por defecto (gratis e ilimitada).",
         "model": "es-MX-JorgeNeural y otras", "env": "— (sin clave)",
         "file": "pipeline/voice_generator.py", "free": "yes",
         "detail": "TTS = 'text to speech', convertir texto en voz hablada. Edge-TTS son "
                   "las voces de Microsoft, gratis y sin límite. La voz por defecto es "
                   "Jorge (México), que narra fútbol con energía. Se puede subir la "
                   "velocidad y el tono para que suene más eufórico. Además devuelve la "
                   "marca de tiempo de cada palabra, que sirve para los subtítulos."},
        {"name": "ElevenLabs", "easy": "Voz de mayor calidad (premium).",
         "model": "eleven_multilingual_v2", "env": "ELEVEN_LABS* + ELEVEN_VOICE_*",
         "file": "pipeline/voice_generator.py", "free": "tier",
         "detail": "Voces de IA de altísima calidad. Las voces 'premade' (Adam, Bill) "
                   "funcionan en el plan gratis; las de la biblioteca (Theo) necesitan "
                   "plan de pago. Tiene cuota mensual limitada (~10 min/mes gratis). La "
                   "app rota entre varias claves cuando una se queda sin crédito."},
        {"name": "gTTS", "easy": "Voz de respaldo simple.",
         "model": "Google Translate TTS", "env": "— (sin clave)",
         "file": "pipeline/voice_generator.py", "free": "yes",
         "detail": "La voz del traductor de Google. Suena más plana y no genera "
                   "subtítulos, pero sirve como último recurso si todo lo demás falla."},
    ]},
    {"group": "Datos de fútbol", "items": [
        {"name": "ESPN (API pública)", "easy": "Resultados, goleadores, minutos y cómo fue cada gol.",
         "model": "site.api.espn.com", "env": "ESPN_LEAGUE_SLUG",
         "file": "pipeline/data_sources/espn.py", "free": "yes",
         "detail": "Una 'API' es una dirección web que devuelve datos en vez de una "
                   "página. ESPN publica una gratis y sin clave con marcadores, quién "
                   "marcó, en qué minuto e incluso una descripción de la jugada. Es la "
                   "fuente principal de hechos para que la narración sea verídica."},
        {"name": "API-Football", "easy": "Fuente alternativa de datos (opcional).",
         "model": "v3.football.api-sports.io", "env": "APIFOOTBALL_KEY",
         "file": "pipeline/data_sources/apifootball.py", "free": "tier",
         "detail": "Otra API de datos de fútbol, con plan gratis de 100 peticiones al "
                   "día (solo temporadas 2021-2024). Disponible por si ESPN no cubre una "
                   "competición."},
        {"name": "openfootball", "easy": "Calendario del Mundial 2026.",
         "model": "worldcup.json (GitHub)", "env": "— (público)",
         "file": "pipeline/wc_calendar.py", "free": "yes",
         "detail": "Un archivo público en GitHub con los 104 partidos del Mundial 2026 "
                   "(fechas y enfrentamientos). Se usa para mostrar el calendario."},
    ]},
    {"group": "Laboratorio IA y extras", "items": [
        {"name": "arXiv + embeddings + Chroma", "easy": "Busca papers científicos y los resume con base real (RAG).",
         "model": "BAAI/bge-small-en-v1.5 + Chroma", "env": "— (local)",
         "file": "pipeline/tools/arxiv_rag.py", "free": "local",
         "detail": "arXiv es el gran repositorio de artículos científicos. 'Embeddings' "
                   "convierten cada trozo de texto en una lista de números que captura su "
                   "significado, de forma que textos parecidos quedan 'cerca'. bge-small "
                   "es el modelo que hace esa conversión, y corre en tu ordenador. Chroma "
                   "es una base de datos que guarda esos números y permite buscar por "
                   "significado (no por palabra exacta). Juntos forman 'RAG': la IA "
                   "responde apoyándose en los papers reales recuperados, no en lo que "
                   "'recuerda', así no se inventa."},
        {"name": "Finnhub + yfinance", "easy": "Precios de bolsa y titulares de empresas.",
         "model": "finnhub.io / yfinance", "env": "FINNHUB_API_KEY (yfinance sin clave)",
         "file": "pipeline/tools/finance.py", "free": "tier",
         "detail": "Finnhub es una API de mercados (60 peticiones/min gratis) que da "
                   "precio y titulares de una empresa. yfinance saca precios de Yahoo "
                   "Finanzas sin clave; se usa de respaldo si Finnhub no responde."},
        {"name": "YouTube Data API v3", "easy": "Sube los vídeos generados a tu canal.",
         "model": "OAuth por perfil", "env": "tokens/client_secret.json + youtube_token.pickle",
         "file": "pipeline/publishers.py", "free": "oauth",
         "detail": "La API oficial de YouTube para subir vídeos. 'OAuth' es el permiso "
                   "que le das a la app para publicar en tu nombre: la primera vez "
                   "inicias sesión con Google y se guarda un 'token' para no repetirlo. "
                   "En modo práctica todo se sube como privado."},
        {"name": "LangSmith", "easy": "Registra las llamadas a los modelos para depurar.",
         "model": "trazas de ejecución", "env": "LANGSMITH_API_KEY",
         "file": "core/tracing.py", "free": "tier",
         "detail": "Herramienta de observabilidad: guarda un registro de cada llamada a "
                   "los modelos (qué se pidió, qué respondió, cuánto tardó) para poder "
                   "revisar y depurar. Es opcional y no cambia el comportamiento."},
    ]},
]


# --- End-to-end flows ---------------------------------------------------------
FLOWS = [
    {
        "id": "match",
        "title": "Partidos → vídeo",
        "easy": "De un partido terminado a un vídeo narrado, listo para YouTube.",
        "input": "Un partido (equipos + marcador).",
        "output": "Un vídeo .mp4 con narración, marcador animado y subtítulos.",
        "orchestrator": "pipeline/runner.py · run_match()",
        "endpoint": "POST /api/profiles/{id}/generate",
        "steps": [
            {"easy": "Busca quién marcó, en qué minuto y cómo fue cada gol.",
             "tech": "Match → ESPN público → goles + minutos + descripción", "file": "pipeline/data_sources/espn_enrich.py",
             "detail": "Si solo tenemos el marcador (p. ej. 2-0), la app llama a ESPN para "
                       "rellenar los detalles: nombres de los goleadores, minutos, tarjetas "
                       "y una breve descripción de cada gol. Sin estos datos la narración "
                       "sería vaga; con ellos puede decir 'gol de X al minuto 29 tras un "
                       "centro'."},
            {"easy": "Escribe la narración como un relator apasionado.",
             "tech": "hechos → LLM (Cerebras/Groq) → guion de 90-150 palabras", "file": "pipeline/narrator.py",
             "detail": "Se ordenan los hechos cronológicamente y se le pasan al LLM con "
                       "instrucciones de actuar como un relator legendario: emocionante, "
                       "apto para todo público, con gramática española correcta y entre 90 "
                       "y 150 palabras. El modelo devuelve el guion hablado."},
            {"easy": "Comprueba que la narración no inventa nada (marcador, nombres).",
             "tech": "guion → regex del marcador + LLM-juez (JSON) → reintento si falla", "file": "agents/guardrail.py",
             "detail": "Un 'guardrail' es una barrera de seguridad. Aquí hay dos: (1) una "
                       "comprobación automática de que el marcador del texto coincide con el "
                       "real, y (2) un segundo modelo que actúa de 'juez' y verifica que "
                       "todo esté respaldado por los hechos, en el idioma correcto y con "
                       "buen tono. Si algo no cuadra, se reescribe una vez siendo más "
                       "estricto. Así evitamos que la IA se invente jugadas."},
            {"easy": "Pule el texto para que suene natural en español.",
             "tech": "guion → LLM editor → re-verifica hechos (revierte si cambió un dato)", "file": "pipeline/text_polish.py",
             "detail": "Un editor (otro LLM) reescribe frases que suenan raras y corrige "
                       "fallos típicos ('la penalty' → 'el penalti'). Después se vuelve a "
                       "verificar que no haya cambiado ningún dato; si el editor alteró un "
                       "nombre o marcador por error, se descarta su versión y se mantiene "
                       "la anterior."},
            {"easy": "Genera el título y la descripción de YouTube.",
             "tech": "hechos → LLM (JSON {title, description}) + etiquetas automáticas", "file": "pipeline/narrator.py",
             "detail": "El modelo crea un título atractivo (con el marcador, máx. 90 "
                       "caracteres) y una descripción. Las etiquetas (tags) se construyen "
                       "automáticamente a partir de la competición, los equipos, países, "
                       "goleadores y estadio."},
            {"easy": "Crea el fondo de ambiente del estadio (si está activado).",
             "tech": "nombre de equipo → FLUX.1-schnell (Together/Fal) → imagen PNG", "file": "pipeline/media_provider.py",
             "detail": "Si activaste las imágenes por IA, se genera un fondo de grada con "
                       "los colores del equipo ganador (o de ambos si hubo empate) usando "
                       "FLUX. Esa imagen se usa detrás del vídeo. Por defecto el vídeo usa "
                       "gráficos animados propios y este paso se omite."},
            {"easy": "Convierte el texto en voz y subtítulos.",
             "tech": "guion → Edge-TTS / ElevenLabs → mp3 + tiempos por palabra", "file": "pipeline/voice_generator.py",
             "detail": "El motor de voz lee el guion y produce el audio. Antes, limpia los "
                       "'GOOOL' estirados a 'gol' para que la voz no se trabe, y sube la "
                       "energía cuando detecta gritos. Devuelve también el momento exacto "
                       "de cada palabra, que se usará para los subtítulos sincronizados."},
            {"easy": "Monta el vídeo: marcador animado + subtítulos karaoke + voz.",
             "tech": "imágenes + audio + tiempos → MoviePy (H.264/AAC) → match_<id>.mp4", "file": "pipeline/video_assembler.py",
             "detail": "Se dibujan gráficos animados (marcador, escudos, cronología de "
                       "goles y tarjetas) sobre el fondo, se añaden subtítulos estilo "
                       "karaoke (una palabra grande cada vez, sincronizada con la voz) y se "
                       "pega el audio. MoviePy une todo y exporta el .mp4 final, en formato "
                       "vertical (reel 1080×1920) u horizontal (YouTube 1920×1080)."},
            {"easy": "Sube el vídeo a YouTube (si lo pides o está en automático).",
             "tech": "mp4 → YouTube Data API v3 (OAuth) → URL del vídeo", "file": "pipeline/publishers.py",
             "detail": "Usa el permiso OAuth ya guardado para publicar el vídeo en tu "
                       "canal con el título y descripción generados. En modo práctica se "
                       "sube como privado. Si la subida falla, el vídeo no se pierde: queda "
                       "en la biblioteca para subirlo a mano."},
        ],
    },
    {
        "id": "create",
        "title": "Crear → texto multiplataforma",
        "easy": "Escribe publicaciones para blog, X, Instagram y LinkedIn sobre un tema.",
        "input": "Tema + público + plataformas elegidas.",
        "output": "Un texto adaptado al formato de cada plataforma.",
        "orchestrator": "pipeline/content_generator.py · generate_freeform()",
        "endpoint": "POST /api/profiles/{id}/content/freeform",
        "steps": [
            {"easy": "Para cada plataforma usa un formato distinto (largo, hashtags…).",
             "tech": "tema → guía por plataforma → LLM (máx. 700 tokens) → texto", "file": "pipeline/content_generator.py",
             "detail": "Cada red social tiene su 'molde': el blog pide 250-400 palabras con "
                       "título; X (Twitter) máx. 280 caracteres con 2-3 hashtags; Instagram "
                       "~150 palabras con 5-8 hashtags; LinkedIn ~120 palabras más formal. "
                       "La app le da al modelo el molde adecuado para cada una y genera el "
                       "texto a medida."},
            {"easy": "Evita inventar datos y aplica el tono de tu marca.",
             "tech": "antepone el 'system_preamble' del perfil + regla 'no fabricar'", "file": "pipeline/content_generator.py",
             "detail": "Antes del prompt se añade la personalidad de tu marca (el "
                       "'system_preamble' del perfil) y una instrucción explícita de no "
                       "inventar hechos, para que el texto suene a ti y sea fiable."},
        ],
    },
    {
        "id": "science",
        "title": "Laboratorio · Ciencia (RAG)",
        "easy": "Explica un tema científico apoyándose en papers reales de arXiv.",
        "input": "Un tema (p. ej. biomecánica del sprint).",
        "output": "Explicación divulgativa basada en papers reales.",
        "orchestrator": "pipeline/tools/arxiv_rag.py · explain()",
        "endpoint": "POST /api/science/explain",
        "steps": [
            {"easy": "Descarga papers de arXiv sobre el tema y los prepara para buscar.",
             "tech": "arXiv → trocea (1000 car./150 solapado) → embeddings bge-small → Chroma", "file": "pipeline/tools/arxiv_rag.py",
             "detail": "La primera vez que consultas un tema, baja hasta 8 artículos de "
                       "arXiv. Los corta en trozos de ~1000 caracteres (con 150 de solape "
                       "para no partir ideas a la mitad). Cada trozo se convierte en "
                       "'embeddings' (números que representan su significado) con el modelo "
                       "bge-small, y se guardan en Chroma, una base de datos que busca por "
                       "significado. Esto se hace una vez y queda cacheado."},
            {"easy": "Recupera los fragmentos más relevantes para tu pregunta.",
             "tech": "pregunta → busca los 4 trozos más parecidos (+ grafo opcional)", "file": "pipeline/tools/graph_rag.py",
             "detail": "Tu tema se convierte también en embeddings y se buscan en Chroma "
                       "los 4 trozos de texto cuyo significado más se le parece. Si activas "
                       "el 'grafo', además se extraen relaciones entre conceptos (A "
                       "'causa' B) y se añaden como contexto extra para una explicación más "
                       "conectada."},
            {"easy": "Redacta la explicación basándose SOLO en lo recuperado.",
             "tech": "trozos recuperados → LLM divulgador (máx. 900 tokens)", "file": "pipeline/tools/arxiv_rag.py",
             "detail": "Se le pasan al modelo únicamente los fragmentos recuperados y se "
                       "le pide explicar el tema de forma divulgativa usando solo esa "
                       "información. Como se apoya en papers reales (no en su memoria), la "
                       "explicación está fundamentada y no inventada."},
        ],
    },
    {
        "id": "finance",
        "title": "Laboratorio · Finanzas",
        "easy": "Da un resumen de bolsa de una empresa con precio y titulares.",
        "input": "Un ticker (p. ej. AAPL, NVDA).",
        "output": "Precio, variación del día y titulares recientes.",
        "orchestrator": "pipeline/tools/finance.py · market_summary()",
        "endpoint": "POST /api/finance/news",
        "steps": [
            {"easy": "Pide el precio actual; si falla, usa una fuente de respaldo.",
             "tech": "Finnhub /quote → si no hay dato, yfinance", "file": "pipeline/tools/finance.py",
             "detail": "Primero pregunta el precio a Finnhub. Si Finnhub no tiene el dato "
                       "(o no hay clave), recurre a yfinance (Yahoo Finanzas), que no "
                       "necesita clave, y calcula la variación del día comparando con el "
                       "cierre anterior."},
            {"easy": "Trae los titulares recientes de la empresa.",
             "tech": "Finnhub /company-news → 5 titulares (vacío sin clave)", "file": "pipeline/tools/finance.py",
             "detail": "Pide a Finnhub las 5 noticias más recientes de la empresa y las "
                       "añade bajo el precio. Si no hay clave de Finnhub, simplemente no "
                       "muestra titulares (el precio sigue funcionando) en vez de fallar."},
        ],
    },
    {
        "id": "agents",
        "title": "Laboratorio · Agentes (LangGraph)",
        "easy": "Un 'jefe' decide qué experto responde tu petición y delega en él.",
        "input": "Una petición en lenguaje libre.",
        "output": "La respuesta del agente experto más adecuado.",
        "orchestrator": "agents/graph.py · route_request()",
        "endpoint": "POST /api/agents/route",
        "steps": [
            {"easy": "El router lee tu petición y elige UN experto.",
             "tech": "supervisor (LLM, temperatura 0) → delega a un agente", "file": "agents/graph.py",
             "detail": "LangGraph permite construir varios 'agentes' (mini-asistentes con "
                       "un rol) coordinados por un 'supervisor'. El supervisor lee tu "
                       "petición y, con temperatura 0 (respuesta determinista, sin "
                       "creatividad), decide a qué único experto enviarla."},
            {"easy": "Deportes / Social escriben texto; Ciencia y Finanzas usan herramientas.",
             "tech": "create_react_agent: sports, social, science(arXiv), finance(Finnhub)", "file": "agents/graph.py",
             "detail": "Hay 4 expertos: 'sports' (contenido de fútbol), 'social' (copys "
                       "para redes), 'science' (puede usar la herramienta de arXiv para "
                       "fundamentarse) y 'finance' (usa la herramienta de Finnhub para dar "
                       "cifras reales). Un agente 'react' puede decidir por sí mismo cuándo "
                       "llamar a su herramienta antes de responder."},
            {"easy": "Devuelve la respuesta del experto elegido.",
             "tech": "último mensaje del grafo → resultado", "file": "agents/graph.py",
             "detail": "Cuando el experto termina, el supervisor recoge su respuesta y la "
                       "devuelve como resultado final. Tú solo escribes la petición; toda "
                       "la coordinación ocurre por debajo."},
        ],
    },
]


def describe() -> dict:
    """The full architecture map for the /api/architecture endpoint."""
    return {"services": SERVICES, "flows": FLOWS}
