# Auditoría técnica contrastiva

Estado: **Implemented / Verified** para el ledger Repo Context actualizado el
2026-07-31, el diagnóstico del RAG del 2026-08-02 y las correcciones focalizadas del
checkout actual. El runtime documental reconstruido sigue **Planned**.

La auditoría integral anterior del RAG documental se conserva sin reescribir en
[archive/rag-v0/auditoria-completa-2026-06-16.md](archive/rag-v0/auditoria-completa-2026-06-16.md).
Sus resultados son **Historical** y no se mezclan con la verificación actual.

La auditoría viva de ingesta, memoria, retrieval, respuestas, tesis y EOS está en
[auditoria-rag-respuestas-sota-2026-08-02.md](auditoria-rag-respuestas-sota-2026-08-02.md).
Su ledger de corrección está en
[plan-rag-sintesis-corpus.md](plan-rag-sintesis-corpus.md): registra componentes
**Implemented / Verified**, pero mantiene G0–G6 **Planned**.

## Validación local de cierre — 2026-08-05

El checkout pasó Ruff completo, MyPy sobre 195 archivos, 57 pruebas Repo Context con
3 omisiones por gramáticas no precargadas, y test/lint/build del frontend. La suite
backend conjunta obtuvo 269 pruebas pasadas, 3 omitidas y 11 fallidas: las fallas
dependen del reranker requerido ausente en el entorno Linux sin extra ML y de una
colección Qdrant visual viva con schema anterior. La validación no mutó esa colección
ni convierte el runtime documental completo en **Verified**; su rebuild sigue
**Planned**.

### Optimización viva de ingesta — 2026-08-05

La reingesta limpia de `Jesus. G.` expuso 927.310 proposiciones esperadas. Ollama
cargaba inicialmente sólo 63 MB de 709 MB de EmbeddingGemma BF16 en VRAM y el worker
sostenía 13,3 proposiciones/s. Se añadió un transporte HTTP OpenAI-compatible que no
forma parte del fingerprint, un launcher llama.cpp con offload CUDA completo y
codificación SPLADE persistida en lotes acotados. La prueba viva posterior sostuvo
102,7 proposiciones/s end-to-end sobre ocho jobs (5.231 proposiciones), con API,
Qdrant y dependencias en verde. El runbook conserva comandos, puertos y recuperación.

Esta medición valida rendimiento operativo, no calidad RAG. El rebuild y el benchmark
humano siguen abiertos hasta que la colección alcance `READY` y se ejecuten sus gates.

## Remediación del RAG en el checkout actual

| Claim | Estado del código | Evidencia focalizada | Runtime vivo |
|---|---|---|---|
| Frontera de corpus y transcripciones | **Implemented / Verified** | allowlist/exclusiones; timestamps, offsets, rol y metadata estructural probados | rebuild limpio **Planned** |
| Chunking y contrato de embeddings | **Implemented / Verified** | hard cap 800/overlap 80, nodo sobredimensionado, prefijos query/documento y fingerprint `emb-v2` probados | vectores del corpus anterior son incompatibles; rebuild **Planned** |
| Dense y fallback cuantizado | **Implemented / Verified** | Qdrant dense primario, guard de schema/dimensión, límite PurePy y rechazo de perfiles legados probados | Qdrant vivo poblado con la nueva generación **Planned** |
| Cobertura de retrieval | **Implemented / Verified** | paginación más allá del documento 50, contexto de follow-up, hasta tres facetas y RRF; `eutanacia` se corrige conservadoramente | Recall@20 Jesús G **Planned** |
| Memoria derivada | **Implemented / Verified** | summaries idempotentes de sección/documento con procedencia; una memoria extractiva de colección explícita y embebible | faithfulness/coverage humana **Planned** |
| Readiness | **Implemented / Verified** | barrera temporal, democión de `READY` incompleto y reparación mínima probadas | `generation_id` y activación atómica definitivos **Planned** |
| Publicación y limpieza | **Implemented / Verified** | fail-closed en rebuild/transición/sin `READY`; evidencia rehidratada desde SQL; cleanup idempotente de SQL, Qdrant, candidate, graph y visual probado | generación staged y reconciler de cardinalidad vivos **Planned** |
| Síntesis compleja | **Implemented / Verified** | maps agrupados y acotados, reducción final, trazas e índices globales de evidencia probados | benchmark argumentativo de 150 preguntas **Planned** |
| Verificación y payload | **Implemented / Verified** | claim audit, citation binding/support, verificador que no infla score y metadata pública compacta probados | calibración humana/entailment independiente **Planned** |
| UI de confianza | **Implemented / Verified** | verdict visible, alertas independientes del número de citas, incidencias y navegación de hasta 20 evidencias | validación E2E contra rebuild vivo **Planned** |

El grafo cross-document real, un reranker vivo calibrado y la comparación controlada
NotebookLM/EOS permanecen **Planned**. Ninguna prueba focalizada demuestra todavía
comprensión completa del corpus, aprendizaje continuo o AGI.

## Snapshot diagnóstico del RAG documental

Estado: **Historical** respecto del checkout remediado. Conserva la evidencia causal
que motivó las correcciones; no describe un índice reconstruido con `emb-v2`.

| Claim del bounded context documental | Estado | Evidencia del 2026-08-02 | Gap vigente |
|---|---|---|---|
| Ingesta de la colección `Jesus G` | **Historical** | 1.754 documentos `ready`, 3 `failed`; API, worker, frontend, Ollama y Qdrant vivos | `READY` no era una barrera de enriquecimiento; todos los documentos listos conservaban jobs pendientes/activos en el snapshot |
| Chunking acotado por tokens | **Historical** | 3.018 chunks; 952 superaban 2.048 tokens; 80,59 % de los tokens estimados estaba después de esa posición dentro de chunks | hard cap corregido; rebuild **Planned** |
| Memoria global por summaries | **Historical** | las filas existían, pero cada documento creaba un pseudo-summary de colección; cero summary vectors en el snapshot | memoria extractiva explícita entregada; evaluación temática **Planned** |
| Grafo conceptual | **Historical** | aproximadamente 2,59 M de aristas por adyacencia/keywords dentro de documentos | entidades y relaciones cross-document evaluadas **Planned** |
| Índices híbridos completos | **Historical** | Qdrant exponía solo propositions sparse y PurePy escaneaba todos los códigos | rebuild con schema guard y paridad por generación **Planned** |
| Routing y recuperación multi-motor | **Historical** | una consulta, router por marcadores y pack máximo de 8–10 evidencias/2.048 tokens | benchmark del retrieval corregido **Planned** |
| Síntesis jerárquica/global | **Historical** | `hierarchical_synthesis` ejecutaba una única generación | benchmark del map-reduce entregado **Planned** |
| Grounding y citas | **Historical** | overlap global + cantidad de citas; no había audit por claim | calibración humana del claim audit entregado **Planned** |
| Calidad comparable a NotebookLM | **Historical** | la pregunta exacta de eutanasia produjo un falso negativo aun con evidencia explícita en 22 documentos | comparación ciega sobre snapshots/fuentes idénticos **Planned** |
| Aprendizaje continuo o AGI | **Historical** | consultas y respuestas se persistían, pero no actualizaban habilidades, política ni memoria neural validada | línea experimental separada **Planned** |

La prueba controlada se ejecutó contra una copia consistente de SQLite, no contra las
tablas de producción. `mode=auto` dio `multi_hop → direct_answer`, seis evidencias,
`unverified` y grounding 0,261; `mode=global` usó dos pseudo-resúmenes, también quedó
`unverified` y dio grounding 0,232. En ambos casos afirmó que no había menciones de
eutanasia, aunque una búsqueda SQL de solo lectura encontró 22 documentos y una
transcripción que contiene la cadena argumentativa principal.

## Contrato frente a implementación

| Claim del baseline | Estado | Evidencia en fuente/pruebas | Gap restante |
|---|---|---|---|
| Core local sin servicios | **Verified** | `repo_context/composition.py`; suite completa con semántica desactivada | ninguno para el smoke core |
| Worktree Git real y fallback no-Git | **Verified** | `infrastructure/git_scanner.py`; tests de tracked, untracked, fingerprint y filesystem | matriz de rename/delete más amplia **Planned** |
| Exclusión de secretos/binarios/builds/escapes | **Verified** | `domain/policies.py`, scanner y tests de traversal/symlink | ampliar patrones cuando aparezcan formatos nuevos |
| Índice SQLite FTS5 incremental | **Verified** | `infrastructure/sqlite_index.py`; reuse por hash/parser y búsqueda literal+FTS | migraciones desde schemas futuros **Planned** |
| Generaciones atómicas | **Verified** | callback de segunda captura dentro de la transacción; rollback y retención probados | load test concurrente prolongado **Planned** |
| Parsers y fallback por archivo | **Verified** | Python AST; Tree-sitter/fallback para TS/TSX/JS/Java/SQL; 53 pruebas con cache preparado | gramáticas SQL reales pueden producir fallback; cobertura global ≥95 % no medida |
| Grafo y RepoMap acotados | **Verified** | `application/repomap.py`, resolución conservadora, foco RRF por facetas y tests de ciclos/budget | resolución dinámica/interlenguaje total fuera de alcance |
| Seis servicios y CLI común | **Verified** | `application/services.py`, `presentation/cli.py`; contratos y paridad probados | paginación por cursor no existe en v1 |
| MCP read-only | **Implemented / Verified** | subprocess `stdio`: cliente oficial MCP 2.0 inicializa, lista seis herramientas y ejecuta `repo_overview` | matriz cruzada Python/OS más amplia **Planned** |
| Fuente viva como autoridad | **Verified** | rehash antes de extractos, stale envelope, sidecar binding y fail-closed por cambio de generación | ninguna garantía sobre semántica de ejecución dinámica |
| Ollama/Qdrant opcionales | **Implemented** | adapters HTTP, namespaces y sentinel persistente; fakes verificados | proveedores vivos no revalidados |
| RRF y reranking | **Implemented / Planned** | RRF determinista y puerto de reranker probados | no hay adapter concreto ni live reranker |
| Generalidad entre repositorios | **Verified** como smoke | mismo runner/código: 13/13 hits en Atenex y `client-romero`; regresión POS → API completa | held-out set amplio y benchmark externo **Planned** |
| Skill portable de navegación | **Verified** | skill canónica `.agents/skills/atenex-repo-context` y adaptador Claude, ambos validados | adapters para otros clientes solo cuando sus formatos lo requieran |

Las rutas anteriores son relativas a `backend/atenex_nova/repo_context/`, salvo las
pruebas bajo `backend/tests/repo_context/`.

## Evidencia reproducible

Entorno focalizado:

- host Linux; runtime MCP portable y aislado en Python 3.11;
- contrato `mypy` fijado a Python 3.12;
- paquete editable y MCP 2.x;
- Tree-sitter probado tanto sin gramáticas como con un caché local precargado;
- semántica desactivada en aceptación.

Resultados:

```text
unittest Repo Context, cache preparado: 53 passed
unittest Repo Context, sin gramáticas precargadas: 50 passed, 3 skipped
ruff focalizado: 0 issues
mypy repo_context: 0 errors in 28 files
goldens: 13 queries, 13 hits, 0 failures
Recall@20 medio: 1.0
MRR: 0.90384615
```

El cliente MCP oficial inicializó el server como subprocess `stdio`, verificó los
seis schemas y ejecutó búsquedas, símbolos y `repo_overview` con respuestas
estructuradas e `is_error=false`. El overview transversal ubicó las seis etapas
críticas POS → API dentro de sus primeros siete paths tanto en resultados como en
RepoMap, respetando 5979/6000 tokens. Los bloqueos observados inicialmente provenían del sandbox de
verificación, que no permitía completar el wake-up del worker AnyIO; la misma prueba
fuera de ese sandbox —el entorno equivalente al proceso lanzado por Claude— pasó.
El runtime portable local usa Python 3.11; el contrato canónico multiplataforma sigue
siendo Python 3.12 y requiere una matriz cruzada más amplia antes de un release.

## Hallazgos cerrados durante implementación

1. El análisis de impacto hacía una lectura SQLite global por símbolo y tardaba
   44.2 s en el repositorio externo. Un caché por generación de las relaciones
   redujo el mismo caso a aproximadamente 0.66 s sin cambiar la semántica.
2. BM25 aislado relegaba una migración SQL literal; la búsqueda literal por contenido
   se fusionó con FTS y la migración requerida subió al top 3.
3. `related_tests` no encontraba referencias exactas no resueltas por el grafo; se
   añadió una señal lexical acotada y deduplicada por ruta.
4. Un sidecar podía abrirse con otro root si se reutilizaba manualmente; los servicios
   ahora verifican root canónico y `repository_id`.
5. La activación podía ocurrir después de que cambiara la fuente durante el parseo;
   una segunda captura se valida dentro de la transacción.
6. La capa semántica perdía readiness al reiniciar proceso; Qdrant ahora guarda un
   sentinel completo por repo/generación/modelo y nunca habilita builds parciales.
7. Cambiar de fallback a Tree-sitter podía reutilizar extracción antigua; el
   fingerprint del parser incorpora disponibilidad de gramáticas y versión del
   paquete.
8. Un foco arquitectónico amplio quedaba dominado por coincidencias genéricas. El
   overview ahora descompone intenciones reconocidas, fusiona paths por RRF y aplica
   diversidad por subsistema; las facetas se devuelven para auditoría.
9. El criterio anterior pedía a una búsqueda léxica del outbox reconstruir también
   el servidor. La aceptación separa ahora búsqueda directa de evidencia y overview
   transversal, de acuerdo con el contrato público y la skill de agente.

## Gaps vigentes

- Repetir MCP `stdio` como subprocess con Python 3.12 y al menos dos clientes.
- Ejecutar Ollama/`embeddinggemma` y Qdrant vivos; documentar dimensión, latencias y
  recuperación frente al core.
- Implementar y evaluar un adapter local de reranker antes de afirmar reranking.
- Expandir el manifest de trece smoke cases a un held-out set con spans, grupos
  requeridos, nDCG y revisión independiente.
- Medir p50/p95/p99, memoria, tamaño de índice, incrementalidad y concurrencia con
  protocolo repetido.
- Completar `generation_id`, reconciliación y activación atómica en todas las capas
  antes de publicar `READY` como generación completa.
- Ejecutar un rebuild limpio vivo con el contrato `emb-v2` y verificar paridad
  SQL↔Qdrant↔candidate↔summaries↔graph.
- Completar el benchmark Jesús G de 150 preguntas y revisión humana; validar un
  reranker multilingüe vivo, graph cross-document y comparación NotebookLM/EOS por
  separado. Usar las puertas de
  [plan-rag-sintesis-corpus.md](plan-rag-sintesis-corpus.md).

## Regla de actualización

Un cambio de contrato, arquitectura o gap debe actualizar conjuntamente:

1. [../README.md](../README.md);
2. [baseline.md](baseline.md);
3. este ledger;
4. el documento especializado y sus pruebas.

`Implemented` afirma existencia; `Verified` requiere evidencia nombrada;
`Planned` es trabajo pendiente; `Historical` nunca describe el runtime vigente.
