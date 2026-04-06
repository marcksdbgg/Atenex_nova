# Documento maestro de arquitectura de software

## Atenex Nova — Plataforma local de memoria documental y RAG de nueva generación

Este documento redefine Atenex como una **plataforma local de comprensión documental**, no como un chatbot con vectores. La base del rediseño es clara: el Atenex del PDF ya acertó en tres cosas importantes —local-first, retrieval híbrido y trazabilidad—, pero también mostró tres cuellos de botella que no conviene heredar tal cual: dependencia excesiva de una síntesis secuencial tipo Map-Reduce, parsing insuficiente para PDFs/tablas/documentos complejos y una arquitectura de recuperación todavía demasiado centrada en chunks planos. Además, el propio PDF muestra que el re-ranking pesa mucho en la calidad final, lo que confirma que el nuevo diseño debe priorizar la memoria externa y la calidad del retrieval por encima de “hacer crecer” el generador.  

La nueva versión se apoya en tecnologías abiertas y actuales: **Gemma 4** como familia generativa principal, **EmbeddingGemma** como embedding local de baja huella, **Qdrant** como motor de recuperación híbrida y multivector, **Docling** para parsing estructural, **GraphRAG** como inspiración para búsquedas locales/globales/DRIFT, **ToPG** para recuperación por proposiciones y **ColPali** para recuperación visual de páginas cuando el layout del documento importa. Gemma 4 se presenta como familia abierta orientada desde dispositivos edge hasta workstations, con modos de razonamiento, contexto amplio y capacidades multimodales; EmbeddingGemma soporta más de 100 idiomas, dimensiones truncables de 768 a 128 mediante MRL y ejecución con menos de 200 MB de RAM cuantizado; Qdrant ya documenta búsqueda híbrida dense+sparse, RRF y reranking con late interaction; Docling está orientado explícitamente a dejar documentos “listos para GenAI”; GraphRAG distingue Local Search, Global Search y DRIFT; y ColPali recupera páginas como imágenes preservando layout, tablas y gráficos. ([Google AI for Developers][1])

---

## 1) Objetivo del producto

Atenex Nova debe permitir que una organización cargue documentos locales, construya una memoria documental estructurada y responda preguntas con:

* grounding real sobre evidencia local,
* citas a spans concretos,
* distintos modos de recuperación según el tipo de pregunta,
* soporte fuerte para documentos complejos,
* operación completa sin dependencia obligatoria de nube.

No se diseña como “single prompt over top-k chunks”.
Se diseña como **sistema de memoria con varios motores de acceso**.

---

## 2) Principios rectores de arquitectura

### 2.1. Local-first real

Todo lo esencial vive y corre localmente: parseo, embeddings, índices, recuperación, síntesis, verificación y UI.

### 2.2. Document understanding antes que vectorización

Primero se entiende la estructura del documento; luego se indexa.

### 2.3. Retrieval multimodal y multicapa

La memoria no será una sola colección de chunks. Habrá memoria por:

* estructura documental,
* pasajes,
* proposiciones,
* resúmenes jerárquicos,
* páginas visuales.

### 2.4. Query routing antes de generación

El sistema decide primero **cómo buscar**; recién después decide **cómo responder**.

### 2.5. El generador no memoriza; sintetiza

Gemma 4 no será “la base de conocimiento”; será el motor de composición y explicación sobre evidencia ya curada.

### 2.6. Modular monolith como estilo inicial

Se implementa como monolito modular con workers internos y motores externos locales.
No microservicios al inicio.

### 2.7. POO estricta y hexagonal

La solución se organiza por capas:

* `presentation`
* `application`
* `domain`
* `infrastructure`
* `workers`
* `evaluation`

---

## 3) Decisiones tecnológicas obligatorias

### 3.1. Lenguaje y runtime

**Lenguaje principal:** Python
**Razón:** ecosistema dominante para Docling, Transformers, Qdrant client, pipelines de embeddings, orquestación local y evaluación.

**Framework API:** FastAPI
**Razón:** tipado fuerte con Pydantic, buen DX, async nativo, OpenAPI automático.

**Modelado de datos:** Pydantic v2 + SQLAlchemy/SQLModel
**Razón:** DTOs claros y persistencia limpia.

**Interfaz de usuario:** React + TypeScript
**Razón:** separación clara entre UI y backend, componentes reutilizables y facilidad para visor de citas, árbol documental y paneles de evidencia.

**Base relacional:** PostgreSQL como recomendación; SQLite como perfil mínimo de despliegue.

**Vector DB:** Qdrant local/self-hosted. Qdrant documenta soporte para dense+sparse, RRF y pipelines con reranking/late interaction, por lo que encaja mejor que una combinación artesanal de FAISS + BM25. ([Qdrant][2])

### 3.2. Runtime de inferencia generativa

**Primario:** `llama.cpp server`
**Secundario compatible:** `Ollama`

Motivo:

* Google documenta que Gemma puede correrse localmente con `llama.cpp` y `Ollama` incluso en laptops sin GPU.
* `llama.cpp` ofrece control fino de GGUF, contexto, cache y parámetros.
* `Ollama` sirve como rampa rápida de desarrollo y entorno de pruebas. ([Google AI for Developers][3])

### 3.3. Modelos generativos

**Modelo principal recomendado:** `Gemma 4 E4B`
**Fallback liviano:** `Gemma 4 E2B`
**Perfil edge alternativo:** `Gemma 3n`

Google describe Gemma 4 como familia abierta orientada a edge, laptops, workstations, razonamiento, coding y multimodalidad, con contexto amplio; Gemma 3n está optimizada específicamente para dispositivos cotidianos. ([Google AI for Developers][4])

### 3.4. Embeddings

**Modelo obligatorio:** `EmbeddingGemma`

Configuración recomendada por perfil:

* `128d` para pruebas y colecciones pequeñas
* `256d` para perfil mínimo
* `384d` para perfil estándar
* `768d` para máxima calidad

EmbeddingGemma soporta más de 100 idiomas, dimensiones truncables de 768 a 128 con Matryoshka Representation Learning, contexto de entrada suficiente para documentos y ejecución cuantizada muy liviana. ([Google AI for Developers][5])

### 3.5. Parsing documental

**Parser principal:** `Docling`

Docling está orientado a preparar documentos para GenAI y su ecosistema documentado cubre parsing de PDF y comprensión avanzada; además, sus repositorios y proyectos asociados muestran soporte para múltiples formatos y una representación estructurada unificada. ([GitHub][6])

### 3.6. Recuperación visual de documentos

**Componente opcional pero recomendado:** `ColPali`

ColPali trata cada página como imagen y genera embeddings multivectoriales con late interaction, preservando layout, tablas y gráficos mejor que una tubería centrada solo en OCR/texto extraído. ([Hugging Face][7])

### 3.7. Estrategias conceptuales de recuperación

**Global/temática:** GraphRAG
**Proposicional/multi-hop:** ToPG
**Memoria no paramétrica:** HippoRAG 2
**Control de distracción:** LDAR

Estas líneas de trabajo son valiosas porque ya no se conforman con top-k chunks: GraphRAG separa búsquedas locales, globales y DRIFT; ToPG modela un grafo heterogéneo de proposiciones, entidades y pasajes; HippoRAG 2 mejora memoria factual, asociativa y de sentido; y LDAR optimiza la recuperación contra pasajes distractores. ([Microsoft GitHub][8])

---

## 4) Estilo arquitectónico

Atenex Nova se implementa como **Modular Monolith + Local Engines**.

### 4.1. Qué significa aquí

Un solo producto desplegable, pero con límites de módulo estrictos y contratos internos formales.

### 4.2. Procesos físicos recomendados

* `atenex-api`
* `atenex-worker`
* `atenex-ui`
* `qdrant`
* `postgres` o `sqlite` según perfil
* `llm-runtime` (`llama.cpp server` o `ollama`)
* `docling-runtime` embebido o como módulo del worker

### 4.3. Comunicación entre procesos

* UI ↔ API: HTTP/JSON
* API ↔ Worker: job table + dispatcher interno
* API/Worker ↔ Qdrant: cliente oficial
* API/Worker ↔ DB: ORM + SQL
* API ↔ LLM runtime: HTTP local
* Worker ↔ embedding runtime: llamada local Python
* Worker ↔ Docling: invocación local

No se usará cola distribuida externa al inicio.
El job orchestration será local y controlado por base de datos + worker runner.

---

## 5) Arquitectura lógica completa

## 5.1. Capa de presentación

### Módulos

* `WebApp`
* `DesktopShell` opcional
* `CLI`

### Responsabilidades

* carga de archivos
* creación de colecciones
* ejecución de preguntas
* visualización de respuesta y citas
* visor de documento con resaltado de spans
* vista de estructura del documento
* vista de evidencias
* vista de jobs
* vista de evaluación

---

## 5.2. Capa de aplicación

### Módulos

* `IngestionApplicationService`
* `QueryApplicationService`
* `CollectionApplicationService`
* `DocumentApplicationService`
* `EvaluationApplicationService`
* `JobApplicationService`

### Responsabilidades

* orquestar casos de uso
* validar comandos
* emitir eventos de dominio
* coordinar servicios de infraestructura

---

## 5.3. Capa de dominio

### Núcleos de dominio

* `Corpus`
* `Document`
* `DocumentStructure`
* `RetrievalMemory`
* `QueryPlan`
* `EvidencePack`
* `Answer`
* `Citation`
* `Evaluation`

### Reglas principales

* un documento no se consulta hasta estar indexado
* un chunk debe rastrear su origen estructural
* una proposición debe referenciar chunk y documento de origen
* una respuesta no se publica sin citas válidas
* todo modo de respuesta debe declarar su plan de consulta

---

## 5.4. Capa de infraestructura

### Adaptadores

* `DoclingParserAdapter`
* `EmbeddingGemmaAdapter`
* `LlamaCppGeneratorAdapter`
* `OllamaGeneratorAdapter`
* `QdrantHybridIndexAdapter`
* `SqlDocumentRepository`
* `SqlQueryRepository`
* `FileBlobRepository`
* `ColPaliRetrieverAdapter`

---

## 5.5. Capa de workers

### Workers

* `IngestionWorker`
* `EmbeddingWorker`
* `IndexWorker`
* `SummaryWorker`
* `GraphWorker`
* `EvaluationWorker`

---

## 6) Arquitectura por subsistemas

## 6.1. Subsystem A — Corpus Management

### Objetivo

Administrar colecciones, documentos y estado del corpus.

### Componentes

* `CollectionManager`
* `DocumentRegistry`
* `BlobStoreService`
* `DocumentLifecycleManager`

### Estados de documento

* `registered`
* `parsed`
* `normalized`
* `segmented`
* `embedded`
* `indexed`
* `ready`
* `failed`

---

## 6.2. Subsystem B — Document Understanding

### Objetivo

Convertir archivos heterogéneos en una representación estructurada útil para IA.

### Pipeline

1. parseo
2. normalización
3. segmentación
4. extracción de proposiciones
5. extracción de entidades/conceptos
6. summaries

### Artefactos generados

* árbol documental
* nodos por bloque
* chunks de retrieval
* proposiciones
* summaries de sección
* summaries de documento
* summaries de colección

---

## 6.3. Subsystem C — Memory Construction

### Objetivo

Construir la memoria consultable.

### Índices

* índice denso de chunks
* índice sparse de chunks
* índice denso de proposiciones
* índice de summaries
* índice visual de páginas
* tablas de relaciones semánticas

### Resultado

El sistema no tendrá una sola “base vectorial”, sino varias memorias especializadas.

---

## 6.4. Subsystem D — Query Intelligence

### Objetivo

Entender la pregunta y elegir la mejor ruta.

### Componentes

* `QueryNormalizer`
* `QueryLanguageDetector`
* `QueryIntentClassifier`
* `QueryRouter`
* `QueryExpander`

### Modos de consulta

* `exact`
* `factual_local`
* `multi_hop`
* `global`
* `argumentative`
* `visual`

---

## 6.5. Subsystem E — Retrieval Engine

### Objetivo

Recuperar evidencia útil con la menor distracción posible.

### Etapas

1. recuperación primaria
2. fusión dense+sparse
3. expansión opcional por grafo
4. reranking
5. pruning anti-distracción
6. armado del evidence pack

---

## 6.6. Subsystem F — Reasoning & Answering

### Objetivo

Convertir evidencia curada en respuesta trazable.

### Etapas

1. plan de respuesta
2. síntesis directa o jerárquica
3. verificación
4. binding de citas
5. serialización de respuesta

---

## 6.7. Subsystem G — Evaluation

### Objetivo

Medir la calidad del sistema y permitir regresión controlada.

### Componentes

* `GoldenSetManager`
* `ScenarioRunner`
* `AnswerScorer`
* `RetrievalScorer`
* `RegressionComparator`

---

# 7) Modelo de dominio

## 7.1. Entidades principales

### `Collection`

Representa un corpus lógico.

Campos:

* `id`
* `name`
* `description`
* `language_profile`
* `default_generation_profile`
* `default_retrieval_profile`

### `Document`

Representa el archivo fuente y su ciclo de vida.

Campos:

* `id`
* `collection_id`
* `title`
* `source_path`
* `mime_type`
* `checksum`
* `status`
* `language`
* `version`

### `DocumentNode`

Representa un bloque estructural del documento.

Campos:

* `id`
* `document_id`
* `parent_id`
* `node_type`
* `page_number`
* `order_index`
* `raw_text`
* `normalized_text`
* `layout_bbox`
* `metadata_json`

### `RetrievalChunk`

Unidad principal de recuperación textual.

Campos:

* `id`
* `document_id`
* `node_ids`
* `text`
* `summary`
* `token_count`
* `embedding_ref`
* `sparse_ref`

### `Proposition`

Afirmación atómica derivada de uno o más chunks.

Campos:

* `id`
* `document_id`
* `source_chunk_id`
* `text`
* `kind`
* `embedding_ref`

### `SummaryNode`

Resumen jerárquico.

Campos:

* `id`
* `scope_type`
* `scope_id`
* `text`
* `embedding_ref`

### `RelationEdge`

Relación semántica.

Campos:

* `id`
* `source_type`
* `source_id`
* `target_type`
* `target_id`
* `relation`
* `weight`

### `Query`

Representa una consulta del usuario.

Campos:

* `id`
* `collection_id`
* `text`
* `normalized_text`
* `language`
* `intent`
* `route_mode`

### `EvidenceItem`

Una pieza de evidencia seleccionada.

Campos:

* `id`
* `query_id`
* `source_type`
* `source_id`
* `score`
* `rank`
* `citation_candidate`

### `Answer`

Respuesta final.

Campos:

* `id`
* `query_id`
* `plan_type`
* `text`
* `grounding_score`
* `verdict`
* `created_at`

### `Citation`

Span exacto de respaldo.

Campos:

* `id`
* `answer_id`
* `document_id`
* `page_number`
* `node_id`
* `char_start`
* `char_end`
* `snippet`

---

## 7.2. Value Objects

* `DocumentId`
* `CollectionId`
* `NodePath`
* `VectorRef`
* `SparseRef`
* `GenerationProfile`
* `RetrievalProfile`
* `CitationSpan`
* `QueryMode`
* `AnswerVerdict`

---

## 7.3. Aggregate roots

* `Collection`
* `Document`
* `Query`
* `Answer`

---

# 8) Diseño POO completo

La solución usa **Hexagonal Architecture + DDD liviano + SOLID**.

## 8.1. Capas POO

### `presentation`

DTOs, routers, view models.

### `application`

use cases, command handlers, query handlers.

### `domain`

entidades, agregados, servicios de dominio, eventos.

### `infrastructure`

repositorios concretos, adaptadores de IA, adaptadores DB, adaptadores vectoriales.

### `workers`

consumidores de jobs.

---

## 8.2. Interfaces base

```python
from typing import Protocol, Iterable, Sequence

class Parser(Protocol):
    def parse(self, file_path: str) -> "ParsedDocument": ...

class Normalizer(Protocol):
    def normalize(self, parsed: "ParsedDocument") -> "NormalizedDocument": ...

class Segmenter(Protocol):
    def segment(self, normalized: "NormalizedDocument") -> "SegmentationResult": ...

class PropositionExtractor(Protocol):
    def extract(self, chunks: Sequence["RetrievalChunk"]) -> Sequence["Proposition"]: ...

class Embedder(Protocol):
    def embed_texts(self, texts: Sequence[str], profile: "EmbeddingProfile") -> Sequence[list[float]]: ...

class SparseEncoder(Protocol):
    def encode(self, texts: Sequence[str]) -> Sequence["SparseVector"]: ...

class HybridIndex(Protocol):
    def upsert_chunks(self, chunks: Sequence["IndexedChunk"]) -> None: ...
    def query(self, request: "HybridQuery") -> Sequence["RetrievalCandidate"]: ...

class VisualRetriever(Protocol):
    def upsert_pages(self, pages: Sequence["PageImage"]) -> None: ...
    def query(self, request: "VisualQuery") -> Sequence["RetrievalCandidate"]: ...

class GraphStore(Protocol):
    def upsert_nodes(self, nodes: Sequence["GraphNode"]) -> None: ...
    def upsert_edges(self, edges: Sequence["GraphEdge"]) -> None: ...
    def expand(self, seed_ids: Sequence[str], mode: str) -> Sequence["GraphHit"]: ...

class Generator(Protocol):
    def generate(self, prompt: "GenerationPrompt", profile: "GenerationProfile") -> "GenerationResult": ...

class Verifier(Protocol):
    def verify(self, answer: "DraftAnswer", evidence: "EvidencePack") -> "VerificationResult": ...
```

---

## 8.3. Clases de dominio

```python
class Collection:
    def __init__(self, id, name, description, language_profile, generation_profile, retrieval_profile): ...
    def rename(self, new_name: str) -> None: ...
    def update_profiles(self, generation_profile, retrieval_profile) -> None: ...

class Document:
    def __init__(self, id, collection_id, title, source_path, mime_type, checksum, status): ...
    def mark_parsed(self): ...
    def mark_normalized(self): ...
    def mark_segmented(self): ...
    def mark_indexed(self): ...
    def fail(self, reason: str): ...

class DocumentNode:
    def __init__(self, id, document_id, parent_id, node_type, page_number, order_index, raw_text, normalized_text): ...
    def is_textual(self) -> bool: ...
    def is_tabular(self) -> bool: ...

class RetrievalChunk:
    def __init__(self, id, document_id, node_ids, text, summary, token_count): ...
    def as_index_payload(self) -> dict: ...

class Proposition:
    def __init__(self, id, document_id, source_chunk_id, text, kind): ...
    def as_graph_node(self) -> "GraphNode": ...

class Query:
    def __init__(self, id, collection_id, text, normalized_text, language, intent, route_mode): ...
    def switch_route(self, new_mode): ...

class EvidencePack:
    def __init__(self, query, items, contradictions, summaries, route_mode): ...
    def prune(self): ...
    def group_by_document(self): ...
    def group_by_theme(self): ...

class Answer:
    def __init__(self, id, query_id, plan_type, text, grounding_score, verdict): ...
    def attach_citations(self, citations): ...
```

---

## 8.4. Servicios de aplicación

```python
class IngestionApplicationService:
    def register_document(self, command: "RegisterDocumentCommand") -> "DocumentRegisteredResult": ...
    def start_ingestion(self, document_id: str) -> None: ...

class QueryApplicationService:
    def ask(self, command: "AskQueryCommand") -> "AnswerDto": ...
    def search_only(self, command: "SearchQueryCommand") -> "SearchResultsDto": ...

class EvaluationApplicationService:
    def run_benchmark(self, command: "RunBenchmarkCommand") -> "BenchmarkRunDto": ...
```

---

## 8.5. Orquestadores clave

```python
class IngestionOrchestrator:
    def execute(self, document_id: str) -> None: ...

class RetrievalOrchestrator:
    def execute(self, query: Query) -> EvidencePack: ...

class AnswerOrchestrator:
    def execute(self, query: Query, evidence: EvidencePack) -> Answer: ...
```

---

## 8.6. Servicios de infraestructura

```python
class DoclingParserAdapter(Parser): ...
class EmbeddingGemmaAdapter(Embedder): ...
class BM25SparseEncoder(SparseEncoder): ...
class QdrantHybridIndexAdapter(HybridIndex): ...
class SqlGraphStore(GraphStore): ...
class LlamaCppGeneratorAdapter(Generator): ...
class OllamaGeneratorAdapter(Generator): ...
class ColPaliRetrieverAdapter(VisualRetriever): ...
class RuleBasedVerifier(Verifier): ...
```

---

## 8.7. Políticas y estrategias

```python
class QueryRoutingPolicy:
    def choose_mode(self, features: "QueryFeatures") -> str: ...

class ContextPackingPolicy:
    def build(self, candidates, token_budget_profile) -> EvidencePack: ...

class AnswerPlanningPolicy:
    def choose_plan(self, evidence_pack: EvidencePack) -> str: ...
```

---

# 9) Estructura de paquetes

```text
atenex_nova/
  presentation/
    api/
      routers/
      dto/
      mappers/
    web/
      viewmodels/
  application/
    commands/
    queries/
    services/
    orchestrators/
    policies/
    handlers/
  domain/
    entities/
    value_objects/
    aggregates/
    services/
    events/
    repositories/
  infrastructure/
    db/
      models/
      repositories/
      migrations/
    qdrant/
    llm/
    embeddings/
    parsing/
    visual/
    graph/
    cache/
    files/
  workers/
    jobs/
    runners/
    handlers/
  evaluation/
    datasets/
    scorers/
    regression/
  shared/
    config/
    logging/
    exceptions/
    utils/
  tests/
    unit/
    integration/
    e2e/
    golden/
```

---

# 10) Modelo de datos persistente

## 10.1. Tablas relacionales

### `collections`

* id
* name
* description
* language_profile
* generation_profile_json
* retrieval_profile_json

### `documents`

* id
* collection_id
* title
* source_path
* mime_type
* checksum
* status
* language
* version
* created_at
* updated_at

### `document_nodes`

* id
* document_id
* parent_id
* node_type
* page_number
* order_index
* raw_text
* normalized_text
* bbox_json
* metadata_json

### `retrieval_chunks`

* id
* document_id
* summary
* text
* token_count
* node_ids_json
* embedding_ref
* sparse_ref

### `propositions`

* id
* document_id
* source_chunk_id
* text
* kind
* embedding_ref

### `summary_nodes`

* id
* scope_type
* scope_id
* text
* embedding_ref

### `relation_edges`

* id
* source_type
* source_id
* target_type
* target_id
* relation
* weight

### `queries`

* id
* collection_id
* original_text
* normalized_text
* language
* intent
* route_mode
* created_at

### `answers`

* id
* query_id
* plan_type
* text
* grounding_score
* verdict
* created_at

### `citations`

* id
* answer_id
* document_id
* page_number
* node_id
* char_start
* char_end
* snippet

### `jobs`

* id
* job_type
* target_id
* state
* payload_json
* result_json
* error_json

---

## 10.2. Qdrant collections

### `chunks_hybrid`

Campos:

* dense vector
* sparse vector
* payload:

  * document_id
  * collection_id
  * page_number
  * node_ids
  * chunk_id
  * text
  * summary
  * language

### `propositions_dense`

Campos:

* dense vector
* payload:

  * proposition_id
  * document_id
  * source_chunk_id
  * kind
  * text

### `summaries_dense`

Campos:

* dense vector
* payload:

  * summary_id
  * scope_type
  * scope_id
  * text

### `pages_visual`

Campos:

* multivector visual
* payload:

  * document_id
  * page_number
  * image_path
  * page_text_preview

Qdrant documenta dense+sparse y también escenarios con reranking multivector y late interaction, por lo que esta separación encaja bien con su modelo operativo. ([Qdrant][9])

---

# 11) Pipeline de ingesta completo

## 11.1. Caso de uso

El usuario carga un archivo o un lote de archivos.

## 11.2. Secuencia completa

```text
UI -> API: upload document
API -> DB: create document(status=registered)
API -> Jobs: enqueue ingestion job

Worker -> BlobStore: read file
Worker -> Parser: parse file
Worker -> DB: store structured nodes
Worker -> Normalizer: normalize nodes
Worker -> Segmenter: create retrieval chunks
Worker -> PropositionExtractor: create propositions
Worker -> Summarizer: create summaries
Worker -> Embedder: embed chunks/propositions/summaries
Worker -> SparseEncoder: encode chunks
Worker -> HybridIndex: upsert chunks
Worker -> HybridIndex: upsert propositions
Worker -> HybridIndex: upsert summaries
Worker -> VisualRetriever: upsert pages (optional)
Worker -> GraphStore: upsert nodes/edges
Worker -> DB: mark document ready
```

## 11.3. Reglas de ingesta

* no indexar documento si el parseo falla
* no generar proposiciones sobre nodos vacíos
* no resumir páginas antes de normalizar
* toda proposición debe guardar origen
* todo chunk debe enlazar a nodos estructurales
* toda página visual debe poder reabrirse desde UI

## 11.4. Estrategias de segmentación

### Segmentación estructural primaria

Basada en árbol documental:

* heading
* paragraph
* list
* table
* caption
* footnote

### Segmentación de retrieval

Agrupación de nodos cercanos bajo reglas:

* coherencia semántica
* continuidad estructural
* tamaño textual razonable
* preservación de contexto de tablas

### Segmentación proposicional

Extracción de:

* hechos
* definiciones
* procedimientos
* reglas
* relaciones causales
* comparaciones

### Segmentación global

Generación de resúmenes por:

* sección
* documento
* colección
* comunidad temática

---

# 12) Pipeline de consulta completo

## 12.1. Caso de uso

El usuario hace una pregunta sobre una colección.

## 12.2. Secuencia completa

```text
UI -> API: ask question
API -> QueryPreprocessor: normalize/language-detect/feature-extract
API -> QueryRouter: choose route_mode
API -> RetrievalOrchestrator: execute route
RetrievalOrchestrator -> Qdrant: dense/sparse/summary query
RetrievalOrchestrator -> GraphStore: graph expansion if needed
RetrievalOrchestrator -> VisualRetriever: visual retrieval if needed
RetrievalOrchestrator -> Reranker: rerank candidates
RetrievalOrchestrator -> ContextBuilder: build evidence pack

API -> AnswerPlanner: choose synthesis mode
API -> Generator: generate answer draft
API -> Verifier: verify grounding/citations
API -> CitationBinder: bind spans
API -> DB: persist answer/citations
API -> UI: return answer + evidence + citations
```

---

## 12.3. Query preprocessing

### Extracción de features

* idioma
* presencia de nombres propios
* presencia de fechas/códigos
* signos de comparación
* signos de contradicción
* amplitud temática
* referencia a tabla/imagen/página

### Clasificación de intención

* exacta
* factual
* comparativa
* explicativa
* argumentativa
* global
* visual

---

## 12.4. Query routing

### `exact`

Se usa cuando la pregunta depende de tokens exactos.

Motores:

* sparse dominante
* dense auxiliar

### `factual_local`

Se usa cuando la respuesta vive en pocos fragmentos.

Motores:

* dense chunks
* sparse chunks
* reranking

### `multi_hop`

Se usa cuando hay que conectar piezas.

Motores:

* chunks
* propositions
* expansión de grafo

### `global`

Se usa cuando la pregunta pide visión de conjunto.

Motores:

* summaries
* comunidades
* DRIFT/global expansion

GraphRAG documenta que Global Search opera sobre comunidades resumidas y que DRIFT amplía el punto de partida local con información comunitaria. ([Microsoft GitHub][10])

### `argumentative`

Se usa cuando hay tensión o conflicto entre fuentes.

Motores:

* chunks
* propositions
* agrupación support/contradict

### `visual`

Se usa cuando hay tablas, layouts o scans relevantes.

Motores:

* ColPali visual pages
* chunks textuales como apoyo

ColPali está pensado precisamente para recuperación visual de documentos por página, incluyendo layout, tablas y charts. ([Hugging Face][7])

---

## 12.5. Recuperación primaria

### Dense retrieval

EmbeddingGemma sobre:

* consulta
* chunks
* propositions
* summaries

### Sparse retrieval

BM25 o sparse encoder léxico sobre:

* chunks
* titles
* headers

### Summary retrieval

Busca resúmenes:

* de documento
* de colección
* de comunidad

### Graph expansion

Expande desde:

* proposiciones semilla
* entidades
* pasajes

ToPG demuestra que una ruta por proposiciones, entidades y pasajes mejora preguntas complejas, con modos naive, local y global. ([arXiv][11])

---

## 12.6. Fusión y reranking

### Fusión

* dense + sparse
* RRF por defecto
* DBSF opcional futuro

Qdrant documenta RRF y score fusion sobre consultas híbridas. ([Qdrant][2])

### Reranking

Dos niveles:

**Nivel 1**

* reranker textual liviano

**Nivel 2**

* late interaction / multivector reranking cuando la consulta lo justifica

Qdrant documenta pipelines con dense, sparse y reranking con ColBERT/late interaction. ([Qdrant][9])

---

## 12.7. Control de distracción

Componente: `DistractionAwareContextBuilder`

Reglas:

* quitar duplicados semánticos
* limitar redundancia por documento
* priorizar cobertura temática
* excluir pasajes periféricos
* equilibrar evidencia exacta y explicativa

LDAR muestra precisamente que la calidad no depende solo de “más contexto”, sino de reducir pasajes distractores y equilibrar cobertura con interferencia. ([arXiv][12])

---

## 12.8. Construcción del evidence pack

Contenido:

* consulta original
* consulta normalizada
* subpreguntas derivadas si aplica
* evidencia principal
* evidencia secundaria
* resúmenes relevantes
* contradicciones detectadas
* budget estructural del prompt
* candidatos de cita

---

# 13) Arquitectura de generación

## 13.1. Planner

El `AnswerPlanner` decide uno de estos planes:

* `direct_answer`
* `hierarchical_synthesis`
* `global_synthesis`
* `argument_synthesis`
* `visual_grounded_synthesis`

## 13.2. Direct answer

Se usa cuando el evidence pack es pequeño, claro y sin conflicto.

## 13.3. Hierarchical synthesis

Se usa cuando hay muchos grupos de evidencia.
Aquí sí entra un Map-Reduce, pero como **estrategia especializada**, no como default del sistema.

## 13.4. Global synthesis

Opera sobre summaries y comunidades, al estilo GraphRAG global.

## 13.5. Argument synthesis

Estructura de salida:

* posición A
* evidencia A
* posición B
* evidencia B
* síntesis

## 13.6. Visual grounded synthesis

Se apoya primero en página visual recuperada y luego en spans textuales.

---

## 13.7. Prompting interno

No se usa un prompt monolítico único.
Se usan plantillas por plan:

* `DIRECT_ANSWER_PROMPT`
* `HIERARCHICAL_MAP_PROMPT`
* `HIERARCHICAL_REDUCE_PROMPT`
* `GLOBAL_SYNTHESIS_PROMPT`
* `ARGUMENT_SYNTHESIS_PROMPT`
* `VISUAL_GROUNDED_PROMPT`
* `VERIFICATION_PROMPT`

Cada plantilla debe inyectar:

* consulta
* evidence pack
* formato de salida
* política de incertidumbre
* obligación de cita

---

## 13.8. Runtime generativo

### Implementación recomendada

* `llama.cpp server` como primario
* modelo GGUF de Gemma 4 E4B/E2B
* `OllamaAdapter` como compatibilidad

Google documenta Gemma con integraciones locales como Ollama y llama.cpp. ([Google AI for Developers][3])

---

# 14) Arquitectura de verificación y citas

## 14.1. Verificación

El `Verifier` debe comprobar:

* que cada cita corresponda a un span real
* que el claim generado tenga respaldo
* que no haya afirmaciones sin evidencia
* que la respuesta no omita contradicción relevante
* que el plan usado sea consistente con la evidencia

## 14.2. Citation binding

`CitationBinder` toma:

* answer draft
* evidence pack
* spans candidatos

y devuelve:

* answer final con citas inline
* lista de citas para panel lateral
* resaltados para visor de documento

## 14.3. Render final

La respuesta debe salir como:

1. respuesta principal
2. puntos clave
3. citas inline
4. panel de fuentes
5. vista opcional de conflicto o incertidumbre

---

# 15) API completa

## 15.1. Colecciones

### `POST /collections`

Crear colección.

### `GET /collections`

Listar colecciones.

### `GET /collections/{id}`

Detalle.

### `PATCH /collections/{id}`

Actualizar perfiles.

---

## 15.2. Documentos

### `POST /collections/{id}/documents`

Subir documentos.

### `GET /collections/{id}/documents`

Listar documentos.

### `GET /documents/{id}`

Detalle.

### `GET /documents/{id}/structure`

Árbol documental.

### `GET /documents/{id}/pages/{page}`

Datos de página.

### `GET /documents/{id}/chunks`

Chunks.

### `GET /documents/{id}/propositions`

Proposiciones.

---

## 15.3. Jobs

### `POST /jobs/ingest/{document_id}`

Disparar ingesta.

### `GET /jobs`

Listar jobs.

### `GET /jobs/{id}`

Detalle.

---

## 15.4. Consulta

### `POST /queries/search`

Modo búsqueda sin respuesta generada.

**Request**

```json
{
  "collection_id": "col_001",
  "query": "¿Qué contradicciones hay sobre X?",
  "mode": "auto"
}
```

**Response**

```json
{
  "query_id": "q_001",
  "route_mode": "argumentative",
  "hits": []
}
```

### `POST /queries/answer`

Pregunta completa.

**Request**

```json
{
  "collection_id": "col_001",
  "query": "¿Qué contradicciones hay sobre X?",
  "mode": "auto",
  "generation_profile": "standard"
}
```

**Response**

```json
{
  "answer_id": "ans_001",
  "route_mode": "argumentative",
  "plan_type": "argument_synthesis",
  "text": "...",
  "citations": [],
  "evidence": [],
  "grounding_score": 0.0
}
```

### `GET /answers/{id}`

Traer respuesta persistida.

---

## 15.5. Evaluación

### `POST /evaluation/runs`

Crear corrida.

### `GET /evaluation/runs/{id}`

Resultado.

### `GET /evaluation/reports/{id}`

Reporte agregado.

---

# 16) Job system completo

## 16.1. Tipos de job

* `parse_document`
* `normalize_document`
* `segment_document`
* `extract_propositions`
* `embed_chunks`
* `embed_propositions`
* `embed_summaries`
* `index_chunks`
* `index_visual_pages`
* `build_graph`
* `run_benchmark`
* `rebuild_collection`

## 16.2. Máquina de estados

* `pending`
* `running`
* `succeeded`
* `failed`
* `cancelled`

## 16.3. Dependencias de jobs

Un job no corre hasta que su dependencia termine.

Ejemplo:
`index_chunks` depende de `embed_chunks`.

## 16.4. Retries

Solo para fallos transitorios de runtime o I/O.
No para parseos estructuralmente inválidos.

---

# 17) UI completa

## 17.1. Pantallas

* Dashboard
* Collections
* Documents
* Document Detail
* Document Structure
* Query Workspace
* Evidence Inspector
* Answer History
* Jobs
* Evaluation Reports

## 17.2. Componentes UI

* `CollectionSidebar`
* `DocumentTable`
* `DocumentTree`
* `QueryInput`
* `AnswerPanel`
* `CitationSidebar`
* `EvidenceCard`
* `PageViewer`
* `ChunkInspector`
* `PropositionGraphView`
* `JobStatusBadge`
* `EvaluationReportView`

## 17.3. Experiencia de consulta ideal

Panel central:

* pregunta
* respuesta
* citas inline

Panel derecho:

* fuentes relevantes
* scores
* spans citados

Panel inferior:

* ruta usada
* plan de respuesta
* modo de consulta
* evidencias excluidas opcionales

---

# 18) Modelos y perfiles operativos

## 18.1. Perfiles generativos

### `lite`

* Gemma 4 E2B
* síntesis directa preferente
* menos expansión global

### `standard`

* Gemma 4 E4B
* perfil por defecto

### `advanced`

* Gemma 4 26B/31B si la máquina lo soporta

Gemma 4 diferencia claramente despliegues E2B/E4B para edge y laptops, y tamaños mayores para workstations/GPUs de consumo. ([Google AI for Developers][4])

## 18.2. Perfiles de embedding

### `lite`

* EmbeddingGemma 256d

### `standard`

* EmbeddingGemma 384d

### `max`

* EmbeddingGemma 768d

EmbeddingGemma permite truncación de dimensiones vía MRL sin cambiar de backbone. ([Google AI for Developers][5])

## 18.3. Perfil visual

### `off`

sin índice visual

### `on_demand`

extrae e indexa visualmente solo documentos marcados

### `full`

indexa todas las páginas complejas

---

# 19) Organización de conexiones y comunicaciones

## 19.1. UI ↔ API

HTTP/JSON síncrono.

## 19.2. API ↔ Dominio

Llamadas en memoria dentro del monolito modular.

## 19.3. API ↔ Worker

Comunicación vía repositorio de jobs y dispatcher.

## 19.4. Worker ↔ Infraestructura

* DB por ORM
* Qdrant por client SDK
* llama.cpp/Ollama por HTTP local
* Docling por llamada Python local

## 19.5. Eventos internos

No broker externo al inicio.
Se usan eventos de dominio persistidos:

* `DocumentRegistered`
* `DocumentParsed`
* `DocumentSegmented`
* `DocumentIndexed`
* `QueryReceived`
* `EvidencePackBuilt`
* `AnswerGenerated`
* `AnswerVerified`

---

# 20) Organización del código y reglas de desarrollo

## 20.1. Reglas base

* no mezclar dominio con infraestructura
* no permitir que routers llamen directamente a adapters
* todo caso de uso pasa por Application Service
* todo acceso a almacenamiento pasa por Repository
* todo modelo externo pasa por Gateway/Adapter
* todo DTO se separa de entidades de dominio
* todo cambio de estado del documento debe ser explícito

## 20.2. Convenciones

* nombres de clases en singular
* nombres de services orientados a verbo
* nombres de repositorios orientados a aggregate
* configs separadas por perfil
* prompts versionados
* migrations explícitas
* pruebas por capa

---

# 21) Evaluación y calidad

## 21.1. Qué se mide

### Retrieval

* Recall@k
* MRR
* nDCG
* coverage temática

### Answering

* grounding
* relevancia
* exactitud
* contradicción detectada/no detectada
* utilidad percibida

### Sistema

* estabilidad
* memoria
* tamaño de índices
* regresión entre versiones

El Atenex original ya mostró que evaluar solo el generador no basta y que el reranking impacta mucho la fidelidad; por eso la nueva evaluación debe partir por retrieval y evidence quality. 

## 21.2. Tipos de prueba

* unitarias
* integración
* contract tests
* golden set
* end-to-end
* benchmark de corpus real

## 21.3. Golden sets

Cada colección importante debe tener:

* preguntas exactas
* preguntas multi-hop
* preguntas globales
* preguntas con contradicción
* preguntas basadas en tablas
* preguntas de layout complejo

---

# 22) Observabilidad técnica

Aunque quitamos seguridad, no quitamos observabilidad.

## 22.1. Logging

* logs por módulo
* logs por query_id
* logs por job_id
* logs por document_id

## 22.2. Métricas

* documentos procesados
* jobs exitosos/fallidos
* tamaño de índices
* proporción de rutas de consulta
* grounding score promedio
* tasa de regeneración post-verificación

## 22.3. Trazabilidad técnica

Cada respuesta debe poder reconstruirse por:

* query_id
* route_mode
* retrieval candidates
* evidence pack
* prompt version
* generation profile
* citations

---

# 23) Fases de implementación

Sin medidas de tiempo, solo orden lógico y criterio de salida.

## Fase 1 — Fundación del repositorio y núcleo arquitectónico

### Incluye

* estructura de paquetes
* FastAPI
* React base
* ORM
* repositorios
* sistema de jobs
* configuración por perfiles
* adapters vacíos

### Salida esperada

* proyecto compilable
* API arrancando
* UI arrancando
* base de datos inicial
* contratos internos definidos

---

## Fase 2 — Ingesta estructural

### Incluye

* upload de documentos
* BlobStore
* integración Docling
* normalización
* árbol documental
* almacenamiento de nodos

### Salida esperada

* documentos parseables
* estructura navegable desde UI
* jobs de parseo estables

---

## Fase 3 — Memoria textual base

### Incluye

* chunking estructural
* EmbeddingGemma
* sparse encoder
* Qdrant dense+sparse
* búsqueda híbrida básica

### Salida esperada

* búsqueda textual híbrida funcional
* resultados relevantes por colección
* chunks citables

---

## Fase 4 — Memoria enriquecida

### Incluye

* extracción de proposiciones
* summaries jerárquicos
* relaciones semánticas
* almacenamiento de grafo lógico

### Salida esperada

* consultas por proposiciones
* summaries consultables
* grafo navegable internamente

---

## Fase 5 — Query intelligence

### Incluye

* preprocesamiento de consulta
* clasificación de intención
* router
* evidence pack builder
* pruning anti-distracción

### Salida esperada

* auto-routing funcional
* evidence packs por modo
* reducción visible de ruido contextual

---

## Fase 6 — Generación y verificación

### Incluye

* runtime Gemma 4
* planner de respuesta
* síntesis directa/jerárquica/global/argumentativa
* verificación
* citation binding

### Salida esperada

* respuestas trazables
* citas inline
* panel de fuentes funcional

---

## Fase 7 — Ruta visual

### Incluye

* extracción de páginas complejas
* integración ColPali
* visual retrieval
* visual grounded synthesis

### Salida esperada

* consultas sobre tablas/layout/escaneos
* evidencia visual recuperable

---

## Fase 8 — Evaluación formal

### Incluye

* datasets internos
* golden sets
* scoring retrieval
* scoring answering
* reportes de regresión

### Salida esperada

* tablero de calidad
* comparación entre perfiles y modos
* criterios claros de aceptación

---

## Fase 9 — Hardening funcional

### Incluye

* pulido de UI
* tolerancia a fallos de jobs
* rebuilds de colección
* exportes de resultados
* documentación de operación

### Salida esperada

* producto instalable
* operación repetible
* guía de despliegue local

---

# 24) Qué se conserva del Atenex original y qué se descarta

## Se conserva

* local-first
* trazabilidad
* retrieval híbrido como base
* foco en hardware de consumo
* idea de monolito modular desplegable
* prioridad del retrieval sobre el tamaño del modelo

Eso está alineado con lo que el PDF demostró: el re-ranking pesa mucho en la calidad y el diseño local es el valor central del producto.  

## Se descarta o reemplaza

* chunking semántico plano como corazón del sistema
* FAISS/BM25 como núcleo suelto sin memoria multicapa
* Map-Reduce como default universal
* dependencia exclusiva de retrieval por pasajes
* parsing textual insuficiente para layout complejo

El PDF ya identificó explícitamente problemas con Map-Reduce lineal y con documentos complejos, por lo que heredarlos sin rediseño sería un error. 

---

# 25) Resultado final esperado

El producto final no será “Atenex con otro modelo”.
Será esto:

* un sistema local completo,
* una memoria documental multicapa,
* con router de consulta,
* con retrieval híbrido + proposicional + global + visual,
* con Gemma 4 como motor de síntesis,
* con EmbeddingGemma como backbone semántico liviano,
* con Docling como base de comprensión documental,
* con Qdrant como motor unificado de recuperación,
* con citas reales a spans,
* y con arquitectura lista para desarrollar sin rehacer el diseño central.

---

# 26) Resumen ejecutivo ultra corto

**Stack base**

* Backend: Python + FastAPI + SQLAlchemy/SQLModel
* UI: React + TypeScript
* DB: PostgreSQL / SQLite
* Vector DB: Qdrant
* Parser: Docling
* Generator: Gemma 4
* Embeddings: EmbeddingGemma
* Visual retrieval: ColPali
* Runtime LLM: llama.cpp server
* Architecture style: modular monolith + workers

**Motor conceptual**

* hybrid RAG
* proposition graph retrieval
* summary/community retrieval
* DRIFT/global retrieval
* distraction-aware context assembly
* answer planning
* verification
* citation binding

**Fases**

* fundación
* ingesta
* memoria textual
* memoria enriquecida
* query intelligence
* generación/verificación
* visual
* evaluación
* hardening

---

[1]: https://ai.google.dev/gemma/docs/core/model_card_4?utm_source=chatgpt.com "Gemma 4 model card | Google AI for Developers"
[2]: https://qdrant.tech/documentation/search/hybrid-queries/?utm_source=chatgpt.com "Hybrid and Multi-Stage Queries"
[3]: https://ai.google.dev/gemma/docs/integrations/ollama "https://ai.google.dev/gemma/docs/integrations/ollama"
[4]: https://ai.google.dev/gemma/docs/core/model_card_4 "https://ai.google.dev/gemma/docs/core/model_card_4"
[5]: https://ai.google.dev/gemma/docs/embeddinggemma?utm_source=chatgpt.com "EmbeddingGemma model overview - Google AI for Developers"
[6]: https://github.com/docling-project/docling?utm_source=chatgpt.com "docling-project/docling: Get your documents ready for gen AI"
[7]: https://huggingface.co/docs/transformers/model_doc/colpali?utm_source=chatgpt.com "ColPali"
[8]: https://microsoft.github.io/graphrag/query/local_search/?utm_source=chatgpt.com "Local Search - GraphRAG"
[9]: https://qdrant.tech/documentation/tutorials-search-engineering/reranking-hybrid-search/?utm_source=chatgpt.com "Hybrid Search with Reranking"
[10]: https://microsoft.github.io/graphrag/query/global_search/?utm_source=chatgpt.com "Global Search - GraphRAG"
[11]: https://arxiv.org/abs/2601.04859 "https://arxiv.org/abs/2601.04859"
[12]: https://arxiv.org/abs/2509.21865 "https://arxiv.org/abs/2509.21865"
