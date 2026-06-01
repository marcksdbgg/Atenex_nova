# Auditoría del plan RAG de Atenex Nova + diagramas corregidos

## Base usada para esta auditoría

Esta auditoría se apoya en cinco fuentes que, juntas, sí fijan el estado técnico útil del sistema:

1. **Plan/base RAG**: plantea que Atenex Nova no debe ser “single prompt over top-k chunks”, sino un sistema de memoria documental multicapa, local-first, con `query routing` antes de generación, memoria por estructura/pasajes/proposiciones/resúmenes/páginas visuales y arquitectura hexagonal por capas. fileciteturn4file0
2. **README**: define el stack operativo declarado, los modos de consulta, el monolito modular con motores locales y la estructura general del proyecto. fileciteturn4file3
3. **AGENTS**: fija la precedencia documental, las reglas de arquitectura, los entry points y dónde viven los componentes críticos del backend y frontend. fileciteturn4file2
4. **Inventario final de brechas**: es la fuente canónica del estado real del backend y del gap frente a `baseline.md`; además afirma explícitamente que el snapshot sí inspeccionó orquestadores, policies, routers, repositorios SQL, workers, tests, frontend y prompts. fileciteturn4file1

5. **Contrato OpenAPI/documentación**: `docs/api-endpoints.md` lista la superficie HTTP pública y un test unitario compara esas rutas contra el OpenAPI generado por FastAPI para detectar drift.

## Hallazgo rector

El diseño conceptual del plan es bueno. El problema no está en la visión, sino en el cierre operativo del backend real. El repositorio ya tiene monolito modular, ingesta estructural, memorias multicapa, routing por modo, evidence packing, verificación en dos pasos, viewer visual y health checks; pero sigue incompleto en cuatro puntos que cambian la arquitectura efectiva del pipeline:

- **sparse retrieval persisted real** todavía no está cerrado en el motor principal,
- **reranking fuerte** sigue siendo heurístico,
- **graph expansion** existe pero está por debajo del baseline para multi-hop complejo,
- **ruta visual strict** no está endurecida como contrato de fallo explícito. fileciteturn4file1

Por eso, los diagramas correctos no deben dibujar un sistema “perfecto”, sino uno **real con brechas visibles**.

---

## 1) Arquitectura real del sistema: vista ejecutiva corregida

```mermaid
flowchart LR
    subgraph UI[Frontend React + TypeScript]
        W1[Workspace de consulta]
        W2[Inspector documental]
        W3[Viewer de citas / evidencia visual]
        W4[Diagnóstico de ruta y verificación]
    end

    subgraph API[FastAPI - Modular Monolith]
        P[Presentation\nRouters + DTOs + mappers]
        A[Application\nServices + orchestrators + policies]
        D[Domain\nEntidades + contratos + reglas]
        I[Infrastructure\nSQL + Qdrant + LLM + Docling + visual]
        WK[Workers\nJobs runner + pipelines]
        EV[Evaluation\nGolden sets + runs]
    end

    subgraph DATA[Persistencia local]
        SQL[(PostgreSQL / SQLite)]
        Q[(Qdrant)]
        FS[(Storage local\nuploads + visual_pages)]
    end

    subgraph ENGINES[Motores locales]
        DOC[Docling]
        EMB[EmbeddingGemma]
        LLM[Gemma 4 via Ollama / llama.cpp]
        VIS[Visual retrieval / ColPali-like path]
        BM25[BM25 sparse local]
    end

    UI --> P
    P --> A
    A --> D
    A --> I
    WK --> A
    EV --> A

    I <--> SQL
    I <--> Q
    I <--> FS

    I <--> DOC
    I <--> EMB
    I <--> LLM
    I <--> VIS
    I <--> BM25
```

### Lectura correcta

- El repositorio declara y el inventario confirma un **monolito modular hexagonal** con separación `presentation -> application -> domain -> infrastructure`, workers y evaluation. fileciteturn4file2 fileciteturn4file1
- El **Frontend** ya no es decorativo: el inventario dice que workspace, inspector, citas, evidencia visual y diagnóstico existen y son operativos, aunque faltan estados límite y aceptación e2e completa. fileciteturn4file1
- La arquitectura **real** todavía no es perfectamente hexagonal porque persisten algunos acoplamientos puntuales entre routers, servicios y repositorios. fileciteturn4file1

---

## 2) Flujo de ingesta real: cómo debería leerse hoy

El plan exige entender documento antes de vectorizarlo y construir varias memorias, no una sola colección de chunks. fileciteturn4file0 El README también declara cuatro vistas: spans estructurales, chunks de retrieval, proposiciones y resúmenes jerárquicos. fileciteturn4file3 El inventario confirma que eso existe, pero no completamente cerrado en fidelidad estructural ni en política estricta de chunking por tokens. fileciteturn4file1

```mermaid
flowchart TD
    U[Documento cargado] --> R[registered]
    R --> PARSE[Parsing estructural\nDocling]
    PARSE --> NORM[normalized]
    NORM --> SEG[segment_document\nsegmentación estructural]
    SEG --> SEGSTATE[segmented]

    SEGSTATE --> M1[Memoria estructural\ndocument_nodes]
    SEGSTATE --> M2[Memoria textual\nretrieval_chunks]
    SEGSTATE --> M3[Memoria proposicional\npropositions]
    SEGSTATE --> M4[Memoria de resúmenes\nsummary_nodes]
    SEGSTATE --> M5[Memoria visual\npages + assets]

    M2 --> EMBED[Embeddings dense]
    M2 --> SPARSE[Sparse / BM25]
    M3 --> PGRAPH[Grafo relacional ligero]
    M5 --> VINDEX[Índice visual]

    EMBED --> IDX[indexed]
    SPARSE --> IDX
    PGRAPH --> IDX
    VINDEX --> IDX
    M1 --> READY[ready]
    IDX --> READY

    PARSE -. fallo .-> FAIL[failed]
    NORM -. fallo .-> FAIL
    SEG -. fallo .-> FAIL
    IDX -. fallo .-> FAIL
```

### Lo que está bien

- El inventario confirma el pipeline de estados documentales y la persistencia de nodos, chunks, proposiciones y resúmenes. fileciteturn4file1
- También confirma que existe ruta visual con assets de página y viewer. fileciteturn4file1

### Lo que sigue mal o incompleto

- La **fidelidad al árbol documental** todavía es parcial para layouts complejos, tablas, captions y footnotes. fileciteturn4file1
- La **segmentación** aún no está cerrada como contrato estricto de presupuesto de tokens y trazabilidad nodo→chunk. fileciteturn4file1
- La estabilidad histórica de `segment_document` sigue siendo deuda operativa. fileciteturn4file1

---

## 3) Mapa de memorias: el corazón correcto del sistema

```mermaid
flowchart LR
    DOC[Documento fuente] --> TREE[Árbol documental\nheadings / paragraphs / tables / captions]
    TREE --> CH[Chunks recuperables]
    TREE --> PR[Proposiciones / claims]
    TREE --> SU[Resúmenes jerárquicos]
    TREE --> PG[Páginas visuales]

    CH --> QD[Qdrant dense]
    CH --> SP[Sparse local]
    PR --> GX[Graph expansion]
    SU --> GL[Global retrieval]
    PG --> VR[Visual retrieval]

    TREE --> BIND[Citation binding]
    CH --> BIND
    PR --> BIND
    PG --> BIND
```

### Interpretación

El plan pide explícitamente memoria por estructura documental, pasajes, proposiciones, resúmenes jerárquicos y páginas visuales. fileciteturn4file0 El inventario confirma que las cinco rutas existen en el backend real, aunque con coberturas distintas. fileciteturn4file1

### Estado real por memoria

- **Estructural**: existe, pero no ha probado todavía cobertura contractual total de layouts complejos. fileciteturn4file1
- **Textual**: existe y se usa en runtime. fileciteturn4file1
- **Proposicional**: existe y se consulta, pero su explotación para multi-hop aún puede fortalecerse. fileciteturn4file1
- **Resúmenes jerárquicos**: existen y participan en retrieval global. fileciteturn4file1
- **Visual**: existe, con assets y viewer, pero strict mode no está cerrado. fileciteturn4file1

---

## 4) Pipeline real de consulta: corregido contra el backend actual

El README dibuja un pipeline simple: `Pregunta -> Preprocesamiento -> Clasificación -> Routing -> Recuperación -> Fusión + Reranking -> Evidence Pack -> Síntesis -> Verificación -> Respuesta`. fileciteturn4file3 Eso es útil, pero incompleto para auditar el backend real.

El pipeline correcto hoy es este:

```mermaid
flowchart TD
    Q[Pregunta del usuario] --> PRE[Preprocesamiento\nnormalización + señales léxicas]
    PRE --> ROUTE[Query router\nexact / factual_local / multi_hop / global / argumentative / visual]

    ROUTE -->|exact| EX[Dense + sparse exact-first]
    ROUTE -->|factual_local| FL[Dense local + sparse + pack]
    ROUTE -->|multi_hop| MH[Seeds + graph expansion + pack]
    ROUTE -->|global| GL[Summary retrieval + synthesis plan]
    ROUTE -->|argumentative| AR[Evidence conflict retrieval + contradiction-aware pack]
    ROUTE -->|visual| VI[Visual page retrieval + textual support]

    EX --> FUS[Fusión híbrida]
    FL --> FUS
    MH --> FUS
    GL --> FUS
    AR --> FUS
    VI --> FUS

    FUS --> RR[Rerank actual\nheurístico]
    RR --> PACK[Evidence pack\ndedupe + diversidad + pruning]
    PACK --> PLAN[Answer planning\ndirect / hierarchical / global / argument / visual_grounded]
    PLAN --> GEN[Generación con Gemma 4]
    GEN --> VER1[Verificación determinística]
    VER1 --> VER2[Segunda pasada LLM]
    VER2 --> DEC{¿débil?}
    DEC -->|sí, una vez| RETRY[Regeneración única]
    DEC -->|no| BIND[Citation binding + evidence trace]
    RETRY --> BIND
    BIND --> OUT[Respuesta persistida]
```

### Qué sí está implementado

- Query routing por modo con `route_reason`. fileciteturn4file1
- Hybrid retrieval por etapas. fileciteturn4file1
- Evidence packing con deduplicación, diversidad y manejo de contradicción. fileciteturn4file1
- Answer planning (`direct`, `hierarchical`, `global`, `argument`, `visual_grounded`). fileciteturn4file1
- Verificación en dos pasos y una sola regeneración. fileciteturn4file1

### Qué obliga a corregir el diagrama ideal

- El **rerank** actual no es fuerte; sigue siendo heurístico. No debe dibujarse como si ya fuera late interaction o cross-encoder real. fileciteturn4file1
- El **sparse** aún no está cerrado como índice primario persisted alineado al baseline. fileciteturn4file1
- El **multi-hop** ya usa expansión, pero con menos tipado y menos robustez de la que el baseline espera. fileciteturn4file1

---

## 5) Tabla de modos y motores de acceso

```mermaid
flowchart LR
    ROUTER[Router] --> E[exact]
    ROUTER --> F[factual_local]
    ROUTER --> M[multi_hop]
    ROUTER --> G[global]
    ROUTER --> A[argumentative]
    ROUTER --> V[visual]

    E --> E1[Sparse exacta]
    E --> E2[Dense local]

    F --> F1[Dense top-k]
    F --> F2[Sparse apoyo]

    M --> M1[Dense seeds]
    M --> M2[Graph expansion]
    M --> M3[Propositions]

    G --> G1[Summary nodes]
    G --> G2[Hierarchical reduce]

    A --> A1[Conflict-aware retrieval]
    A --> A2[Diversidad documental]

    V --> V1[Visual pages]
    V --> V2[Texto estructural de soporte]
```

### Comentario arquitectónico

Los seis modos del README son válidos como contrato de producto. fileciteturn4file3 El inventario confirma que están implementados en existencia, pero todavía no aprobados de forma reproducible por evaluación formal, porque faltan goldens y runs completos por modo. fileciteturn4file1

---

## 6) Dónde está hoy el cuello del retrieval

```mermaid
flowchart LR
    subgraph HOY[Pipeline actual]
        D1[Dense Qdrant]
        S1[Sparse local / BM25]
        F1[Fusión]
        R1[Rerank heurístico]
        G1[Graph expansion parcial]
    end

    subgraph BASELINE[Pipeline que el baseline pide]
        D2[Dense Qdrant]
        S2[Sparse persisted principal]
        F2[Fusión híbrida estable]
        R2[Reranker fuerte\nlate interaction / cross-encoder]
        G2[Graph expansion tipada]
    end

    D1 --> F1 --> R1
    S1 --> F1
    G1 --> F1

    D2 --> F2 --> R2
    S2 --> F2
    G2 --> F2
```

### Conclusión precisa

La gran diferencia entre el plan y el backend real no está en “falta de componentes”, sino en **nivel de cierre de los componentes de retrieval**. El inventario lo deja explícito: Qdrant ya es la fuente principal dense, pero faltan sparse persisted, reranking fuerte y graph expansion más rico. fileciteturn4file1

---

## 7) Flujo de citas y grounding: componente que no debe simplificarse

```mermaid
flowchart TD
    EV[Evidence candidates] --> PACK[Evidence pack final]
    PACK --> GEN[Respuesta generada]
    GEN --> CAND[Candidatos de cita]
    CAND --> B1[Texto: span / node / heading_path / bbox]
    CAND --> B2[Proposición: claim + node_ids]
    CAND --> B3[Visual: page_asset_path + bbox + page_number]
    B1 --> RES[Binding final]
    B2 --> RES
    B3 --> RES
    RES --> UI[Sidebar / viewer / exporte]
```

### Qué dice el estado real

- Ya existe metadata enriquecida de grounding, incluyendo `bbox`, `heading_path` y `page_asset_path`. fileciteturn4file1
- Pero el inventario no da por cerrado el **binding estricto a spans reales** en todas las clases de evidencia. fileciteturn4file1

### Riesgo si no se corrige

Si esta parte se dibuja como “resuelta”, el sistema parece más sólido de lo que realmente es. En Atenex Nova, la credibilidad del producto depende de que cada cita sea navegable hasta evidencia real, no aproximada. El propio inventario lo trata como brecha alta. fileciteturn4file1

---

## 8) Ruta visual real: cómo debe diagramarse hoy

```mermaid
flowchart TD
    VQ[Consulta visual] --> VR[Router visual]
    VR --> VP[Recuperación de páginas visuales]
    VP --> TX[Texto estructural de soporte]
    TX --> PACK[Visual evidence pack]
    PACK --> VG[visual_grounded answer]
    VG --> STRICT{¿strict mode?}
    STRICT -->|sí y evidencia insuficiente| FAIL[Fallo explícito]
    STRICT -->|sí y evidencia suficiente| OK[Respuesta visual válida]
    STRICT -->|no| SOFT[Respuesta con fallback controlado]
```

### Estado real

La ruta visual existe con indexación, assets y viewer, pero **strict mode** todavía no está cerrado como regla dura; además no hay evidencia de cobertura total de render real por formato. fileciteturn4file1

### Implicación

No conviene seguir mostrando la ruta visual como una simple rama equivalente a las otras. Arquitectónicamente es una ruta con política de fallo propia.

---

## 9) Jobs y workers: lectura correcta del backend

AGENTS identifica `backend/atenex_nova/workers/main.py` y `workers/runner.py` como piezas que deben revisarse juntas. fileciteturn4file2 El inventario además confirma runner operativo y recuperación de jobs huérfanos. fileciteturn4file1

```mermaid
flowchart TD
    UP[Upload / action] --> J1[Job registrado]
    J1 --> WKR[Worker runner]
    WKR --> PAR[parse_document]
    PAR --> SEG[segment_document]
    SEG --> MEM[build memories]
    MEM --> IDX[index retrieval/visual]
    IDX --> DONE[ready]

    PAR -. error .-> ERR[failed]
    SEG -. error .-> ERR
    MEM -. error .-> ERR
    IDX -. error .-> ERR

    subgraph RECOVERY[Recuperación]
        ORPH[Jobs running huérfanos]
        RET[retry/backoff/terminalidad]
    end

    ORPH --> RET --> WKR
```

### Nota de auditoría

Aquí el problema principal ya no es inexistencia del worker model, sino cierre fino de invariantes de estado y de rebuild idempotente del documento. fileciteturn4file1

---

## 10) La arquitectura documental correcta del backend

El README contiene una vista útil, pero demasiado general. fileciteturn4file3 Para evitar errores de diseño, el backend debería leerse así:

```mermaid
flowchart TD
    subgraph PRESENTATION
        R1[Collections router]
        R2[Documents drill-down router]
        R3[Queries router]
        R4[Answers router]
        R5[Health / Jobs / Observability / Evaluation routers]
    end

    subgraph APPLICATION
        S1[Collection services]
        S2[Document services]
        O1[Retrieval orchestrator]
        O2[Answering orchestrator]
        P1[Routing / retrieval policies]
        P2[Verification policies]
    end

    subgraph DOMAIN
        D1[Document aggregates]
        D2[Answer / citation contracts]
        D3[Job states / invariants]
        D4[Repository interfaces]
    end

    subgraph INFRASTRUCTURE
        I1[SQL repositories]
        I2[Qdrant adapter]
        I3[Embedding adapter]
        I4[LLM adapter]
        I5[Docling adapter]
        I6[Visual adapter]
        I7[File storage]
    end

    PRESENTATION --> APPLICATION --> DOMAIN
    APPLICATION --> INFRASTRUCTURE
```

### Corrección clave

El inventario marca como brecha alta que **ningún router debería acceder a infraestructura directamente** y que aún quedan acoplamientos puntuales. fileciteturn4file1 Ese detalle debe aparecer en el diagrama, porque altera el criterio de cierre del backend.

---

### Superficie HTTP verificada

La superficie pública actual no se debe reconstruir desde memoria ni desde el roadmap: queda anclada a `docs/api-endpoints.md` y al OpenAPI generado por `atenex_nova.main:create_app`. El contrato ligero cubre los grupos `health`, `collections`, `documents`, `queries`, `answers`, `jobs`, `observability` y `evaluation`, incluyendo `/health/dependencies` y el drill-down documental `/documents/{document_id}/nodes`, `/structure`, `/chunks`, `/propositions` y `/pages/{page_number}`. Este contrato pasa en aislamiento, aunque los gates globales de unit tests, frontend build/lint, `ruff` y `mypy` siguen abiertos en el checkout actual.

---

## 11) Gap real resumido en una sola lámina

```mermaid
flowchart LR
    subgraph IMPLEMENTADO[Ya implementado]
        I1[Monolito modular]
        I2[Ingesta estructural funcional]
        I3[Memorias multicapa]
        I4[Routing por modo]
        I5[Answer planning]
        I6[Verificación en dos pasos]
        I7[Workspace + inspector + viewer]
        I8[Health/dependencies + contrato API]
    end

    subgraph PARCIAL[Parcial / por cerrar]
        P1[Fidelidad estructural total]
        P2[Chunking por tokens estricto]
        P3[Metadata homogénea]
        P4[Evidence trace completo en UI]
        P5[Exportes enriquecidos]
        P6[Evaluación formal por modo]
        P7[E2E + integración con runtimes activos]
    end

    subgraph CRITICO[Brechas críticas]
        C1[Sparse persisted real]
        C2[Reranker fuerte]
        C3[Graph expansion tipada]
        C4[Citation binding estricto]
        C5[Visual strict mode]
    end
```

Todo lo de la columna crítica sale textual del inventario como bloqueante o de prioridad alta para alcanzar el baseline. fileciteturn4file1

---

## 12) Arquitectura objetivo corregida: la que sí conviene implementar

```mermaid
flowchart TD
    Q[Pregunta] --> ROUTER[Router persistido + route_reason]

    ROUTER --> RETR[Retrieval stage]
    subgraph RETR[Retrieval multicapa]
        DENSE[Dense retrieval en Qdrant]
        SPARSE[Sparse persisted real]
        GRAPH[Graph expansion tipada]
        SUMM[Summary retrieval]
        VIS[Visual retrieval]
    end

    DENSE --> FUSE[Fusión híbrida estable]
    SPARSE --> FUSE
    GRAPH --> FUSE
    SUMM --> FUSE
    VIS --> FUSE

    FUSE --> RERANK[Reranker fuerte real]
    RERANK --> PACK[Evidence pack por modo]
    PACK --> PLAN[Answer plan]
    PLAN --> LLM[Gemma 4]
    LLM --> VERIFY[Verificación determinística + LLM]
    VERIFY --> BIND[Binding estricto de citas]
    BIND --> UI[UI / exporte / viewer]
```

### Por qué este es el diagrama correcto

Porque respeta el plan original de memoria multicapa, query routing y generador como sintetizador, pero además incorpora las correcciones que el estado real del backend exige: sparse persisted, reranker fuerte, graph expansion tipada y binding/citas estrictas. fileciteturn4file0 fileciteturn4file1

---

## Conclusiones de auditoría

### 1. El plan conceptual está bien enfocado

Atenex Nova sí está bien concebido como plataforma local de memoria documental y no como chatbot vectorial. La apuesta por parseo estructural, varias memorias, routing por modo y síntesis sobre evidencia es coherente. fileciteturn4file0

### 2. El README simplifica demasiado el pipeline real

Sirve como onboarding, pero no sirve por sí solo para auditar el backend. Le faltan dos cosas esenciales: mostrar que el rerank actual sigue siendo heurístico y mostrar que la ruta visual tiene política de strict failure separada. fileciteturn4file3 fileciteturn4file1

### 3. La fuente correcta para “estado del backend” es el inventario final

AGENTS lo trata como inventario canónico del gap y el propio documento dice que revisó routers, orquestadores, repositorios, workers, frontend y tests. Por tanto, para no introducir errores, la arquitectura debe dibujarse contra ese snapshot. fileciteturn4file2 fileciteturn4file1

### 4. El backend ya tiene el 80% de la topología, pero no el 100% del cierre del retrieval

Lo crítico pendiente no es agregar muchas cajas nuevas, sino endurecer el retrieval core y el grounding: sparse persisted, reranking fuerte, expansión de grafo tipada, citation binding estricto y visual strict mode. fileciteturn4file1

### 5. Si quieres evitar errores de implementación, el orden correcto de trabajo es este

1. cerrar sparse persisted,
2. cerrar reranker fuerte,
3. tipar graph expansion,
4. endurecer citation binding,
5. cerrar visual strict mode,
6. recién después declarar el pipeline RAG “completo”.

Ese orden sale directamente del peso arquitectónico de las brechas altas del inventario. fileciteturn4file1
