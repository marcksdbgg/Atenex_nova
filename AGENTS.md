# AGENTS.md — Atenex Nova

> **Última actualización:** 2026-04-06
> **Estado del proyecto:** Fase 0 — Planificación y estructura

---

## 1. Descripción del Proyecto

**Atenex Nova** es una plataforma local de memoria documental y RAG de nueva generación.
No es un chatbot con vectores; es un **sistema de memoria con varios motores de acceso**
que permite a una organización cargar documentos locales, construir una memoria documental
estructurada y responder preguntas con grounding real, citas a spans concretos,
distintos modos de recuperación según el tipo de pregunta y soporte fuerte para
documentos complejos — todo sin dependencia obligatoria de nube.

---

## 2. Entorno de Desarrollo

| Aspecto               | Detalle                                          |
| ---------------------- | ------------------------------------------------ |
| **SO**                 | Windows 11 (local)                               |
| **Shell**              | PowerShell                                       |
| **Ruta del proyecto**  | `G:\Atenex\Atenex_nova`                          |
| **Asistente IA**       | Antigravity (Google DeepMind)                    |
| **Control de versión** | Git (repositorio local inicializado)             |
| **Python**             | ≥ 3.11 (recomendado 3.12)                       |
| **Node.js**            | ≥ 20 LTS                                        |
| **Docker**             | Docker Desktop for Windows (requerido para Qdrant) |

---

## 3. Stack Tecnológico

### 3.1 Backend (Python)

| Componente          | Tecnología                          | Rol                                         |
| ------------------- | ----------------------------------- | -------------------------------------------- |
| Framework API       | **FastAPI**                         | API REST async con tipado Pydantic           |
| ORM / Modelos       | **SQLAlchemy 2 + SQLModel**         | Persistencia relacional con DTOs limpios     |
| Base de datos       | **PostgreSQL** / SQLite (perfil min)| Metadata, jobs, citas, historial             |
| Migraciones         | **Alembic**                         | Control de esquema                           |
| Tasks/Jobs          | Job table + dispatcher interno      | Orquestación local sin cola externa          |
| Validación          | **Pydantic v2**                     | DTOs, configs, schemas                       |
| Testing             | **pytest** + pytest-asyncio         | Unit, integration, e2e                       |
| Linting/Format      | **Ruff**                            | Linter + formatter unificado                 |
| Type checking       | **mypy** (strict)                   | Verificación estática                        |

### 3.2 Frontend (React + TypeScript)

| Componente          | Tecnología                          | Rol                                         |
| ------------------- | ----------------------------------- | -------------------------------------------- |
| Framework           | **Vite + React 19 + TypeScript**    | SPA con HMR rápido                           |
| Gestión de estado   | **Zustand** o **TanStack Query**    | Estado global + server state                 |
| Estilos             | **Vanilla CSS** (design system)     | Máximo control, sin dependencia de utility fw|
| Routing             | **React Router v7**                 | Navegación SPA                               |
| HTTP Client         | **fetch** nativo / Axios            | Comunicación con API                         |
| Testing             | **Vitest + Testing Library**        | Unit + component tests                       |

### 3.3 IA / ML (Local-first)

| Componente              | Tecnología                   | Rol                                          |
| ------------------------ | ---------------------------- | -------------------------------------------- |
| Modelo generativo        | **Gemma 4 E4B** (GGUF)      | Síntesis, razonamiento, verificación         |
| Modelo generativo lite   | **Gemma 4 E2B** (GGUF)      | Perfil liviano                               |
| Runtime LLM              | **llama.cpp server**         | Inferencia local con control fino            |
| Runtime LLM alt          | **Ollama**                   | Rampa rápida de desarrollo                   |
| Embeddings               | **EmbeddingGemma** (308M)   | Embedding multilingüe con MRL truncable      |
| Vector DB                | **Qdrant** (Docker)          | Dense + sparse + RRF + reranking             |
| Parser documental        | **Docling**                  | Parsing estructural de PDF/DOCX/HTML/PPTX    |
| Retrieval visual         | **ColPali** (opcional)       | Recuperación de páginas como imágenes         |

### 3.4 Infraestructura local

| Componente          | Tecnología                          |
| ------------------- | ----------------------------------- |
| Contenedores        | **Docker + Docker Compose**         |
| DB para desarrollo  | **SQLite** (perfil inicial)         |
| DB para producción  | **PostgreSQL** (Docker)             |
| Qdrant              | **qdrant/qdrant** (Docker, puerto 6333) |

---

## 4. Arquitectura

**Estilo:** Modular Monolith + Local Engines
**Patrón:** Hexagonal Architecture + DDD liviano + SOLID

### Capas del backend

```
atenex_nova/
├── presentation/    → Routers FastAPI, DTOs, mappers
├── application/     → Use cases, commands, queries, orchestrators, policies
├── domain/          → Entidades, value objects, agregados, eventos, repositorios (interfaces)
├── infrastructure/  → Adaptadores concretos (DB, Qdrant, LLM, embeddings, Docling, ColPali)
├── workers/         → Consumidores de jobs (ingesta, embedding, indexación, grafos)
├── evaluation/      → Datasets, scorers, regresión
└── shared/          → Config, logging, excepciones, utils
```

### Procesos físicos

1. `atenex-api` — FastAPI server
2. `atenex-worker` — Worker de jobs
3. `atenex-ui` — React dev server / build estático
4. `qdrant` — Motor vectorial (Docker)
5. `postgres` / `sqlite` — Base relacional
6. `llm-runtime` — llama.cpp server o Ollama

---

## 5. Subsistemas Principales

| ID | Subsistema              | Descripción                                           |
| -- | ----------------------- | ----------------------------------------------------- |
| A  | Corpus Management       | Colecciones, documentos, ciclo de vida                |
| B  | Document Understanding  | Parsing, normalización, segmentación, proposiciones   |
| C  | Memory Construction     | Índices densos, sparse, proposicionales, visuales     |
| D  | Query Intelligence      | Preprocesamiento, clasificación, routing              |
| E  | Retrieval Engine        | Recuperación híbrida, fusión, reranking, pruning       |
| F  | Reasoning & Answering   | Planificación, síntesis, verificación, citas          |
| G  | Evaluation              | Golden sets, scoring, regresión                       |

---

## 6. Fases de Desarrollo

| Fase | Nombre                        | Estado         |
| ---- | ----------------------------- | -------------- |
| 0    | Planificación y estructura    | ✅ En progreso |
| 1    | Fundación del repositorio     | 🔲 Pendiente   |
| 2    | Ingesta estructural           | 🔲 Pendiente   |
| 3    | Memoria textual base          | 🔲 Pendiente   |
| 4    | Memoria enriquecida           | 🔲 Pendiente   |
| 5    | Query Intelligence            | 🔲 Pendiente   |
| 6    | Generación y verificación     | 🔲 Pendiente   |
| 7    | Ruta visual                   | 🔲 Pendiente   |
| 8    | Evaluación formal             | 🔲 Pendiente   |
| 9    | Hardening funcional           | 🔲 Pendiente   |

---

## 7. Convenciones de Código

### Python

- **Formatter/Linter:** Ruff (line-length=100)
- **Type hints:** obligatorios en interfaces públicas
- **Docstrings:** Google style
- **Imports:** absolutos desde `atenex_nova.*`
- **Nombres:** clases en singular, services orientados a verbo, repos a aggregate
- **Configs:** separadas por perfil (`dev`, `test`, `prod`)
- **Prompts:** versionados en archivos separados

### TypeScript / React

- **Strict mode** habilitado
- **Componentes:** funcionales con hooks
- **Estilos:** CSS Modules o archivos `.css` por componente
- **Naming:** PascalCase para componentes, camelCase para funciones y variables

### Git

- **Branching:** `main` → `develop` → `feature/*`, `fix/*`
- **Commits:** mensajes descriptivos en español o inglés, con prefijo de fase

---

## 8. Reglas Arquitectónicas (para sub-agentes)

1. **No mezclar dominio con infraestructura.** El dominio NO importa de infra.
2. **No permitir que routers llamen directamente a adapters.** Siempre via Application Service.
3. **Todo caso de uso pasa por Application Service.**
4. **Todo acceso a almacenamiento pasa por Repository (interfaz en domain, impl en infra).**
5. **Todo modelo externo pasa por Gateway/Adapter.**
6. **Todo DTO se separa de entidades de dominio.**
7. **Todo cambio de estado del documento debe ser explícito** (máquina de estados).
8. **Las dependencias se inyectan**, no se instancian dentro de los servicios.
9. **Los tests se organizan por capa** (unit/, integration/, e2e/, golden/).

---

## 9. Documentación de Referencia

| Documento                  | Ruta                                |
| -------------------------- | ----------------------------------- |
| Plan maestro de arquitectura | `docs/plan.md`                    |
| Diseño baseline            | `docs/baseline.md`                 |
| Plan de implementación     | Artefacto en Antigravity            |
| Este archivo               | `AGENTS.md` (raíz del proyecto)    |

---

## 10. Comandos Frecuentes

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
uvicorn atenex_nova.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev                    # Vite dev server en :5173

# Qdrant
docker run -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant

# llama.cpp server (ejemplo)
llama-server -m models/gemma-4-e4b.gguf --port 8080 --ctx-size 8192

# Tests
cd backend && pytest tests/ -v
cd frontend && npm test
```
