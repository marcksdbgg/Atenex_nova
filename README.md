# Atenex Nova

**Plataforma local de memoria documental y RAG de nueva generación**

<p align="center">
  <em>Sistema de memoria con varios motores de acceso, no un chatbot con vectores.</em>
</p>

---

## Estado verificado del workspace

Este README refleja el checkout actual del repositorio, no solo la visión del producto.

| Check | Resultado | Nota |
| --- | --- | --- |
| OpenAPI/docs contract | 1 passed | `backend/.venv/Scripts/python.exe -m pytest tests/unit/test_openapi_documentation_contract.py -q` |
| Backend unit tests | 1 failed, 43 passed | `tests/unit/test_answer_orchestrator_llm.py::test_compose_includes_all_selected_evidence_in_prompt` falla por citas vacías |
| Frontend build | failed | `src/pages/Pages.tsx` usa `run.cases`, campo ausente en `EvaluationRunResponse` |
| Frontend lint | failed | `src/components/PageViewer.tsx` dispara `react-hooks/set-state-in-effect` |
| Backend `ruff` | 6 issues | Deuda existente de formato/imports; la nueva prueba de contrato queda limpia |
| Backend `mypy` | 5 errors | Deuda existente en Qdrant, embeddings y visual adapter |
| Integration / e2e | presentes | Existen, pero dependen de runtimes locales y no se revalidaron en esta pasada |

La fuente canónica del gap restante sigue siendo [docs/final-gap-inventory.md](docs/final-gap-inventory.md).

---

## Qué es Atenex Nova

Atenex Nova es una plataforma local-first para cargar documentos, construir memoria documental estructurada y responder preguntas con grounding real. La idea no es "otro chatbot con vectores", sino un sistema con varios motores de acceso:

- búsqueda híbrida dense + sparse
- recuperación por proposiciones y resúmenes
- routing por tipo de pregunta
- soporte visual para páginas complejas
- verificación antes de entregar una respuesta
- trazabilidad de evidencia y citas

La implementación actual sigue una arquitectura modular monolítica con backend FastAPI, jobs asíncronos, persistencia relacional, Qdrant para recuperación híbrida y un frontend React/Vite orientado a workspace operativo.

---

## Qué está implementado hoy

Hoy el repositorio ya incluye, de forma operativa:

- routers FastAPI para `health`, `collections`, `documents`, `queries`, `answers`, `jobs`, `observability` y `evaluation`
- ingesta de documentos con parsing estructural, normalización, segmentación, embeddings y enriquecimiento posterior
- memoria persistida para chunks, proposiciones, resúmenes, relaciones, citas, queries, answers y jobs
- recuperación híbrida con EmbeddingGemma como embedding local por defecto y búsqueda sparse local/BM25
- routing de consulta por modos `exact`, `factual_local`, `multi_hop`, `global`, `argumentative` y `visual`
- generación de respuesta con plan de síntesis, verificación y persistencia de grounding
- exportes de respuesta a Markdown y PDF
- observabilidad de pipeline y estado de jobs
- UI de workspace para colecciones, consulta, observabilidad, evaluación y jobs

---

## Arquitectura actual

Atenex Nova se organiza como un **Modular Monolith + Hexagonal Architecture**.

| Capa | Responsabilidad |
| --- | --- |
| `presentation` | Routers FastAPI, DTOs y respuestas HTTP |
| `application` | Servicios, orquestadores, políticas y casos de uso |
| `domain` | Entidades, value objects, contratos y reglas del dominio |
| `infrastructure` | DB, archivos, Docling, embeddings, Qdrant, LLM, visual |
| `workers` | Procesamiento asíncrono por jobs |
| `evaluation` | Datasets, runs y métricas de regresión |
| `shared` | Configuración, logging, errores y utilidades |

### Stack tecnológico

| Capa | Tecnología |
| --- | --- |
| Backend | Python, FastAPI, SQLAlchemy async, SQLModel, Pydantic v2 |
| DB relacional | PostgreSQL o SQLite |
| Vector DB | Qdrant |
| Parser | Docling |
| Generación | Gemma 4 vía Ollama o llama.cpp |
| Embeddings | EmbeddingGemma |
| Visual | ColPali-style visual retrieval |
| Frontend | React, TypeScript, Vite |

### Entry points principales

- API: [backend/atenex_nova/main.py](backend/atenex_nova/main.py)
- Wiring de dependencias: [backend/atenex_nova/dependencies.py](backend/atenex_nova/dependencies.py)
- Worker: [backend/atenex_nova/workers/main.py](backend/atenex_nova/workers/main.py)
- Dispatcher de jobs: [backend/atenex_nova/workers/runner.py](backend/atenex_nova/workers/runner.py)
- Shell frontend: [frontend/src/App.tsx](frontend/src/App.tsx)
- Páginas frontend: [frontend/src/pages/Pages.tsx](frontend/src/pages/Pages.tsx)

---

## Modelo de datos y almacenamiento

La persistencia actual combina SQLModel + almacenamiento local + Qdrant.

### En SQL viven, entre otros:

- collections
- documents
- structural nodes
- chunks
- propositions
- summaries
- citations
- queries
- answers
- jobs
- relation edges
- pipeline audits
- evaluation runs y cases

### Almacenamiento local

- uploads: `backend/storage/uploads/{collection_id}/{document_id}/{filename}`
- visual pages: `backend/storage/visual_pages/`

### Qdrant

La recuperación está namespaceada por corpus. El patrón actual usa colecciones por documento/colección para chunks, proposiciones, resúmenes y páginas visuales.

---

## Pipeline de ingesta

El pipeline real está orientado a document understanding antes que a vectorización rápida.

```text
Documento -> parsing estructural -> normalización -> segmentación
          -> embeddings -> enriquecimiento -> indexación visual -> ready
```

### 1) Recepción

El documento entra por upload, import local o import folder. Se genera metadata de colección, documento, checksum, versión y trazas de proceso.

### 2) Parsing estructural

Se usa Docling para extraer estructura, texto y layout cuando aplica. El sistema persiste nodos estructurales y conserva metadatos útiles para grounding.

### 3) Normalización

Se limpia whitespace, se preservan elementos semánticos relevantes y se preparan nodos para segmentación.

### 4) Segmentación

Se construyen chunks de recuperación sobre la estructura documental, no solo por corte ciego de caracteres.

### 5) Embeddings e indexación

Se embeddean chunks y luego se escribe en Qdrant la representación dense. La capa sparse local complementa para keywords, nombres propios, fechas y códigos.

### 6) Enriquecimiento

El worker extrae proposiciones, genera resúmenes y construye relaciones heurísticas para razonamiento multi-hop.

### 7) Indexación visual

Se preparan páginas visuales para documentos complejos o escaneados y se habilita una ruta visual de recuperación.

### Estados del documento

```text
registered -> parsed -> normalized -> segmented -> embedded -> indexed -> ready
```

---

## Pipeline de consulta

La consulta sigue un flujo de routing y síntesis por etapas.

```text
Pregunta -> normalización -> clasificación -> routing -> retrieval
         -> fusión + rerank -> evidence pack -> síntesis -> verificación -> respuesta
```

### Modos de consulta

- `exact`: códigos, nombres propios, fechas, IDs
- `factual_local`: preguntas puntuales sobre pocos fragmentos
- `multi_hop`: conexión de piezas dispersas
- `global`: visión de conjunto del corpus
- `argumentative`: conflicto o tensión entre fuentes
- `visual`: tablas, layouts complejos o escaneos

### Qué hace el backend en la práctica

- detecta idioma e intención de la consulta
- resuelve el ámbito documental permitido
- combina sparse, dense, summary y visual retrieval
- rerankea y deduplica la evidencia
- arma un evidence pack con presupuesto de tokens
- decide un plan de síntesis
- genera la respuesta con Gemma 4
- verifica grounding y citas antes de persistir la salida

### Salida de la respuesta

La respuesta persistida incluye:

- texto de respuesta
- verdict
- grounding score
- citas
- evidencia asociada
- ruta/mode usado
- metadata de verificación
- exportes disponibles

---

## Frontend y experiencia de usuario

La app frontend ya no es un scaffold vacío; es un workspace operativo.

### Rutas actuales

- `/` -> Dashboard
- `/collections` -> Colecciones
- `/query` -> Espacio de consulta
- `/observability` -> Observabilidad
- `/evaluation` -> Evaluación
- `/jobs` -> Tareas

### Qué muestra el query workspace

- conversation thread
- answer panel
- citation sidebar
- evidence cards
- document tree
- page viewer
- rail de historial / memoria de consultas

### Qué cubren Collections y los demás módulos

- creación de colecciones
- carga de archivos y carpetas locales
- rebuild de una colección
- inspección de estructura y estado documental
- visualización de jobs y audit trail
- runs de evaluación

### API client

El frontend usa un cliente `fetch` fino en [frontend/src/services/api.ts](frontend/src/services/api.ts).

- toma `VITE_API_URL` si existe
- si no existe, resuelve contra `window.location.hostname` en el puerto `8000`
- aplica timeouts por operación
- soporta helpers de paginación para inventarios completos

---

## API surface principal

La lista completa está en [docs/api-endpoints.md](docs/api-endpoints.md). Ese documento se contrasta contra el OpenAPI generado por FastAPI mediante `backend/tests/unit/test_openapi_documentation_contract.py`. Los grupos principales son:

| Método | Ruta | Propósito |
| --- | --- | --- |
| GET | `/health` | Estado básico del servicio |
| GET | `/health/dependencies` | Dependencias activas del runtime |
| POST | `/collections` | Crear colección |
| GET | `/collections` | Listar colecciones |
| GET | `/collections/{id}/documents` | Inventario de documentos con paginación |
| POST | `/collections/{id}/documents` | Subir documento |
| POST | `/collections/{id}/documents/import` | Registrar ruta local |
| POST | `/collections/{id}/documents/import-folder` | Importar carpeta local |
| POST | `/collections/{id}/rebuild` | Reencolar rebuild |
| GET | `/documents/{id}/structure` | Árbol documental |
| GET | `/documents/{id}/nodes` | Nodos estructurales |
| GET | `/documents/{id}/chunks` | Chunks persistidos |
| GET | `/documents/{id}/propositions` | Proposiciones persistidas |
| GET | `/documents/{id}/pages/{page}` | Página visual |
| GET | `/queries/history` | Historial de consultas |
| POST | `/queries/search` | Retrieval sin respuesta |
| POST | `/queries/answer` | Retrieval + síntesis |
| GET | `/answers/{id}` | Respuesta persistida |
| GET | `/answers/{id}/export/markdown` | Exportar Markdown |
| GET | `/answers/{id}/export/pdf` | Exportar PDF |
| GET | `/jobs` | Listar jobs |
| GET | `/observability/audit` | Audit trail |
| GET | `/observability/documents/{id}/evidence` | Evidencia de documento |
| GET | `/evaluation/datasets` | Datasets de evaluación |
| POST | `/evaluation/runs` | Lanzar evaluación |

---

## Requisitos del sistema

### Perfiles de hardware

| Perfil | RAM | Generador | Embeddings | Notas |
| --- | --- | --- | --- | --- |
| Lite | 8 GB | Gemma 4 E2B | EmbeddingGemma 256d | Sin índice visual permanente |
| Standard | 16 GB | Gemma 4 E4B | EmbeddingGemma 384d | Grafo proposicional completo |
| Advanced | 32 GB+ | Gemma 4 26B/31B | EmbeddingGemma 768d | Todos los índices activos |

### Software requerido

- Python >= 3.11
- Node.js >= 20 LTS
- Docker Desktop para Qdrant y PostgreSQL
- Git

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

Si el alias global de Python no está disponible en Windows, usa directamente `backend/.venv/Scripts/python.exe` para instalar y ejecutar comandos del backend.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Servicios locales

```bash
# Qdrant
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage qdrant/qdrant

# LLM runtime por defecto: Ollama + Gemma 4
ollama serve
ollama pull gemma4:e4b

# Verificar modelo disponible
ollama list

# Alternativa: llama.cpp
llama-server -m models/gemma-4-e4b.gguf --port 8080 --ctx-size 8192
```

### 4.1 Verificación rápida de dependencias activas

Con el backend levantado, valida el runtime antes de correr pruebas e2e:

```bash
curl http://127.0.0.1:8000/health/dependencies
```

La respuesta debe reflejar `llm.available=true` cuando Ollama y `gemma4:e4b` estén listos.

### 5. Ejecutar

```bash
# API
cd backend
uvicorn atenex_nova.main:app --reload --port 8000

# Worker
cd backend
python -m atenex_nova.workers.main

# UI
cd frontend
npm run dev
```

---

## Estructura del proyecto

```text
Atenex_nova/
├── AGENTS.md
├── README.md
├── backend/
│   ├── pyproject.toml
│   ├── ruff.toml
│   ├── atenex_nova/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   ├── presentation/
│   │   ├── application/
│   │   ├── domain/
│   │   ├── infrastructure/
│   │   ├── workers/
│   │   ├── evaluation/
│   │   └── shared/
│   └── tests/
├── design-system/
│   └── atenex-nova/
├── docs/
│   ├── baseline.md
│   ├── final-gap-inventory.md
│   └── plan_restante.md
├── frontend/
│   ├── package.json
│   └── src/
├── prompts/
├── scripts/
├── storage/
└── tests/
```

---

## Brechas conocidas

El repo ya está bastante avanzado, pero no está cerrado al 100% contra el baseline. El inventario canónico de brechas sigue siendo [docs/final-gap-inventory.md](docs/final-gap-inventory.md). En este checkout todavía hay deuda visible en:

- un fallo unitario en `AnswerOrchestrator` por citas vacías
- `npm run build` y `npm run lint` del frontend
- `ruff` y `mypy` del backend
- cierre duro del sparse persisted
- reranking más fuerte y medible
- strict mode visual más exigente
- evaluación formal con goldens por modo
- validación e2e completa con runtimes locales activos

---

## Documentación relacionada

- [Inventario final de brechas](docs/final-gap-inventory.md)
- [Diseño baseline](docs/baseline.md)
- [Arquitectura backend](docs/architecture-backend.md)
- [Arquitectura frontend](docs/architecture-frontend.md)
- [API endpoints](docs/api-endpoints.md)
- [Jobs y workers](docs/jobs-and-workers.md)
- [Design system](design-system/atenex-nova/MASTER.md)
- [AGENTS.md](AGENTS.md)

---

## Licencia

Pendiente de definir.

---

<p align="center">
  <strong>Atenex Nova</strong> — Plataforma local de memoria documental de nueva generación
</p>
