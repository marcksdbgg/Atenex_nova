<br># Atenex Nova

**Plataforma local de memoria documental y RAG de nueva generación**

<p align="center">
  <em>Sistema de memoria con varios motores de acceso — no un chatbot con vectores.</em>
</p>

---

## ¿Qué es Atenex Nova?

Atenex Nova permite que una organización cargue documentos locales, construya una **memoria documental estructurada** y responda preguntas con:

- 🎯 **Grounding real** sobre evidencia local
- 📎 **Citas a spans concretos** en los documentos fuente
- 🔀 **Modos de recuperación** adaptados al tipo de pregunta
- 📄 **Soporte fuerte** para documentos complejos (PDFs, tablas, layouts)
- 🏠 **Operación 100% local** sin dependencia obligatoria de nube

---

## Arquitectura

Atenex Nova se implementa como un **Modular Monolith + Local Engines** usando Hexagonal Architecture, DDD liviano y principios SOLID.

### Stack tecnológico

| Capa              | Tecnología                                       |
| ----------------- | ------------------------------------------------ |
| **Backend**       | Python · FastAPI · SQLAlchemy/SQLModel · Pydantic v2 |
| **Frontend**      | React · TypeScript · Vite                        |
| **Base de datos** | PostgreSQL / SQLite                              |
| **Vector DB**     | Qdrant (dense + sparse + RRF + reranking)        |
| **Parser**        | Docling (parsing estructural de documentos)      |
| **Generador**     | Gemma 4 E4B / E2B (via llama.cpp / Ollama)       |
| **Embeddings**    | EmbeddingGemma (308M, MRL truncable 768→128d)    |
| **Visual**        | ColPali (recuperación visual de páginas)          |

### Subsistemas

```
┌──────────────────────────────────────────────────────────────┐
│                        ATENEX NOVA                           │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   Corpus     │  Document    │   Memory     │   Query        │
│  Management  │ Understanding│ Construction │ Intelligence   │
├──────────────┼──────────────┼──────────────┼────────────────┤
│  Retrieval   │  Reasoning   │  Evaluation  │   UI           │
│   Engine     │ & Answering  │   System     │  (React)       │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

### Modos de consulta

| Modo              | Cuándo se usa                                     |
| ----------------- | ------------------------------------------------- |
| `exact`           | Códigos, nombres propios, fechas, IDs             |
| `factual_local`   | Preguntas puntuales sobre pocos fragmentos        |
| `multi_hop`       | Conectar piezas de información dispersas          |
| `global`          | Visión de conjunto o síntesis del corpus           |
| `argumentative`   | Tensión o conflicto entre fuentes                 |
| `visual`          | Tablas, layouts complejos, documentos escaneados  |

---

## Requisitos del sistema

### Perfiles de hardware

| Perfil     | RAM    | Generador       | Embeddings         | Notas                     |
| ---------- | ------ | --------------- | ------------------- | ------------------------- |
| **Lite**   | 8 GB   | Gemma 4 E2B     | EmbeddingGemma 256d | Sin índice visual permanente |
| **Standard** | 16 GB | Gemma 4 E4B    | EmbeddingGemma 384d | Grafo proposicional completo |
| **Advanced** | 32 GB+ | Gemma 4 26B/31B | EmbeddingGemma 768d | Todos los índices activos  |

### Software requerido

- **Python** ≥ 3.11
- **Node.js** ≥ 20 LTS
- **Docker Desktop** (para Qdrant y PostgreSQL)
- **Git**

---

## Inicio rápido

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd Atenex_nova
```

### 2. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Servicios locales

```bash
# Qdrant (vector DB)
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage qdrant/qdrant

# LLM runtime (ejemplo con llama.cpp)
llama-server -m models/gemma-4-e4b.gguf --port 8080 --ctx-size 8192
```

### 5. Ejecutar

```bash
# API
cd backend
uvicorn atenex_nova.main:app --reload --port 8000

# UI
cd frontend
npm run dev
```

---

## Estructura del proyecto

```
Atenex_nova/
├── AGENTS.md                    # Referencia para agentes IA
├── README.md                    # Este archivo
├── .gitignore
├── docker-compose.yml           # Orquestación de servicios locales
│
├── backend/                     # Python backend
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/                 # Migraciones de DB
│   └── atenex_nova/             # Paquete principal
│       ├── main.py
│       ├── config.py
│       ├── presentation/        # Routers, DTOs, mappers
│       ├── application/         # Use cases, orchestrators, policies
│       ├── domain/              # Entidades, VOs, agregados, eventos, repos
│       ├── infrastructure/      # Adaptadores (DB, Qdrant, LLM, Docling...)
│       ├── workers/             # Jobs de procesamiento
│       ├── evaluation/          # Benchmarks, golden sets
│       └── shared/              # Config, logging, excepciones, utils
│
├── frontend/                    # React + TypeScript UI
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/          # Componentes reutilizables
│       ├── pages/               # Vistas de pantalla
│       ├── services/            # API client
│       ├── stores/              # Estado global
│       ├── hooks/               # Custom hooks
│       ├── types/               # TypeScript types
│       └── styles/              # CSS global y design system
│
├── docs/                        # Documentación
│   ├── plan.md                  # Arquitectura maestro
│   └── baseline.md              # Diseño baseline
│
├── prompts/                     # Plantillas de prompts versionadas
├── scripts/                     # Scripts de utilidad
└── tests/                       # Tests globales y e2e
```

---

## Pipeline de ingesta

```
Documento → Parsing (Docling) → Normalización → Segmentación en capas
    ├── Vista A: Spans estructurales (párrafos, secciones, tablas)
    ├── Vista B: Chunks de recuperación (embeddings + sparse)
    ├── Vista C: Proposiciones/claims (afirmaciones atómicas)
    └── Vista D: Resúmenes jerárquicos (sección → documento → colección)
```

## Pipeline de consulta

```
Pregunta → Preprocesamiento → Clasificación → Routing → Recuperación
    → Fusión + Reranking → Evidence Pack → Síntesis → Verificación → Respuesta
```

---

## API Endpoints principales

| Método | Ruta                                | Descripción                  |
| ------ | ----------------------------------- | ---------------------------- |
| POST   | `/collections`                      | Crear colección              |
| GET    | `/collections`                      | Listar colecciones           |
| POST   | `/collections/{id}/documents`       | Subir documentos             |
| GET    | `/documents/{id}/structure`         | Árbol documental             |
| POST   | `/queries/search`                   | Búsqueda sin respuesta       |
| POST   | `/queries/answer`                   | Pregunta completa con RAG    |
| GET    | `/answers/{id}`                     | Respuesta persistida         |
| POST   | `/evaluation/runs`                  | Ejecutar benchmark           |
| GET    | `/jobs`                             | Estado de jobs               |

---

## Documentación

- [Plan maestro de arquitectura](docs/plan.md)
- [Diseño baseline](docs/baseline.md)
- [AGENTS.md](AGENTS.md) — Referencia para sub-agentes IA

---

## Licencia

Pendiente de definir.

---

<p align="center">
  <strong>Atenex Nova</strong> — Plataforma local de memoria documental de nueva generación
</p>
