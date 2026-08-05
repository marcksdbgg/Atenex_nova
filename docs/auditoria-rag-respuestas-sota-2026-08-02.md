# Auditoría integral del RAG documental y de la calidad de respuesta

Estado: **Verified** para la inspección de fuente y las observaciones del runtime
registradas el 2026-08-02. Las propuestas de rediseño están marcadas
**Planned**. Los resultados anteriores de la tesis y del RAG archivado siguen siendo
**Historical** hasta que exista una reproducción vinculada a artefactos.

Esta auditoría estudia por qué Atenex Nova responde como un buscador con una capa
generativa, en lugar de comportarse como un sintetizador que reconstruye la línea
argumental de todo un corpus. El análisis cubre el flujo completo:

```text
importación → parsing → normalización → segmentación → embeddings e índices
           → proposiciones → resúmenes → grafo → routing → retrieval
           → evidence pack → planificación → generación → verificación → citas → UI
```

El corpus vivo auditado es `Jesus G`. La comparación funcional usa el ejemplo de
NotebookLM aportado por el usuario, pero no atribuye a NotebookLM una arquitectura
interna que Google no haya publicado.

## 1. Dictamen ejecutivo

Atenex Nova contiene una arquitectura modular prometedora, pero la implementación
viva no constituye hoy una memoria coherente del corpus. Es un RAG monodisparo que
normalmente recupera una sola vez, selecciona entre 8 y 10 fragmentos dentro de un
presupuesto aproximado de 2.048 tokens y ejecuta una generación. El modelo no recibe
los 1.754 documentos listos ni una representación global fiel de ellos.

El ejemplo de la eutanasia permitió reproducir el fallo de manera controlada:

- el corpus contiene 22 documentos que mencionan `eutanasia`;
- una transcripción concreta contiene prácticamente toda la cadena argumentativa que
  aparece en la respuesta de NotebookLM;
- Atenex, ante la pregunta exacta del usuario, afirmó que el corpus no contenía
  menciones directas de la eutanasia;
- la respuesta quedó `unverified`, sin citas y con grounding 0,261;
- forzar el modo `global` produjo el mismo falso negativo, usando solo dos
  pseudo-resúmenes no citables y grounding 0,232.

No es principalmente un problema de “inteligencia” de Gemma. La evidencia se pierde
antes de la generación y vuelve a perderse durante la selección:

```text
transcripción de 9.282 tokens
  → un único nodo de captions sobredimensionado
  → embedding con contexto máximo 2.048
  → representación densa dominada por el prefijo
  → índices Qdrant incompletos y búsqueda exhaustiva PurePy
  → router por palabras clave, sin reescritura ni descomposición
  → 2–10 evidencias elegidas primero por tipo y después por relevancia
  → prompt directo que exige respuesta breve y factual
  → verificación por solapamiento léxico, no entailment por afirmación
  → falso “no existe evidencia”
```

Los defectos de mayor impacto son:

1. **Segmentación incompatible con el modelo de embeddings.** El 80,59 % de los
   tokens estimados del corpus queda después de la posición 2.048 dentro de chunks
   sobredimensionados.
2. **No hay resumen global real.** Cada documento crea una fila llamada
   `collection_summary`; `summarize_texts` solo selecciona y concatena hasta tres
   textos por frecuencia léxica.
3. **No hay grafo conceptual transversal.** El grafo enlaza oraciones del mismo
   documento mediante cercanía y coincidencia de palabras.
4. **Parte del descubrimiento ve solo 50 documentos.** La consulta usa el límite
   por defecto del repositorio de documentos.
5. **No hay planificación iterativa.** No existen query rewriting conversacional,
   descomposición, multi-query, búsqueda correctiva ni map-reduce real.
6. **El reranker neural no está activo.** El runtime carece de `torch`; degrada a
   una heurística sin bloquear ni hacer visible la pérdida de capacidad.
7. **El índice denso PurePy no es ANN.** Escanea todos los códigos cuantizados y
   materializa matrices `N × 384`; ya consume decenas de segundos en propositions y
   presenta riesgo de varios GiB por consulta.
8. **Grounding y citas no prueban soporte semántico.** El score premia solapamiento
   de palabras y cantidad de referencias; el binding valida índices, no la relación
   claim→evidencia.
9. **`READY` no significa memoria completa.** En el snapshot estable, todos los
   documentos listos conservaban trabajos pendientes o activos.
10. **La evaluación disponible no mide la expectativa real.** No hay ejecuciones
    vivas ni goldens de Jesús G para postura autoral, síntesis global, inferencia,
    continuidad conversacional o cobertura de citas.

La conclusión científica es doble:

- Atenex puede convertirse en un asistente local de síntesis profunda si primero
  corrige ingesta, representaciones, retrieval y evaluación.
- Atenex junto con la idea de EOS puede formularse como agenda de investigación en
  memoria verificable y aprendizaje en varias escalas; no es evidencia de AGI, de
  aprendizaje continuo neural ni de un sistema “sin ventana de contexto”.

## 2. Alcance, método y límites

### 2.1 Evidencia revisada

La auditoría combinó:

- `repo_overview` y búsquedas focalizadas del MCP Repo Context;
- lectura exacta del código de ingesta, memoria, índices, consulta, respuesta,
  evaluación y frontend;
- estado de SQLite, Qdrant, Ollama, API, worker y frontend vivos;
- historial persistido de respuestas anteriores;
- dos respuestas nuevas contra una copia consistente de la base, servida en un API
  temporal aislado;
- la tesis `/mnt/ssd/UCSP/Tesis/tesis_2025/Tesis.pdf`;
- el roadmap `/mnt/ssd/Mark/EOS/EOS_core/README.md`;
- fuentes primarias u oficiales sobre NotebookLM, RAG jerárquico, GraphRAG,
  retrieval contextual, evaluación y memoria neural.

Repo Context informó:

```text
generation: 14
HEAD: d23894a22fdea0ad559bc01cd5ea6134aa87fe73
stale: false
```

`trace_symbol` y `analyze_impact` no pudieron resolver las clases principales porque
el índice vigente marcó esos archivos Python como `parsed` pero devolvió una lista de
símbolos vacía. `related_tests` sí devolvió candidatos, aunque gran parte de ellos se
basó en coincidencia léxica débil. Por ello, las conclusiones de esta auditoría se
fundan en la fuente exacta y en el runtime, no en relaciones estáticas ausentes.

### 2.2 Experimento aislado

Se creó una copia consistente de `backend/atenex_nova.db` y se levantó un segundo API
en `127.0.0.1:8001` con esa copia. Las consultas escribieron únicamente en la copia.
Ollama y Qdrant siguieron siendo los proveedores locales vivos; el worker de
producción continuó procesando su cola. El API temporal se detuvo después del ensayo.

Esto permite reproducir el contenido y las rutas, pero las latencias no son un
benchmark de release: el generador y Qdrant compartían carga con el worker.

### 2.3 Límites de esta auditoría

- Es un análisis profundo de un único host y snapshot, no una matriz de sistemas
  operativos.
- No se reejecutó toda la suite histórica de Windows ni se validó Docling, ausente en
  este runtime.
- Se hicieron dos respuestas controladas y una búsqueda adicional, no una evaluación
  estadística.
- No se dispuso de acceso automatizado a NotebookLM para una comparación ciega sobre
  exactamente el mismo snapshot.
- La arquitectura interna de NotebookLM es propietaria. Solo se comparan capacidades
  observables y claims oficiales.
- El porcentaje 80,59 % usa el estimador persistido de Atenex. La truncación exacta
  por el tokenizer real debe medirse en una reconstrucción.

## 3. Estado vivo reproducible

El siguiente corte corresponde a la copia estable creada alrededor de las 09:00,
hora de Lima, mientras el worker seguía avanzando en producción.

| Artefacto | Conteo observado | Interpretación |
|---|---:|---|
| Documentos `ready` | 1.754 | El estado no implica enriquecimiento completo. |
| Documentos `failed` | 3 | Incluye formatos administrativos no parseables. |
| Document nodes | 5.252 | Cero padres y cero headings en el corpus auditado. |
| Chunks | 3.018 | Solo 1,72 por documento en promedio. |
| Tokens estimados en chunks | 13.440.422 | Promedio 4.453; máximo 453.076. |
| Chunks mayores de 2.048 | 952 | 31,54 % de los chunks. |
| Tokens situados después de 2.048 | 10.831.634 | 80,59 % del total estimado. |
| Proposiciones | 788.945 | Extracción heurística de oraciones. |
| Vectores cuantizados de chunk | 3.018 | Uno por chunk, aunque el texto puede exceder el contexto. |
| Vectores cuantizados de proposition | 651.223 | Capa parcial en el corte. |
| Resúmenes de colección | 1.390 | Son uno por documento procesado, con el mismo scope de colección. |
| Resúmenes de documento | 1.390 | Extractivos, no generativos. |
| Resúmenes de sección | 2.511 | Basados en el prefijo de 280 caracteres del chunk. |
| Resúmenes con `embedding_ref` | 0 | Ninguna capa de resumen estaba activa. |
| Evaluation runs/cases | 0 / 0 | Sin evaluación viva del corpus. |
| Jobs pendientes o activos | 2.482 | El más antiguo era del 2026-06-19. |
| Documentos `ready` con algún job pendiente/activo | 1.754 | `READY` no es una barrera de completitud. |

Qdrant exponía una sola colección, la de propositions, configurada únicamente con
vector sparse. No estaban presentes las colecciones base de chunks, summaries o
pages. Su cardinalidad crecía mientras el worker procesaba la cola, por lo que no se
fija como número de release.

El health endpoint respondió `degraded`:

- LLM, Qdrant, embeddings, base y storage visual: disponibles;
- Docling: no instalado;
- TurboVec: no instalado;
- base: SQLite, con recomendación explícita de un solo writer.

El modelo vivo `embeddinggemma` reportó contexto 2.048, dimensión nativa 768 y
Atenex conservó 384 dimensiones mediante truncación Matryoshka y renormalización.

El almacenamiento mostraba otra señal de amplificación:

```text
uploads Jesus G:       56 MiB
SQLite principal:     1,8 GiB
WAL:                  147 MiB
storage/turbovec:       0 B
```

La expansión proviene, sobre todo, de cientos de miles de propositions, códigos
cuantizados y millones de aristas heurísticas.

## 4. Auditoría de ingesta y representación

### 4.1 Importación sin frontera de corpus

Estado: **Implemented**, con gaps **Verified**.

La importación local recorre, hashea y registra archivos sin una política suficiente
de allowlist, tamaño máximo o exclusión de artefactos administrativos. En el corpus se
ingirieron `_meta/video_index.csv`, JSON y ZIP. El CSV de metadatos produjo el chunk
máximo de 1.812.305 caracteres, 25.446 propositions y más de 114.000 aristas.

El problema no es solo costo. Un artefacto administrativo puede dominar BM25,
embeddings, resúmenes y grafo sin pertenecer al conocimiento que el usuario desea
consultar. La política de corpus debe distinguir contenido, metadatos, manifests,
exports, binarios y archivos auxiliares antes de calcular memoria derivada.

Rutas relevantes:

- [import_session_service.py](../backend/atenex_nova/application/services/import_session_service.py)
- [collections.py](../backend/atenex_nova/presentation/api/routers/collections.py)

### 4.2 Parsing de transcripciones sin estructura útil

Estado: **Verified**.

Para `.txt`, el parser divide únicamente por doble salto de línea y crea nodos
`paragraph` con `heading_path=[]`. Una transcripción de captions con saltos simples
puede convertirse en un único nodo enorme. Véase
[docling_adapter.py](../backend/atenex_nova/infrastructure/parsing/docling_adapter.py).

El resultado vivo —5.252 nodos, cero padres y cero headings— significa que la capa
llamada estructural no representa capítulos, turnos, temas, timestamps ni unidades
argumentativas del corpus de videos. Docling no corrige este caso porque el adapter
elige explícitamente el parser plain-text para `.txt`.

### 4.3 El hard cap de chunk no es un hard cap

Estado: **Verified**, severidad P0.

`TokenBudgetPolicy` recomienda 800 tokens, pero solo divide antes de añadir el
siguiente nodo cuando ya existe contenido acumulado. Si el primer nodo excede el
presupuesto, pasa entero. `SegmentDocumentJobHandler` nunca subdivide el nodo.

Rutas exactas:

- [token_budget_policy.py](../backend/atenex_nova/application/policies/token_budget_policy.py)
- [mem_builder_job.py](../backend/atenex_nova/workers/jobs/mem_builder_job.py)
- [test_token_budget_policy.py](../backend/tests/unit/policies/test_token_budget_policy.py)

La prueba unitaria vigente acepta que un nodo individual mayor que el máximo no se
divida. Es una especificación incorrecta para embeddings con contexto finito.

La transcripción directamente relacionada con la pregunta de la eutanasia quedó así:

| Parte | Tokens estimados | Caracteres | Observación |
|---|---:|---:|---|
| Envelope de metadatos | 74 | 299 | Chunk separado. |
| Captions | 9.282 | 37.131 | Un solo chunk; `cadalso` aparece alrededor del carácter 17.411. |

EmbeddingGemma puede representar como máximo los primeros 2.048 tokens en una
llamada. Aunque el runtime de Ollama no informó explícitamente cuántos tokens
truncó por fila, la incompatibilidad de presupuestos es objetiva y el contenido de
la cola no puede influir íntegramente en ese vector.

### 4.4 Embeddings no alineados con el contrato de retrieval

Estado: **Verified** en el payload; impacto exacto **Planned** por medir.

La consulta se envía como texto crudo y el documento usa un encabezado propio
`Documento: ...`. El adapter Ollama manda solo `model` e `input`, sin distinguir
query de pasaje. La tarjeta oficial de
[EmbeddingGemma](https://huggingface.co/google/embeddinggemma-300m) prescribe
formatos asimétricos de tarea para retrieval, equivalentes a `task: search result |
query: ...` y `title: ... | text: ...`.

Rutas:

- consulta: [retrieval_orchestrator.py](../backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py);
- documento: [mem_builder_job.py](../backend/atenex_nova/workers/jobs/mem_builder_job.py);
- payload Ollama: [embedding_adapter.py](../backend/atenex_nova/infrastructure/embeddings/embedding_adapter.py).

La falta de prefijos no demuestra por sí sola un porcentaje de pérdida de recall, pero
sí invalida asumir que el encoder se está usando según su configuración de retrieval.

### 4.5 `READY` prematuro y generaciones mezcladas

Estado: **Verified**, severidad P0.

En perfil no estricto, el documento se marca `READY` después de chunks/embeddings y
antes de propositions, summaries, graph y visual. En el snapshot, los 1.754
documentos listos tenían algún trabajo pendiente o activo.

No existe una barrera única que afirme:

```text
misma generación
+ chunks completos
+ propositions completas
+ summaries completos
+ graph completo
+ paridad SQL/Qdrant/candidate
= READY
```

Tampoco hay un manifest por generación, checksum agregado o reconciler de
cardinalidad. El health de Qdrant comprueba disponibilidad del servicio, no que una
colección tenga todas las capas exigidas para contestar.

### 4.6 Propositions: volumen no equivale a conocimiento

Estado: **Verified**.

`ExtractPropositionsJobHandler` separa oraciones por regex y asigna una clase a partir
de marcadores como `because`, `debe`, `diferencia` o `se define`. No hay:

- decontextualización de pronombres;
- resolución de entidades;
- normalización de ASR;
- modalidad o temporalidad;
- deduplicación semántica;
- detección de tesis, objeción y respuesta;
- evaluación de completitud de la afirmación.

Así se produjeron 788.945 propositions, con fragmentos conversacionales y ruido que
pueden desplazar pasajes útiles. La cifra alta no representa una base de conocimiento
equivalente a 788.945 hechos verificados.

Fuente: [memory_enrichment_job.py](../backend/atenex_nova/workers/jobs/memory_enrichment_job.py).

### 4.7 Resúmenes: etiquetas globales sobre artefactos locales

Estado: **Verified**, severidad P0.

La función `summarize_texts` calcula frecuencia de palabras, ordena las entradas y
concatena hasta tres. No realiza abstracción. Después:

- el resumen de sección recibe el prefijo de 280 caracteres del chunk;
- el resumen de documento recibe hasta tres propositions o chunks;
- cada documento crea una nueva fila con `scope_type="collection"` y el mismo
  `scope_id` de la colección;
- esas filas de colección se excluyen explícitamente del embedding;
- los 5.291 resúmenes del snapshot tenían `embedding_ref=NULL`.

Por ello, `Collection summary` no significa “síntesis del corpus”. Significa uno de
muchos extractos por documento, sin `document_id` en la respuesta y, por tanto, sin
una cita documental resoluble.

El estado presenta además una inconsistencia que debe diagnosticarse antes de un
rebuild: 407 jobs `embed_summaries` figuraban como exitosos en la copia, pero no
existían `embedding_ref`, vectores cuantizados de summary ni colección Qdrant de
summaries. El job status no prueba que el artefacto final siga presente y coherente.

### 4.8 Grafo: relaciones intra-documento por heurística

Estado: **Verified**.

`BuildGraphJobHandler` opera sobre las propositions de un solo documento. Crea:

- proposition→document con `appears_in`;
- enlaces entre propositions adyacentes;
- `supports`, `contradicts` o `defines` por presencia de palabras;
- hasta cinco `mentions` por coincidencia de keywords entre oraciones del mismo
  documento.

El bloque denominado `CONCEPT-BASED CROSS-REFERENCES` sigue dentro de la lista local
del documento y ejecuta un doble bucle cuadrático. No enlaza conceptos canónicos entre
fuentes ni detecta comunidades del corpus.

En el snapshot había aproximadamente 2,59 millones de aristas. El grafo aporta
traversal local, pero no una representación de la postura global de Jesús G. Maestro.

### 4.9 Atomicidad, reintentos e idempotencia

Estado: **Verified**, severidad P1.

La cadena de jobs no constituye una transacción de generación. Entre los riesgos
observados:

- repositorios de nodos y chunks ejecutan commits internos, de modo que un handler
  puede dejar artefactos parciales antes de fallar;
- guardar `embedding_ref` y hacer upsert en Qdrant no forman una operación atómica;
  un retry puede omitir un chunk ya marcado aunque el punto remoto falte;
- parse cleanup y rebuild no eliminan de manera simétrica todos los namespaces de
  propositions, summaries, visual y candidate;
- propositions y summaries usan IDs nuevos; un rebuild incompleto puede mezclar
  generaciones en Qdrant;
- el adapter Qdrant tolera algunas respuestas 400/404 antes de aplicar plenamente la
  política `required`;
- varios zips usan `strict=False` sin convertir diferencias de cardinalidad en error;
- los stale jobs pueden volver a pending sin consumir el mismo contador de retries;
- la ejecución del handler y la transición final del job usan transacciones separadas;
- las tablas principales carecen de varias foreign keys/unique constraints que
  impedirían duplicados u huérfanos.

Rutas de evidencia:

- [sql_node_repo.py](../backend/atenex_nova/infrastructure/db/repositories/sql_node_repo.py)
- [sql_chunk_repo.py](../backend/atenex_nova/infrastructure/db/repositories/sql_chunk_repo.py)
- [ingestion_job.py](../backend/atenex_nova/workers/jobs/ingestion_job.py)
- [qdrant_adapter.py](../backend/atenex_nova/infrastructure/qdrant/qdrant_adapter.py)
- [sql_job_repo.py](../backend/atenex_nova/infrastructure/db/repositories/sql_job_repo.py)
- [runner.py](../backend/atenex_nova/workers/runner.py)
- [tables.py](../backend/atenex_nova/infrastructure/db/models/tables.py)

La consecuencia es epistemológica, no solo operacional: sin generación y
reconciliación, una respuesta no puede declarar qué versión coherente de la memoria
consultó.

### 4.10 Integridad de importación y amplificación

Estado: **Verified**, severidad P1.

Upload lee archivos completos en memoria. El camino de deduplicación por checksum
puede devolver un documento existente sin reencolar uno fallido. La importación local
hashea archivos en el flujo de sesión y no congela el contenido entre checksum y parse.

La sesión observada declaró 1.789 descubiertos, 1.787 intentados, 1.347 creados y 440
deduplicados; dos archivos no quedaron explicados por esos contadores. `completed` no
valida esa igualdad.

Con SQL debug activo, la persistencia cuantizada ejecuta además patrones N+1 y emite
grandes trazas. Esto contribuye a que 56 MiB de uploads produzcan 1,8 GiB de SQLite y
147 MiB de WAL. La amplificación no es por sí sola un bug, pero debe presupuestarse y
medirse por capa.

## 5. Auditoría de índices y retrieval

### 5.1 Topología de índices incompleta

Estado: **Verified**.

La documentación y el código contemplan colecciones Qdrant para chunks,
propositions, summaries y pages. El runtime exponía solo
`collection_<id>_propositions`, sparse-only. En consecuencia:

- chunks densos dependen del candidate index SQL;
- chunks sparse no disponen de su colección esperada;
- summaries recurren a carga SQL y scoring local;
- visual no tiene una colección viva verificable;
- propositions se reparten entre códigos cuantizados parciales y Qdrant sparse.

La ausencia de una capa no siempre activa el fallback más seguro. Si PurePy devuelve
algún candidato denso, el sistema puede conservar esos candidatos y no ejecutar un
BM25 local completo de chunks aunque la colección sparse de Qdrant no exista.

### 5.2 El candidate index PurePy es búsqueda exhaustiva

Estado: **Verified**, severidad P0 operacional.

`PurePyTurboQuantCandidateIndex.search()` carga todos los códigos de una capa, estima
el producto interno de todos y ordena el resultado. No usa HNSW, IVF, partición o
streaming top-k.

El estimador materializa tres matrices principales `N × 384`:

```text
idx_matrix      int32
signs_matrix    float32
hat_v_rot       float32
```

Con 651.223 propositions cuantizadas en el snapshot, estas matrices representan
aproximadamente 2,80 GiB antes de objetos ORM, blobs y temporales. Si se cuantizan las
788.945 propositions, las tres matrices rondan 3,39 GiB.

Rutas:

- [purepy_candidate_index.py](../backend/atenex_nova/infrastructure/indexes/purepy_candidate_index.py)
- [turboquant_adapter.py](../backend/atenex_nova/infrastructure/vector_quantization/turboquant_adapter.py)

La prueba controlada confirmó el costo práctico: `score_propositions` tardó entre
48,15 y 69,47 segundos en las consultas observadas. Esto no es candidate generation
sublineal y empeora conforme avanza el worker.

### 5.3 Descubrimiento limitado a 50 documentos

Estado: **Verified**.

`RetrievalOrchestrator.search()` llama `list_by_collection(collection_id)` sin pasar
límite. `SqlDocumentRepository.list_by_collection` usa `limit=50`. El mapa de títulos
y parte de la carga de summaries de documento/sección quedan restringidos a esos 50,
aunque Qdrant y otras consultas SQL puedan recuperar nodos de más documentos.

Los eventos de la prueba registraron literalmente `documents: 50` para una colección
con 1.754 documentos listos.

Rutas:

- [retrieval_orchestrator.py](../backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py)
- [sql_document_repo.py](../backend/atenex_nova/infrastructure/db/repositories/sql_document_repo.py)

### 5.4 Router heurístico, sin comprensión de intención

Estado: **Verified**.

`QueryRoutingPolicy` detecta modos mediante listas pequeñas de palabras. `global`
requiere marcadores como `corpus`, `resumen`, `global` o `panorama`; conjunciones,
comas o punto y coma pueden disparar `multi_hop`. No hay clasificador entrenado ni
planificador que distinga:

- búsqueda factual;
- reconstrucción de la postura de un autor;
- evaluación de la premisa del usuario;
- síntesis global;
- contraargumentación;
- seguimiento conversacional ambiguo.

La pregunta de eutanasia fue `multi_hop` por ser multicláusula, pero conservó intent
`factual` y terminó en `direct_answer`.

Fuente: [query_routing_policy.py](../backend/atenex_nova/application/policies/query_routing_policy.py).

### 5.5 La conversación no guía el retrieval

Estado: **Verified**.

Los últimos cinco mensajes se incorporan al prompt después de recuperar. Retrieval
usa solo la pregunta actual. Un seguimiento como “explica más, investiga bien e
infiere de todo” pierde el tema anterior durante la búsqueda, aunque el generador vea
después el historial.

Rutas:

- [answer_service.py](../backend/atenex_nova/application/services/answer_service.py)
- [answer_orchestrator.py](../backend/atenex_nova/application/orchestrators/answer_orchestrator.py)

### 5.6 No hay descomposición ni corrección iterativa

Estado: ausencia **Verified**.

El flujo no implementa:

- reescritura ortográfica o contextual;
- expansión semántica o variantes de consulta;
- subpreguntas por faceta;
- recuperación paralela y fusión por cobertura;
- evaluación de suficiencia antes de generar;
- segunda búsqueda ante evidencia pobre;
- traversal iterativo global→local;
- selección long-context de documentos completos.

La falta de normalización fue visible en `eutanacia`: con la pregunta exacta no se
recuperó el pasaje relevante; una búsqueda adicional con `eutanasia` sí ubicó un
pseudo-resumen del video correcto en el rango 5, pero no lo convirtió en una fuente
citable ni en síntesis.

### 5.7 Evidence pack: primero el tipo, luego la relevancia

Estado: **Verified**.

`ContextPackingPolicy` usa:

- presupuesto fijo predeterminado: 2.048 tokens;
- máximo: 8 evidencias para factual/global/visual y 10 para
  multi-hop/argumentative;
- máximo por documento: entre 2 y 3;
- orden lexicográfico por prioridad de `source_type` antes del score;
- deduplicación por tipo, documento y primeros 160 caracteres.

En `multi_hop`, propositions y graph edges tienen más prioridad que chunks. En
`global`, summaries tienen más prioridad que chunks aunque los summaries vivos sean
pseudo-resúmenes no citables. No se optimizan cobertura de facetas, diversidad
semántica, diversidad documental, representatividad temática o supportability.

Fuente: [context_packing_policy.py](../backend/atenex_nova/application/policies/context_packing_policy.py).

### 5.8 Reranking real ausente

Estado: **Implemented** como adapter y **Verified** como degradado en runtime.

El adapter intenta cargar `BAAI/bge-reranker-v2-m3`, pero el entorno vivo no contiene
`torch`. El error se captura y el sistema continúa con una heurística. Health no hace
visible al usuario final que la etapa neural está ausente.

Fuente: [reranker_adapter.py](../backend/atenex_nova/infrastructure/embeddings/reranker_adapter.py).

### 5.9 Sparse no es BM25 corpus-aware

Estado: **Verified**.

El payload vivo identificó el encoder como `lexical_hash`. El fallback calcula pesos
TF normalizados con hashing estable, sin IDF de la colección. Aunque clases y docs usan
el término BM25 en algunos puntos, esta señal no implementa el ranking probabilístico
BM25 dependiente del corpus.

La alternativa SPLADE configurada es inglesa y, si no puede cargar su modelo, el
singleton puede reintentar inicialización en nuevas construcciones. Para Jesús G se
necesita un sparse español/multilingüe evaluado, no un nombre de componente.

Fuente: [bm25_encoder.py](../backend/atenex_nova/infrastructure/embeddings/bm25_encoder.py).

### 5.10 La ruta visual no codifica píxeles

Estado: **Verified**.

El adapter llamado ColPali declara en fuente que es una implementación ligera y
embebe texto de página, no la imagen. Aunque el pipeline puede renderizar páginas, el
modelo activo no recibe píxeles. En STANDARD tampoco había una colección visual viva
verificable.

El health `visual=available` comprueba dependencias básicas y directorio; no prueba
OCR, page retrieval, table-cell accuracy ni visión. La capacidad debe renombrarse como
text-page retrieval o implementar un encoder visual real antes de usar el claim
ColPali.

Fuente: [colpali_adapter.py](../backend/atenex_nova/infrastructure/visual/colpali_adapter.py).

## 6. Auditoría de síntesis, verificación y UI

### 6.1 Los planes cambian prompts, no algoritmos

Estado: **Verified**.

`AnswerPlanningPolicy` decide:

- factual/exact → `direct_answer`;
- más de ocho ítems → `hierarchical_synthesis`;
- global con summaries → `global_synthesis`;
- contradicciones → `argument_synthesis`.

No existe un map por documento, síntesis por cluster, reducción por tema ni una
segunda pasada integradora. “Hierarchical” es el nombre de un prompt aplicado a una
sola llamada LLM.

Además, un `multi_hop` con exactamente ocho evidencias o menos cae en
`direct_answer`. La pregunta de eutanasia seleccionó seis.

Fuente: [answer_planning_policy.py](../backend/atenex_nova/application/policies/answer_planning_policy.py).

### 6.2 El prompt directo produce el comportamiento de buscador

Estado: **Verified**.

El prompt ordena responder solo desde la evidencia, preferir afirmaciones concisas y
factuales, y retornar una respuesta corta. Es una política razonable para fechas o
códigos, pero inadecuada para una pregunta que exige reconstruir tesis, matiz,
excepción y conclusión.

Fuente: [DIRECT_ANSWER_PROMPT.md](../prompts/DIRECT_ANSWER_PROMPT.md).

El prompt global es más largo, pero no puede compensar dos pseudo-resúmenes sin la
evidencia relevante. Prompt engineering no repara información que no entra al pack.

### 6.3 Grounding no es entailment

Estado: **Verified**.

El score determinista calcula, principalmente:

```text
0,55 × cobertura de tokens de la respuesta presentes en alguna evidencia
+ 0,45 × cantidad normalizada de citas
```

No divide la respuesta en claims ni comprueba para cada uno:

- soporte;
- contradicción;
- fuente correcta;
- alcance de la cita;
- inferencia válida;
- cobertura total.

El verificador LLM usa el mismo generador, espera texto libre y puede fallar sin
producir una señal semántica estructurada. Puede bajar el score, pero no convierte el
overlap base en entailment.

Fuente: [answer_orchestrator.py](../backend/atenex_nova/application/orchestrators/answer_orchestrator.py).

### 6.4 Binding de cita no demuestra soporte

Estado: **Verified**.

El binder confirma que `[n]` existe, que el ítem tiene documento y que se puede
resolver un span. Esto evita índices inventados, pero no prueba que la frase vecina
esté sustentada por esa fuente. Graph edges y summaries sin documento pueden aparecer
en el prompt y en marcadores intermedios, pero no convertirse en citas documentales
válidas.

Los offsets se calculan sobre texto normalizado, no necesariamente sobre el artefacto
original que vería el usuario.

### 6.5 La UI no comunica bien la incertidumbre

Estado: **Verified**.

La alerta principal exige simultáneamente grounding menor que 0,55 y menos de dos
citas; no usa el `verdict` como condición suficiente. Una respuesta `unverified` con
score alto por overlap y varias citas puede presentarse sin alerta principal.

La evidencia visible se limita normalmente a cinco elementos y la cita prioriza UUID
en lugar de título, pasaje y navegación clara al original.

Rutas:

- [ChatMessage.tsx](../frontend/src/components/ChatMessage.tsx)
- [Pages.tsx](../frontend/src/pages/Pages.tsx)
- [CitationSidebar.tsx](../frontend/src/components/CitationSidebar.tsx)

### 6.6 Persistencia y payload excesivos

Estado: **Verified**.

Se persisten el prompt completo y metadata con `source_text` íntegro. El detalle de la
respuesta de Cervantes pesó aproximadamente 712 KiB para una respuesta final de 112
tokens. Esto aumenta I/O, latencia, exposición de texto y tamaño de base sin mejorar el
contexto que recibió el generador.

Rutas:

- [answer_orchestrator.py](../backend/atenex_nova/application/orchestrators/answer_orchestrator.py)
- [sql_answer_repo.py](../backend/atenex_nova/infrastructure/db/repositories/sql_answer_repo.py)

### 6.7 La evaluación implementada no mide la capacidad objetivo

Estado: **Implemented / Verified** como harness mínimo; el benchmark de corpus está
**Planned**.

El dataset incorporado tiene cuatro preguntas genéricas en inglés, no casos de Jesús
G. La base viva auditada tenía cero evaluation runs y cero cases.

`AnswerScorer` mide presencia de tokens de la respuesta esperada, overlap con
evidencias y cantidad de citas. No mide entailment, postura autoral, coherencia,
comprehensiveness, inferencia, contradicciones o citation recall por claim.

Además, `EvaluationService` llama primero a `search_only` para puntuar retrieval y
después a `answer()`, que vuelve a recuperar. La respuesta puede evaluarse contra un
pack distinto del que recibió el generador.

Rutas:

- [baseline.json](../backend/atenex_nova/evaluation/datasets/baseline.json)
- [answer_scorer.py](../backend/atenex_nova/evaluation/scorers/answer_scorer.py)
- [evaluation_service.py](../backend/atenex_nova/application/services/evaluation_service.py)

## 7. Experimentos de respuesta

### 7.1 Pregunta exacta de eutanasia

Consulta reproducida:

```text
Si fuera mas facil los tienen miedo a suicidarse lo harian por eso quieren la
eutanacia dice que uno es dueño de su vida y ojala una sociedad que pueda decidir si
vivir su vida o no por eso quieren la eutanacia, asi son libres.
```

Resultados sobre la copia aislada:

| Configuración | Ruta / plan | Pack | Resultado | Veredicto / grounding | Tiempo observado |
|---|---|---:|---|---|---:|
| `mode=auto` | `multi_hop → direct_answer` | 6 | Afirmó que no había menciones directas de eutanasia; cuatro graph edges y dos pseudo-resúmenes irrelevantes. | `unverified` / 0,261 / 0 citas | retrieval 70,27 s; compose 79,37 s |
| `mode=global` | `global → global_synthesis` | 2 | Afirmó de nuevo que el corpus no trataba la eutanasia; solo dos pseudo-resúmenes no citables. | `unverified` / 0,232 / 0 citas | retrieval 87,10 s; compose 153,58 s |
| búsqueda corregida con `eutanasia` | `factual_local` | 10 hits | El video relevante apareció como pseudo-resumen en rango 5. | no generó respuesta | retrieval 58,17 s |

Identificadores de la copia de auditoría:

```text
auto query:   94910fb6-32b7-4dba-9dd6-59b61a8aca01
global query: b9a14860-cf02-4d82-aafd-0ae19e0e06fb
search query: 9f9468e3-91bc-403b-82f7-583bdbe78d76
```

Estos IDs no existen en producción y se conservan solo como referencia del ensayo.

### 7.2 El corpus sí contiene la respuesta

Una consulta SQLite de solo lectura encontró `eutanasia` en 22 documentos. El video
titulado *Don Quixote versus 21st-century euthanasia. Literature defends real life,
not imaginary life* desarrolla, entre otros, estos puntos:

- crítica a presentar la muerte como libertad;
- diferencia entre derecho general y recurso ante enfermedad terminal;
- contraste entre élites que buscan longevidad y eutanasia ofrecida al pueblo;
- defensa literaria de la vida;
- el pasaje final de Sancho sobre no dejarse morir por melancolía.

Es decir, NotebookLM no necesitó inventar la estructura principal de su respuesta.
La mayor parte está explícitamente disponible en el corpus. Atenex produjo un falso
negativo de retrieval/síntesis.

### 7.3 Historial vivo de Cervantes y amor

La respuesta reportada por el usuario quedó persistida con:

- ruta `factual_local`;
- plan `direct_answer`;
- 8 evidencias;
- tres pseudo-resúmenes de colección entre los primeros resultados;
- prompt de 2.291 tokens y respuesta de 112;
- dos intentos por bajo grounding;
- `partially_verified`, score 0,595;
- retrieval aproximado 17,8 s y composición 105,8 s.

El seguimiento que pedía investigar e inferir usó el historial solo en generación,
recuperó seis propositions ruidosas y dos pseudo-resúmenes, no seleccionó chunks y
volvió a `direct_answer`. Esto explica por qué una petición explícita de análisis no
cambió la naturaleza de la respuesta.

### 7.4 Qué demuestran y qué no demuestran

Los ensayos demuestran:

- falso negativo sobre evidencia presente;
- routing/planning inadecuados;
- memory summaries no funcionales como corpus summary;
- sensibilidad a ortografía;
- latencia creciente en propositions;
- insuficiencia de forzar manualmente `global`.

No demuestran:

- una tasa promedio de error;
- superioridad estadística de NotebookLM;
- que Gemma 4 no pueda sintetizar con evidencia adecuada;
- que una sola técnica SOTA vaya a resolver todo el sistema.

## 8. Comparación rigurosa con NotebookLM

Según la documentación oficial vigente de Google:

- NotebookLM es un asistente fundamentado en las fuentes seleccionadas;
- cuando existen muchas fuentes, primero recupera información relevante y después
  construye la respuesta;
- el chat normal usa esas fuentes y ofrece citas navegables;
- el plan Pro admite 300 fuentes por notebook, que coincide con el límite observado
  por el usuario;
- otros planes publican límites distintos, incluyendo 500/600 en Ultra;
- cada fuente puede alcanzar 500.000 palabras o 200 MB.

Fuentes oficiales:

- [planes y límites](https://support.google.com/notebooklm/answer/16213268)
- [descripción del producto](https://support.google.com/notebooklm/answer/16164461)
- [chat y citas](https://support.google.com/notebooklm/answer/16179559)
- [notebooks y fuentes](https://support.google.com/notebooklm/answer/16206563)

No existe evidencia pública suficiente para afirmar que NotebookLM use internamente
RAPTOR, GraphRAG, DRIFT o un grafo de propositions. La comparación correcta es por
capacidades observables:

| Capacidad | NotebookLM en el ejemplo | Atenex observado |
|---|---|---|
| Entender una premisa coloquial con error ortográfico | Reconstruye la cuestión | No corrige `eutanacia`; deriva a evidencia de libertad genérica. |
| Recuperar el documento decisivo | Sí, por el contenido de la respuesta | No entra al pack en la consulta exacta. |
| Formular una tesis central | Sí | Responde como lookup o abstención. |
| Integrar cadena argumentativa | Sí | No hay planificación por facetas. |
| Introducir matiz/excepción | Sí | El pack no contiene el pasaje terminal. |
| Conservar la postura del corpus | Alta en el ejemplo | No se mide ni modela explícitamente. |
| Citar fuentes navegables | Producto lo soporta | Binding existe, pero las evidencias elegidas pueden no ser citables. |
| Síntesis global verificable | Capacidad observable, arquitectura desconocida | `global_synthesis` es una llamada sobre pseudo-resúmenes. |

Tener 1.700 archivos no es una ventaja si la representación es defectuosa. Trescientos
documentos bien segmentados, recuperables y sintetizables pueden superar 1.700
documentos cuyos vectores representan prefijos y cuyas memorias globales son
extractos sin procedencia.

## 9. Contraste con el estado del arte

Las referencias siguientes no son recetas para copiar sin evaluación. Definen
capacidades ausentes y baselines de diseño.

### 9.1 Memoria jerárquica y sentido global

**RAPTOR** agrupa y resume chunks recursivamente para recuperar distintos niveles de
abstracción. Es la referencia directa para sustituir filas llamadas summary por una
jerarquía realmente recuperable y evaluada. Véase
[RAPTOR, ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8a2acd174940dbca361a6398a4f9df91-Abstract-Conference.html).

**GraphRAG** parte del mismo gap observado aquí: top-k de chunks no responde bien a
preguntas sobre temas y tendencias del corpus. Extrae entidades/relaciones, detecta
comunidades, produce reportes y ejecuta una reducción global. Véanse el
[paper](https://arxiv.org/abs/2404.16130) y la
[documentación oficial](https://microsoft.github.io/graphrag/).

**DRIFT** combina reportes globales con búsquedas locales iterativas y preguntas de
seguimiento. Funcionalmente se acerca más a “investiga e infiere” que una única
consulta. Véase
[Microsoft Research](https://www.microsoft.com/en-us/research/blog/introducing-drift-search-combining-global-and-local-search-methods-to-improve-quality-and-efficiency/).

### 9.2 Retrieval contextual y reranking

La propuesta de
[Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)
añade a cada chunk una explicación breve de su contexto documental antes de indexar
dense y BM25, recupera un pool amplio y aplica reranking. Sus cifras deben
revalidarse en español, pero el principio es relevante: un pasaje ASR necesita título,
tema y posición para ser recuperable.

[ColBERT](https://arxiv.org/abs/2004.12832) aporta late interaction token a token como
baseline académico para ranking fino. Antes de adoptarlo, Atenex debe garantizar
chunks correctos; ningún reranker recupera texto destruido o truncado durante ingesta.

### 9.3 Retrieval adaptativo

[Self-RAG](https://proceedings.iclr.cc/paper_files/paper/2024/file/25f7be9694d7b32d5cc670927b8091e1-Paper-Conference.pdf)
aprende cuándo recuperar y cómo criticar evidencia; no equivale a añadir un prompt de
verificación.

[Corrective RAG](https://arxiv.org/abs/2401.15884) evalúa la calidad del retrieval y
activa acciones correctivas. Para Atenex local-first, el patrón útil es:

```text
evaluar suficiencia → responder | ampliar localmente | reformular | ruta global | abstenerse
```

No es necesario copiar el fallback web de CRAG.

### 9.4 Long context como ruta, no como dogma

[Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/) muestra que una ventana
grande tampoco garantiza usar evidencia situada en posiciones intermedias.

Una comparación posterior encontró que long-context podía superar RAG cuando había
recursos, mientras RAG conservaba ventaja de costo; Self-Route eligió entre ambos.
Véase [Li et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-industry.66/).

La consecuencia para Atenex es un router por costo y necesidad:

- lookup local preciso;
- recuperación jerárquica/global;
- traversal multi-hop;
- long context sobre pocos documentos completos elegidos con alta confianza.

### 9.5 Evaluación diagnóstica

[RAGChecker](https://proceedings.neurips.cc/paper_files/paper/2024/hash/27245589131d17368cccdfa990cbf16e-Abstract.html)
separa errores de retriever y generador a nivel de claims.

[RAGAS](https://aclanthology.org/2024.eacl-demo.16/) es útil para iteración
reference-free, pero no reemplaza goldens humanos.

[ALCE](https://arxiv.org/abs/2305.14627) separa fluidez, corrección y calidad de
citas. Su énfasis en citation recall es crucial: citar correctamente dos afirmaciones
no compensa omitir soporte para otras ocho.

## 10. Auditoría de la tesis

Estado: claims del PDF **Historical**. El artefacto no permite reproducirlos.

La tesis presenta una arquitectura RAG contemporánea y defendible como proyecto de
ingeniería: parsing estructural, recuperación híbrida, memoria multicapa, routing,
visual, verificación y citas. Declara correctamente que la contribución es de
integración y evaluación, no un nuevo modelo fundacional (PDF pp. 15–19 y 35–42).

El protocolo propuesto también es razonable. Define 640 preguntas públicas, 60
institucionales, baselines, tres corridas, desviación estándar, comparación pareada y
bootstrap al 95 % (PDF pp. 45–49).

El problema es que el capítulo de resultados no deja auditar los claims. Reporta,
entre otros, Recall@10 0,914, Answer Correctness 0,846, Faithfulness 0,934 y Citation
Precision 0,921, pero no incluye:

- IDs de preguntas y evidencia gold;
- splits, seeds o muestreo;
- prompts y configuración completa;
- `top_k`, pesos, chunking o parámetros de reranking;
- modelo juez y calibración;
- resultados por corrida;
- desviaciones, intervalos o pruebas pareadas prometidas;
- logs, exports o commit reproducible;
- muestra humana, revisores o acuerdo interanotador.

El protocolo estadístico está en la p. 49 y los resultados en pp. 50–59; estos últimos
no muestran las desviaciones, intervalos ni comparaciones pareadas prometidas.

Además:

- `Context Recall` coincide numéricamente con `Recall@10` en las tablas, aunque son
  conceptos distintos;
- se privilegia Citation Precision sin demostrar Citation Recall/Source Coverage;
- no se mide la calidad de propositions, summaries, grafo, OCR o detección de
  contradicciones;
- `NotebookLM-style` está explícitamente simulado en la p. 47, no es NotebookLM real;
- la mayor parte de benchmarks no representa ensayo filosófico oral en español;
- no hay un desglose para fidelidad a la postura del autor o síntesis de Jesús G;
- la portada indica diciembre de 2025, mientras el PDF fue creado el 2026-05-14 y
  contiene referencias de 2026; debe versionarse o explicarse.

La conclusión rigurosa no es “los resultados son falsos”. Es: el PDF no permite
distinguir resultados reales, sintéticos o preliminares. No deben usarse como evidencia
de superioridad hasta publicar un paquete reproducible.

## 11. Auditoría de EOS y la hipótesis de AGI

Estado: `/mnt/ssd/Mark/EOS/EOS_core/README.md` es **Planned**, no una implementación
verificada.

La intuición de EOS —memorias y actualizaciones a distintas escalas temporales— es
valiosa. El pseudocódigo actual, sin embargo, describe una recurrencia semejante a GRU:

- `h_t` es una activación, no parámetros de memoria actualizados por gradiente;
- `h` se reinicia desde `h0` en cada `forward`;
- inference usa `torch.no_grad()`;
- el output head vuelve a dimensión de embedding, no a logits de vocabulario;
- MSE sobre embeddings no entrena generación next-token;
- el copy task entrega IDs donde el modelo espera vectores, salvo paso omitido;
- `TransformerBaseline(...)` es placeholder;
- el diccionario de resultados está hardcodeado;
- todo el checklist permanece sin marcar.

Por ello, EOS no implementa Titans, Nested Learning/Hope, test-time learning ni
memoria persistente entre sesiones.

**Titans** actualiza parámetros de una red de memoria durante test-time mediante una
pérdida asociativa y una señal de sorpresa; conserva atención de ventana y mecanismos
de olvido. No afirma memoria infinita. Véanse
[Google Research](https://research.google/pubs/titans-learning-to-memorize-at-test-time/)
y el [paper](https://arxiv.org/abs/2501.00663).

**Nested Learning/Hope** formula problemas de optimización anidados con diferentes
frecuencias de actualización y un continuum de memoria. Hope es una prueba de concepto
de investigación, no una arquitectura AGI demostrada. Véanse
[NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/4309616aaed8e848009bc4a7ef73b493-Abstract-Conference.html)
y la [explicación oficial](https://research.google/blog/introducing-nested-learning-a-new-ml-paradigm-for-continual-learning/).

La bibliografía de EOS atribuye “Learning to Memorize at Test Time” a Munkhdalai et
al. (2024), pero Titans corresponde a Behrouz, Zhong y Mirrokni. Debe corregirse.

### 11.1 Qué sí puede ser Atenex + EOS

Una agenda defendible tendría cuatro memorias separadas:

1. **Memoria de trabajo:** ventana acotada del LLM.
2. **Memoria de sesión:** adaptación neural temporal, experimental y aislada.
3. **Memoria documental durable:** Atenex, versionada, con procedencia y rollback.
4. **Consolidación validada:** convierte solo interacciones revisadas en conocimiento
   persistente.

La memoria neural no debería escribir directamente al corpus confiable. La frontera
de consolidación necesita protección contra poisoning, contaminación entre tenants,
olvido catastrófico, bucles de alucinación y deriva temporal.

Esta arquitectura podría producir un asistente cognitivo local con memoria efectiva
amplia. Aun así, no demuestra AGI. Faltarían aprendizaje de habilidades, transferencia
abierta, planificación y agencia robustas, calibración, seguridad, evaluación
longitudinal y generalidad fuera del corpus.

## 12. Clasificación epistemológica

### 12.1 Observado y verificado

- Código y políticas descritos en este documento.
- Conteos de SQLite, Qdrant y storage.
- Contexto declarado por EmbeddingGemma.
- Ausencia de Docling, TurboVec, torch y summary vectors.
- Backlog y semántica prematura de `READY`.
- Preguntas/answers/route/plan/evidencias de la copia aislada.
- Evidencia explícita de eutanasia presente en el corpus.
- Latencias registradas por pipeline audit.

### 12.2 Inferido con alta confianza

- Los vectores de chunks mayores de 2.048 no representan íntegramente su cola.
- Chunks sobredimensionados, prefijos de embedding y ausencia de sparse chunk
  degradan recall.
- Los pseudo-resúmenes no permiten una síntesis global fiel.
- PurePy presenta riesgo de OOM y degradación aproximadamente lineal con el número de
  vectores.
- La respuesta NotebookLM aportada se apoya principalmente en evidencia explícita del
  corpus, no solo en conocimiento externo.

### 12.3 Pendiente de medir

- Truncación exacta con el tokenizer real por documento.
- Recall perdido por no usar los prefijos oficiales.
- Deriva exacta SQL↔Qdrant por generación.
- Calidad de propositions y summaries mediante muestra anotada.
- Comparación ciega Atenex↔NotebookLM sobre fuentes idénticas.
- Beneficio incremental de RAPTOR, GraphRAG, contextual retrieval y long context.
- Coste y estabilidad de una memoria neural EOS real.

## 13. Riesgos priorizados

| Prioridad | Riesgo | Impacto |
|---|---|---|
| P0 | Chunks mayores que el contexto de embedding | Contenido invisible para dense retrieval. |
| P0 | `READY` sin memoria completa | UI y evaluación operan sobre índices parciales. |
| P0 | Pseudo-resúmenes de colección | Modo global responde desde artefactos locales no citables. |
| P0 | PurePy exhaustivo | Latencia creciente y riesgo de varios GiB por consulta. |
| P0 | Corpus administrativo ingerido | Ruido domina memoria y costo. |
| P0 | No hay benchmark Jesús G | No existe puerta objetiva de calidad. |
| P1 | Límite accidental de 50 documentos | Metadatos y summaries incompletos. |
| P1 | Query actual sin historial | Seguimientos pierden el tema durante retrieval. |
| P1 | Router por keywords | Selección errónea de motor y plan. |
| P1 | Propositions/grafo heurísticos | Volumen, ruido y relaciones espurias. |
| P1 | Verificador lexical | Confianza no equivale a soporte. |
| P1 | Índices sin generación/reconciler | Mezcla o deriva entre stores. |
| P2 | Payload completo y SQL debug | I/O, tamaño y exposición innecesarios. |
| P2 | UI no usa verdict como alerta | Riesgo de confianza indebida. |
| P2 | Visual no es encoder de píxeles | Claim funcional mayor que la capacidad real. |

## 14. Recomendación final

No conviene optimizar primero el prompt ni aumentar indiscriminadamente `top_k`. La
secuencia correcta es:

1. construir un benchmark Jesús G y congelar un snapshot;
2. corregir frontera de corpus y segmentación;
3. reconstruir embeddings e índices coherentes;
4. verificar recall antes de generar;
5. implementar memoria jerárquica y planificación iterativa;
6. verificar claims/citas y solo después optimizar estilo, modelo y latencia.

El plan ejecutable, con puertas de aceptación y orden de migración, está en
[plan-rag-sintesis-corpus.md](plan-rag-sintesis-corpus.md).
