# Ledger de reconstrucción del RAG hacia síntesis de corpus

Estado del ledger: **Implemented**. Registra el orden técnico, las entregas y las
puertas derivadas de la
[auditoría del 2026-08-02](auditoria-rag-respuestas-sota-2026-08-02.md). Un artefacto
puede estar **Implemented / Verified** en pruebas sin que su gate o el runtime vivo
estén cerrados. G0–G6 permanecen **Planned**.

## 1. Objetivo

Transformar el RAG documental de Atenex Nova de una búsqueda monodisparo con
generación a un asistente local capaz de:

- recuperar evidencia explícita aunque esté distribuida o escrita con variantes;
- reconstruir la postura de un autor sin inventarla;
- distinguir evidencia, inferencia y conocimiento externo;
- sintetizar niveles chunk→documento→tema→corpus;
- mantener conversación sin perder el referente durante retrieval;
- citar cada claim verificable y declarar cobertura insuficiente;
- actualizar el corpus incrementalmente sin mezclar generaciones;
- operar en hardware local con latencia, memoria y calidad medidas.

La meta no es imitar una arquitectura interna desconocida de NotebookLM. La meta es
alcanzar y medir las capacidades observables relevantes para el corpus Jesús G.

## 2. No objetivos inmediatos

- Declarar AGI.
- Eliminar toda ventana de contexto.
- Entrenar un foundation model desde cero.
- Incorporar EOS al camino crítico antes de validar la memoria documental.
- Añadir un grafo masivo sin comprobar que mejora tareas.
- Usar un juez LLM como única evidencia de calidad.
- Hacer un rebuild definitivo mientras el chunking y los índices sigan defectuosos.
- Aumentar `top_k` como sustituto de cobertura, diversidad y planificación.

## 3. Principios de diseño

1. **Evaluación antes de optimización.** Cada fase empieza con un baseline y termina
   con una puerta cuantitativa.
2. **Fuente original como autoridad.** Todo artefacto derivado conserva procedencia,
   generación y offsets recuperables.
3. **Memoria derivada es lossy.** Propositions, summaries y graph nunca sustituyen
   el texto fuente.
4. **Completitud por generación.** Ningún documento ni colección se declara listo con
   capas parciales o mezcladas.
5. **Retrieval antes de generation.** Un generador no puede reparar evidencia que no
   fue recuperada.
6. **Cobertura y diversidad.** El pack debe optimizar facetas y supportability, no
   solo score individual.
7. **Corrección adaptativa.** Evidencia insuficiente activa reformulación, expansión,
   otra ruta o abstención.
8. **Inferencia etiquetada.** Una conclusión derivada se presenta como tal y enlaza
   sus premisas.
9. **Degradación visible.** Reranker, visual, summaries o graph ausentes cambian el
   estado de capacidad y la UI.
10. **Local-first medido.** Calidad, p50/p95/p99, RAM, VRAM, disco e ingesta forman
    parte del contrato.

## 4. Ledger de ejecución

| Frente | Implementación y evidencia | Runtime/gate |
|---|---|---|
| Benchmark | scorer claim-oriented y dataset semilla Jesús G versionados; pruebas focalizadas **Verified** | 150 preguntas, dos anotadores y baseline vivo **Planned**; G0 **Planned** |
| Frontera y parsing | allowlist, exclusiones, transcript timestamps/offsets y metadata estructural **Implemented / Verified** | snapshot/rebuild completo **Planned**; G1 **Planned** |
| Chunking/embeddings | hard cap 800, overlap 80, source spans, prefijos query/documento, cardinalidad y fingerprint `emb-v2` **Implemented / Verified** | reconstrucción de todos los vectores vivos **Planned**; G1 **Planned** |
| Índices | Qdrant dense primario, schema guard, IDs estables, cap PurePy y rechazo legado **Implemented / Verified** | `generation_id`, reconciler y activación atómica definitivos **Planned**; G2 **Planned** |
| Retrieval | paginación completa, follow-up contextual, hasta tres facetas, RRF y corrección `eutanacia` **Implemented / Verified** | Recall/latencia vivos y reranker calibrado **Planned**; G2 **Planned** |
| Memoria | summaries sección/documento con procedencia y una memoria extractiva de colección explícita **Implemented / Verified** | temas, contradictions y graph cross-document **Planned**; G3 **Planned** |
| Readiness | barrera temporal, democión y reparación mínima **Implemented / Verified** | coherencia por una generación común **Planned**; G1/G2 **Planned** |
| Síntesis | packing por cobertura, planner y map-reduce acotado para rutas complejas **Implemented / Verified** | comprehensiveness humana y corrección iterativa **Planned**; G4 **Planned** |
| Confianza/UX | claim audit, verificador conservador, payload compacto y UI guiada por verdict **Implemented / Verified** | entailment independiente, calibración y E2E vivo **Planned**; G5 **Planned** |
| Comparación | protocolo definido | NotebookLM/EOS sobre corpus comparable **Planned**; G6 **Planned** |

La evidencia **Verified** anterior procede de tests focalizados, no del índice vivo
auditado el 2026-08-02. Como los prefijos y el fingerprint cambiaron, ese índice es
incompatible con `emb-v2` y no debe usarse para atribuir calidad a estas entregas.

## 5. Arquitectura objetivo

```text
                         ┌────────────────────────────┐
                         │ snapshot de corpus         │
                         │ allowlist + manifest       │
                         └─────────────┬──────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ parsing y chunking         │
                         │ unidades discursivas       │
                         │ hard cap del tokenizer     │
                         └─────────────┬──────────────┘
                                       │
                 ┌─────────────────────┼──────────────────────┐
                 │                     │                      │
       ┌─────────▼────────┐  ┌─────────▼────────┐  ┌─────────▼────────┐
       │ índice lexical   │  │ índice dense ANN │  │ memoria derivada │
       │ corpus-aware     │  │ query/documento  │  │ jerárquica       │
       └─────────┬────────┘  └─────────┬────────┘  └─────────┬────────┘
                 └─────────────────────┼──────────────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ planner de consulta        │
                         │ rewrite + facets + route   │
                         └─────────────┬──────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ multi-retrieval + fusion   │
                         │ rerank + diversity         │
                         └─────────────┬──────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ suficiencia y corrección   │
                         │ ampliar/reformular/abstener│
                         └─────────────┬──────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ síntesis por faceta        │
                         │ map → integrate → answer   │
                         └─────────────┬──────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ claims + entailment + citas│
                         │ explícito/inferencia/gap   │
                         └────────────────────────────┘
```

## 6. Orden de ejecución

Las fases son acumulativas. No se debe iniciar una reconstrucción completa del corpus
antes de cerrar las fases 0 y 1.

### Fase 0 — Congelar evidencia y construir el benchmark

Estado: **Implemented / Verified** para el dataset semilla y los scorers por claim.
El benchmark de 150 preguntas y G0 permanecen **Planned**, prioridad P0.

#### Trabajo

1. Congelar un snapshot reproducible del corpus Jesús G:

   - manifest de archivos, checksums y tamaño;
   - lista explícita de contenido incluido/excluido;
   - versión de parsers, modelos, prompts y código;
   - generación única en todos los stores.

2. Crear un dataset versionado con preguntas reales en español:

   - exactas y factuales;
   - postura del autor;
   - globales y temáticas;
   - multi-hop;
   - argumentativas;
   - contradicciones y evolución temporal;
   - lenguaje coloquial, errores ortográficos y premisas imperfectas;
   - seguimientos conversacionales;
   - no respondibles y fuera de corpus;
   - tablas/visual solo si existe esa evidencia.

3. Para cada caso registrar:

   - pregunta original y versión normalizada;
   - ruta esperada solo como hipótesis, no como gold rígido;
   - documentos y spans mínimos requeridos;
   - facetas que la respuesta debe cubrir;
   - postura/tesis esperada;
   - excepciones o matices requeridos;
   - claims aceptables y no aceptables;
   - respuesta de referencia cuando sea posible;
   - condición de abstención;
   - rúbrica humana.

4. Incluir de inmediato:

   - la pregunta exacta de eutanasia;
   - versión ortográficamente corregida;
   - la consulta de Cervantes y amor;
   - el seguimiento “investiga e infiere de todo”;
   - preguntas donde una sola transcripción contiene la respuesta;
   - preguntas que realmente requieren varios documentos.

5. Persistir trazas desacopladas:

   - candidatos por motor;
   - pack seleccionado;
   - respuesta;
   - claims;
   - citas;
   - latencias y memoria.

#### Puerta G0

Estado: **Planned**.

- Dataset con al menos 150 preguntas piloto, de las cuales 50 sean
  globales/argumentativas y 30 conversacionales o con ruido lingüístico.
- Al menos dos anotadores en una muestra de 30 casos.
- Acuerdo reportado para facetas, supportability y postura autoral.
- Ejecución baseline del sistema actual guardada como artefacto, sin editar sus
  resultados.
- Ningún claim de mejora hasta cerrar esta puerta.

### Fase 1 — Corregir la memoria primaria

Estado: **Implemented / Verified** en pruebas focalizadas para frontera de corpus,
transcripciones, hard cap 800/overlap 80, spans, prefijos query/documento y fingerprint
`emb-v2`. El rebuild del corpus vivo y G1 permanecen **Planned**, prioridad P0.

#### 1.1 Frontera de corpus

- Allowlist de formatos de contenido.
- Exclusiones explícitas para `_meta`, manifests, exports, sidecars, bases, ZIP y
  artefactos administrativos.
- Tamaño máximo y detector de texto/binario.
- Snapshot inmutable del archivo entre checksum y parse.
- Reporte de archivos descubiertos, aceptados, excluidos, deduplicados y fallidos cuya
  suma sea consistente.

#### 1.2 Parsing de transcripciones

- Reconocer envelope, captions, timestamps y turnos.
- Normalizar saltos, puntuación ASR y ruido sin alterar la fuente original.
- Conservar pares `original_offset ↔ normalized_offset`.
- Detectar unidades discursivas: oración, párrafo, bloque temporal, sección y video.
- Propagar título, playlist, canal, idioma y posición como metadata, no como contenido
  dominante.

#### 1.3 Chunking con hard cap real

- Usar el tokenizer del modelo activo.
- Subdividir cualquier nodo individual que exceda el máximo.
- Objetivo inicial: 384–768 tokens, hard cap inferior al contexto del encoder.
- Overlap pequeño y medido, preferentemente en límites de oración.
- Contexto de documento/sección separado del cuerpo del chunk.
- Rechazar o diagnosticar cualquier chunk que viole el hard cap.

#### 1.4 Embeddings

- Usar prefijos query/documento oficiales de EmbeddingGemma.
- Aplicar batching real.
- Enviar `truncate=false` cuando el runtime lo soporte y tratar overflow como error.
- Validar cardinalidad y dimensión de cada batch.
- Persistir modelo, digest, dimensión, task prefix y tokenizer en la generación.

#### Puerta G1

Estado: **Planned**.

- Cero chunks mayores que el contexto del encoder.
- Percentil 99 de chunks dentro del hard cap acordado.
- Cero archivos `_meta` o binarios en memoria consultable.
- 100 % de embeddings con dimensión/cardinalidad verificadas.
- Test con un nodo de 450.000 tokens que produce múltiples chunks válidos.
- La evidencia `cadalso/patíbulo` de la transcripción de eutanasia es recuperable por
  búsqueda exacta y dense.
- Ningún documento `READY` si alguna capa requerida de memoria primaria falta.

### Fase 2 — Índices coherentes y retrieval base

Estado: **Implemented / Verified** para Qdrant dense primario, schema guard, fallback
PurePy acotado, paginación, contexto conversacional y multi-query RRF. Generaciones
atómicas, benchmark y reranker vivo permanecen **Planned**, prioridad P0.

#### 2.1 Generaciones y reconciliación

- Definir `generation_id` en chunks, vectors, Qdrant payloads, summaries y graph.
- Construir una generación staged y activarla atómicamente.
- Reconciler SQL↔Qdrant↔candidate con cardinalidad, checksum y modelo.
- Health por colección/capa/generación, no solo por endpoint.
- Rebuild elimina o archiva todas las capas de la generación anterior.
- Jobs idempotentes con clave única y retries reales.

#### 2.2 Índice lexical y dense

- Qdrant o ANN local real para dense, sin materializar `N × D` completo por consulta.
- Índice sparse corpus-aware para chunks y summaries.
- BM25 real o alternativa multilingüe evaluada; no denominar BM25 a TF hash sin IDF.
- Fallback lexical obligatorio si falta la colección sparse.
- Índices de chunks, summaries y propositions con paridad explícita.
- Mantener propositions fuera del camino crítico hasta demostrar utilidad incremental.

#### 2.3 Query understanding

- Normalización ortográfica conservadora, incluidos acentos y errores frecuentes.
- Reescritura conversacional que incorpore el referente del historial.
- Detección de intención semántica mediante modelo pequeño o LLM estructurado con
  fallback determinista.
- Descomposición en facetas/subpreguntas.
- Variantes lexicales y semánticas acotadas.
- Marcar cuál query produjo cada evidencia.

#### 2.4 Multi-retrieval y reranking

- Ejecutar dense+sparse+title+summary según la ruta.
- Pool inicial amplio y acotado por recursos.
- RRF o fusión aprendida calibrada.
- Reranker multilingüe real, con readiness visible.
- Selección final por relevancia, facetas, diversidad documental, citabilidad y
  redundancia.
- Comparar contextual retrieval frente a chunks sin contexto.

#### Puerta G2

Estado: **Planned**.

- Recall@20 de spans/documentos requeridos ≥0,90 en el piloto global y ≥0,95 en
  factual/exact.
- La pregunta exacta con `eutanacia` recupera el video decisivo en top 5.
- Un seguimiento ambiguo recupera el tema correcto con la conversación.
- Qdrant/SQL/candidate tienen cardinalidad y generación iguales antes de `READY`.
- `score_propositions` y cada motor cumplen p95 y memoria definidos; ninguna búsqueda
  materializa matrices proporcionales a todo el corpus.
- Ablación documenta el aporte de dense, sparse, contextualización y reranker.

### Fase 3 — Memoria jerárquica real

Estado: **Implemented / Verified** para summaries idempotentes de sección/documento
con procedencia y una memoria extractiva de colección explícita. Tema/cluster,
abstracción y grafo cross-document permanecen **Planned**, prioridad P0/P1.

#### 3.1 Resúmenes fundamentados

Construir niveles explícitos:

```text
chunk → sección/bloque → documento/video → tema/cluster → colección
```

Cada summary debe guardar:

- `summary_id`, `generation_id`, nivel y versión de prompt/modelo;
- IDs y spans de todos los hijos;
- claims atómicos con soporte;
- cobertura estimada;
- incertidumbres y contradicciones;
- embedding e índice sparse;
- mecanismo de invalidación incremental.

No crear una fila `collection` por documento. Una colección tiene versiones de
síntesis construidas desde grupos explícitos y reducibles.

#### 3.2 Estrategia a comparar

Implementar como experimentos separados:

- baseline extractivo mejorado;
- jerarquía RAPTOR-like por clustering y resumen recursivo;
- reports de comunidades GraphRAG-like;
- long-context sobre documentos seleccionados.

No combinar todas las técnicas antes de medirlas. El sistema debe permitir ablación.

#### 3.3 Entidades y grafo

- Canonicalizar personas, obras, conceptos y variantes.
- Resolver relaciones cross-document con evidencia y confidence.
- Distinguir coocurrencia, soporte, contradicción, definición y evolución.
- Rechazar relaciones no sustentadas.
- Evitar O(P²) mediante índices invertidos, blocking y top-k por entidad.
- Construir comunidades solo si mejoran preguntas globales.

#### Puerta G3

Estado: **Planned**.

- Summary faithfulness y claim support revisados en una muestra estratificada.
- Coverage de facetas ≥0,85 en resúmenes de documento y colección.
- Cero summary sin procedencia a hijos.
- Consulta global recupera tanto abstracciones como pasajes originales.
- La pregunta de eutanasia reconstruye tesis, argumentos y excepción con spans
  correctos.
- Ablación demuestra que la jerarquía mejora comprehensiveness sin degradar
  faithfulness más allá del umbral acordado.

### Fase 4 — Planificación, síntesis e inferencia controlada

Estado: **Implemented / Verified** para planificación por ruta, packing por cobertura,
map-reduce acotado y claim audit. Suficiencia iterativa, etiquetas
explicit/derived/external y G4 permanecen **Planned**, prioridad P0/P1.

#### 4.1 Planner estructurado

Producir un plan auditable:

```json
{
  "intent": "author_stance",
  "facets": ["tesis", "argumentos", "excepción", "referencia literaria"],
  "routes": ["global", "local"],
  "needs_followups": true,
  "answer_style": "argumentative_synthesis",
  "abstention_policy": "facet-aware"
}
```

El planner no debe confiar ciegamente en una sola clasificación. Debe poder revisar
su plan tras observar evidencia.

#### 4.2 Suficiencia y corrección

Antes de generar:

- medir qué facetas tienen evidencia;
- detectar packs dominados por un solo tipo o documento;
- exigir fuentes citables para claims verificables;
- reformular o ampliar retrieval cuando falten facetas;
- abstenerse por faceta, no necesariamente de toda la pregunta.

#### 4.3 Síntesis real

Para preguntas complejas:

1. map por documento/tema;
2. extracción de claims y posición;
3. reconciliación de repetición/contradicción;
4. integración por faceta;
5. redacción final;
6. reparación solo de claims no soportados.

`hierarchical_synthesis` debe describir este algoritmo, no solo un template.

#### 4.4 Inferencia explícita

Separar en la salida interna:

- `explicit`: dicho por la fuente;
- `derived`: conclusión válida a partir de premisas citadas;
- `external`: conocimiento ajeno al corpus, desactivado por defecto;
- `uncertain`: insuficiencia o ambigüedad.

Una inferencia requiere enlaces a sus premisas. “Analizar” no significa liberar al LLM
de grounding.

#### Puerta G4

Estado: **Planned**.

- Comprehensiveness y coherencia argumentativa superan el baseline en revisión ciega.
- ≥0,90 de claims verificables tienen soporte claim→span.
- Citation recall y precision se reportan juntas.
- Falsos negativos “no hay evidencia” por debajo del umbral definido.
- La respuesta exacta de eutanasia cubre tesis, libertad, dimensión social, excepción
  terminal y referencia literaria sin añadir claims externos.
- Seguimientos mantienen tema y actualizan solo las facetas solicitadas.

### Fase 5 — Verificación, UX y rendimiento

Estado: **Implemented / Verified** para auditoría de soporte/citas por claim, payload
compacto y UI guiada por verdict. Entailment independiente, calibración humana,
performance vivo y G5 permanecen **Planned**, prioridad P1/P2.

#### 5.1 Verificador por claims

- Segmentar salida en claims.
- Entailment/contradiction multilingüe claim→evidence.
- Verificar citation binding y citation coverage.
- Reportar claims no soportados aunque el overlap global sea alto.
- Calibrar score contra revisión humana.
- No usar el mismo generador como única instancia de verificación.

#### 5.2 Contrato de respuesta

La API debe devolver una vista compacta por defecto:

```text
answer
verdict
coverage
claims[] → evidence_ids[] → source spans
gaps[]
route/plan summary
```

Prompts completos y `source_text` deben permanecer en storage de auditoría con acceso
controlado, no duplicarse en toda respuesta HTTP.

#### 5.3 UI

- `unverified` siempre visible.
- Mostrar gaps por faceta.
- Citas por título, documento, pasaje y navegación.
- Diferenciar texto explícito de inferencia.
- Mostrar si reranker/global/visual están degradados.
- Streaming con recuperación persistida tras desconexión.

#### 5.4 Rendimiento

- Métricas por etapa: normalize, embed query, candidate search, sparse, rerank,
  planning, map, reduce, verify y persist.
- Cache por query normalizada + generación.
- Presupuestos dinámicos por ruta.
- Backpressure entre worker y consultas.
- Migrar writer a PostgreSQL o rediseñar transacciones si SQLite no cumple carga.
- Desactivar SQL echo en operación normal.

#### Puerta G5

Estado: **Planned**.

- p50/p95/p99 repetidos sobre host identificado.
- RAM/VRAM pico y tamaño de índices reportados.
- Ninguna respuesta normal devuelve cientos de KiB de source text.
- UI bloquea o alerta inequívocamente respuestas `unverified`.
- Recovery de streaming probado.
- Quality gate no se degrada al optimizar latencia.

### Fase 6 — Comparación externa reproducible

Estado: **Planned**.

#### Diseño

Comparar Atenex con:

- BM25 + mismo generador;
- dense-only;
- hybrid;
- hybrid + reranker;
- long-context sobre subconjunto;
- memoria jerárquica sin graph;
- GraphRAG-like si superó G3;
- NotebookLM real, solo en una evaluación de producto separada.

Para NotebookLM:

- usar exactamente los mismos documentos permitidos, hasta el límite del plan;
- versionar la selección cuando no entren los 1.700;
- hacer preguntas idénticas;
- ocultar el sistema a revisores;
- ejecutar múltiples corridas cuando el producto lo permita;
- medir calidad y latencia, sin atribuir componentes internos.

#### Métricas mínimas

Retrieval:

- Recall@k por documento y span;
- MRR y nDCG;
- coverage de facetas;
- diversidad de documentos;
- retriever claim recall.

Respuesta:

- correctness y relevance;
- faithfulness claim-level;
- fidelidad a la postura del autor;
- comprehensiveness;
- coherencia argumentativa;
- calidad de inferencia;
- abstention accuracy.

Citas:

- precision;
- recall;
- claim coverage;
- binding al span original.

Operación:

- p50/p95/p99 y TTFT;
- RAM/VRAM;
- disco e ingesta;
- throughput con worker activo e inactivo.

Estadística:

- mínimo tres corridas cuando exista variabilidad;
- media y desviación;
- comparación pareada por pregunta;
- bootstrap 95 %;
- tamaño de efecto;
- análisis por categoría, no solo promedio.

#### Puerta G6

Estado: **Planned**.

- Dataset, configs, prompts, commits y outputs versionados.
- Ninguna tabla sin número de casos ni incertidumbre.
- NotebookLM-style claramente separado de NotebookLM real.
- Claims de superioridad limitados a métricas y condiciones reproducidas.

### Fase 7 — EOS como línea experimental separada

Estado: **Planned**. Es investigación separada y no pertenece al camino crítico de
release del RAG.

#### Pregunta científica

¿Una memoria neural de sesión actualizable en test-time aporta continuidad o
adaptación sin degradar factualidad, privacidad y estabilidad frente a una memoria
documental externa bien construida?

#### Requisitos previos

- Reimplementar desde un paper primario o referencia verificable, no desde el
  pseudocódigo GRU actual.
- Definir qué parámetros/estado se actualizan y persisten.
- Separar memoria por usuario/sesión.
- Presupuesto de olvido, reset y rollback.
- Prohibir escritura automática al corpus confiable.
- Comparar con cache, RAG de sesión y fine-tuning ligero.

#### Experimentos

- copy/associative recall como sanity check, no como claim de lenguaje;
- continuidad conversacional larga;
- adaptación a convenciones nuevas;
- resistencia a poisoning;
- olvido y recuperación;
- transferencia fuera de distribución;
- costo y estabilidad numérica.

#### Puerta G7

Estado: **Planned**.

- Implementación ejecutable, no resultados hardcodeados.
- Baseline completo y mismo presupuesto de parámetros/cómputo.
- Estado persiste o se reinicia según contrato explícito.
- Mejora significativa en tareas de sesión sin degradar grounding del corpus.
- Threat model y política de consolidación aprobados.

Cerrar G7 no demuestra AGI. Solo valida una memoria neural específica.

## 7. Backlog priorizado

### P0 — antes del siguiente rebuild

1. Dataset semilla y scorer por claims: **Implemented / Verified**; baseline Jesús G
   de 150 preguntas: **Planned**.
2. Exclusión de `_meta` y formatos no autorizados: **Implemented / Verified**.
3. Subdivisión de nodos gigantes con hard cap: **Implemented / Verified**.
4. Prefijos query/documento y fingerprint `emb-v2`: **Implemented / Verified**.
5. `READY` por barrera temporal: **Implemented / Verified**; generación común y
   activación atómica: **Planned**.
6. Reconciler SQL↔Qdrant↔candidate: **Planned**.
7. Qdrant dense primario y límite PurePy: **Implemented / Verified**; ANN local viva:
   **Planned**.
8. Eliminar pseudo-resúmenes `collection`: **Implemented / Verified**; jerarquía
   temática/abstractive: **Planned**.
9. Corregir límite de 50 documentos: **Implemented / Verified**.
10. Fallback sparse de chunks: **Implemented / Verified** en pruebas focalizadas;
    benchmark vivo: **Planned**.
11. Guard de publicación y revalidación canónica de evidencia:
    **Implemented / Verified**; publicación staged por generación: **Planned**.
12. Cleanup simétrico SQL↔Qdrant↔candidate↔graph↔visual:
    **Implemented / Verified**; reconciler de cardinalidad vivo: **Planned**.

### P1 — calidad de síntesis y confianza

13. Contexto conversacional y corrección ortográfica conservadora:
    **Implemented / Verified**.
14. Facetas acotadas y multi-query RRF: **Implemented / Verified**.
15. Reranker multilingüe vivo calibrado: **Planned**.
16. Evidencia por relevancia/cobertura/diversidad/citabilidad:
    **Implemented / Verified**.
17. Summary hierarchy con procedencia: sección/documento/colección extractiva
    **Implemented / Verified**; temas y contradictions **Planned**.
18. Planner por ruta y map-reduce real: **Implemented / Verified**; replanning
    iterativo **Planned**.
19. Claim audit: **Implemented / Verified**; tipos de inferencia estructurados:
    **Planned**.
20. Citation binding/coverage y soporte léxico: **Implemented / Verified**;
    entailment independiente calibrado: **Planned**.
21. UI guiada por verdict e incidencias: **Implemented / Verified**; gaps por faceta
    estructurados: **Planned**.
22. Idempotencia de summaries/collection memory y reparación mínima:
    **Implemented / Verified**; fault injection exhaustiva: **Planned**.

### P2 — optimización y extensiones

23. Payload público compacto: **Implemented / Verified**; storage de auditoría con
    control de acceso: **Planned**.
24. Streaming y cache por generación: **Planned**.
25. Métricas de recursos y backpressure: **Planned**.
26. Visual encoder real o renombrado de la capacidad: **Planned**.
27. Experimentos GraphRAG/DRIFT/long-context: **Planned**.
28. Línea EOS aislada: **Planned**.

## 8. Matriz problema → intervención → prueba

| Problema observado | Intervención | Estado / prueba restante |
|---|---|---|
| Nodo de 453k tokens queda entero | hard cap 800/overlap 80 | **Implemented / Verified**; rebuild vivo **Planned** |
| `eutanacia` no recupera video | corrección conservadora + multi-query hybrid | variante **Verified**; documento top 5 vivo **Planned** |
| Follow-up pierde tema | contextual retrieval query | **Implemented / Verified**; Recall vivo **Planned** |
| `Collection summary` por documento | summaries idempotentes + build explícito | **Implemented / Verified**; coverage humana **Planned** |
| Summary sin vector | readiness temporal + repair | **Implemented / Verified**; reconciler por generación **Planned** |
| Qdrant solo propositions | dense primario + schema guard | **Implemented / Verified**; rebuild/paridad vivos **Planned** |
| Query observa rebuild o índice viejo | publication guard + rehidratación SQL + fingerprint | **Implemented / Verified**; alias/generación atómica **Planned** |
| Rebuild deja vectores o aristas huérfanos | cleanup simétrico e idempotente | **Implemented / Verified**; reconciler vivo **Planned** |
| PurePy tarda decenas de segundos | Qdrant primario + límite seguro | **Implemented / Verified**; SLO vivo y ANN local **Planned** |
| Global usa dos extractos | cobertura, facetas y memoria colección | código **Verified**; coverage ≥0,85 **Planned** |
| Hierarchical es un prompt | map/reduce real | **Implemented / Verified**; benchmark humano **Planned** |
| Grounding global oculta claims | claim audit conservador | **Implemented / Verified**; entailment calibrado **Planned** |
| Citas sin coverage | audit de binding/support | **Implemented / Verified**; citation recall humano **Planned** |
| UI oculta `unverified` | policy de confianza por verdict | **Implemented / Verified**; E2E vivo **Planned** |

## 9. Política de claims de release

Solo usar:

- **Implemented** cuando el artefacto exista en el checkout.
- **Verified** cuando una prueba o ejecución nombrada lo demuestre.
- **Planned** para diseño no entregado.
- **Historical** para resultados de snapshots anteriores.

No afirmar:

- “comprende todo el corpus” sin benchmark de cobertura global;
- “aprendizaje continuo” por el solo hecho de reindexar;
- “sin ventana de contexto” porque exista retrieval;
- “reranking” si el adapter degradó a heurística;
- “memoria global” si no hay síntesis de colección con procedencia;
- “ColPali” si el modelo no codifica píxeles;
- “supera NotebookLM” con un proxy `NotebookLM-style`;
- “AGI” a partir de RAG, memoria de sesión o copy task.

Claims defendibles tras las puertas correspondientes:

- “memoria documental local, versionada y verificable”;
- “síntesis multi-documento con cobertura y citas medidas”;
- “actualización incremental de conocimiento externo”;
- “memoria neural de sesión experimental”, si G7 se cierra;
- “calidad superior al baseline X en el dataset Y bajo configuración Z”.

## 10. Decisión recomendada inmediata

1. Mantener apagado o claramente aislado el índice documental anterior: fue creado
   con chunks y embeddings incompatibles con `emb-v2`.
2. Completar `generation_id`, reconciliación y activación atómica antes del rebuild;
   la barrera temporal actual evita `READY` prematuro, pero no cierra G1/G2.
3. Ejecutar después un rebuild limpio, verificar paridad de capas y congelar sus
   artefactos como baseline vivo.
4. Completar G0 con 150 preguntas y revisión humana; ejecutar G1–G5 en orden y no
   convertir tests focalizados en claims de calidad global.
5. Mantener reranker, graph cross-document, NotebookLM y EOS como **Planned** hasta
   que sus respectivas ablaciones/puertas produzcan evidencia reproducible.
