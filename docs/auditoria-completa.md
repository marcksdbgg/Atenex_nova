# Auditoría Técnica Completa — Atenex Nova

> Auditoría de arquitectura, integración VecQuant/TurboQuant, flujos de ingesta y
> pipeline RAG/PRAG, realizada por revisión estática exhaustiva del código fuente,
> contrastada contra la tesis (`G:\UCSP\Tesis\tesis_2025\Tesis.pdf`), el `README.md`,
> `AGENTS.md`, `docs/turboquant-integration.md` y la literatura primaria de TurboQuant
> (Zandieh, Daliri, Hadian, Mirrokni — *TurboQuant: Online Vector Quantization with
> Near-optimal Distortion Rate*, arXiv:2504.19874, ICLR/AISTATS 2026).
>
> **Fecha:** 2026-06-16. **Tipo:** auditoría real, con contraste claim-vs-implementación
> y citas a archivo:línea. Reemplaza a `docs/final-gap-inventory.md` (eliminado).
>
> **⚠️ ESTADO ACTUAL (2026-06-16, post-corrección):** las secciones §1–§12 describen el
> diagnóstico **original**. El plan §13 fue **ejecutado** (SA-1 a SA-7) y la mayoría de
> hallazgos críticos/altos están **cerrados**. El estado vigente, validado contra el
> código actual y con tests reales, está en **§14 (leer primero)**. Donde §1–§12
> contradigan a §14, **manda §14**.

---

## 0. Alcance, método y honestidad sobre lo verificado

Esta auditoría se realizó **íntegramente por análisis estático** (lectura de código,
documentos y papers). Es necesario declarar con precisión qué se pudo y qué **no** se
pudo validar, para no incurrir en el mismo defecto que el inventario anterior
(afirmaciones de verde 100% no contrastables):

| Verificación | Estado | Motivo |
|---|---|---|
| Lectura/comprensión de todo el backend, VecQuant, workers, orquestadores | ✅ Hecho | Herramientas de archivo operativas |
| Lectura de la tesis (68 pp.) y research de TurboQuant | ✅ Hecho | PDF leído; literatura primaria consultada |
| Limpieza de la DB relacional de desarrollo (SQLite) | ✅ Hecho | `clean_all.py --yes` (2026-06-16 sesión live) |
| Limpieza de Qdrant (servicio Docker) y `storage/` | ✅ Hecho | `clean_all.py --yes` con Qdrant en 6333 |
| Limpieza de PostgreSQL | ⚠️ N/A en dev | Perfil dev usa SQLite; Postgres solo con `--profile prod` |
| Ejecución de la suite de tests (`pytest`) sin runtimes | ✅ Hecho | 90 passed, 3 skipped (2026-06-16) |
| Ejecución de la suite con **Qdrant + Ollama vivos** | ✅ Hecho | **93 passed, 0 skipped** (2026-06-16, §15) |
| `turbovec` instalado en `.venv312` | ✅ Hecho | `import turbovec` OK |
| `mypy` / `ruff` / frontend lint+build | ✅ Hecho | mypy 155 files limpio; ruff 0; npm OK |
| `/health/dependencies` con servicios levantados | ✅ Hecho | LLM+Qdrant+embeddings OK (Ollama local) |
| Métricas reales recall/answer/grounding (golden sets) | ❌ Pendiente | SA-8 parcial; requiere evaluación manual |

> **Limpieza (2026-06-16):** ejecutado `backend/scripts/clean_all.py --yes` con Qdrant
> Docker en 6333 — SQL drop+recreate, 24 colecciones Qdrant borradas, `storage/` vaciado.

**Conclusión global del veredicto (diagnóstico original §1–§12):** la arquitectura
hexagonal está bien planteada, pero **al momento del diagnóstico** la integración
VecQuant/TurboQuant tenía triple persistencia, adapter muerto y `turbovec` no declarado.

**Conclusión vigente (post-corrección §14–§15):** la Opción A del plan §13 está
**implementada y verificada** en código y tests. Qdrant en LITE/STANDARD es sparse-only;
dense canónico = códigos SQL + estimador IP (`dense_turbo_ip`). Embeddings 100% locales
vía Ollama (`embeddinggemma`), sin Hugging Face. Pendiente: golden sets de calidad
(SA-8) y H-11 (cache BM25).

---

## 1. Arquitectura: estado real

El patrón **monolito modular + hexagonal** existe y se respeta en lo esencial:
`presentation → application → domain → infrastructure → workers → evaluation → shared`.

- **Puertos de dominio** correctos y desacoplados: `VectorQuantizerPort`
  (`domain/ports/quantizer.py`), `CandidateIndexPort` (`domain/ports/candidate_index.py`),
  `DenseIndexPort` (`domain/ports/dense_index.py`), `HybridIndex`
  (`domain/repositories/vector_index.py`).
- **Wiring** por DI en `dependencies.py` y un `JobRunner` de polling robusto
  (`workers/runner.py`) con recuperación de jobs `running` huérfanos y reintentos.
- **Cadena de jobs de ingesta** correctamente encadenada:
  `PARSE → SEGMENT → EMBED → EXTRACT_PROPOSITIONS → (EMBED_PROPOSITIONS, GENERATE_SUMMARIES → EMBED_SUMMARIES, BUILD_GRAPH) → INDEX_VISUAL_PAGES`.

**Hallazgo de contraste documental (Severidad: media).** El `pyproject.toml` aplica
`[[tool.mypy.overrides]] ... ignore_errors = true` a **casi todos los módulos con lógica
crítica** (repositorios SQL, workers, `retrieval_orchestrator`, `answer_service`,
routers de `collections`/`health`, etc. — `pyproject.toml:83-100`). Por tanto, la
afirmación "mypy 0 errors / 100% verde" es engañosa: los módulos más complejos están
**excluidos** del chequeo estricto. No es un fallo funcional, pero invalida el "verde"
como señal de calidad de tipos en el núcleo.

---

## 2. VecQuant / TurboQuant — auditoría profunda

Este es el foco central del pedido ("valida que VecQuant esté completamente
implementado"). El resultado es matizado: **el algoritmo está correctamente
implementado a nivel matemático, pero está mal integrado y en gran parte no se usa**.

### 2.1. Lo que SÍ está bien

- `TurboQuantAdapter` (`infrastructure/vector_quantization/turboquant_adapter.py`)
  implementa fielmente **TurboQuantprod**: rotación ortogonal determinista (QR),
  Lloyd-Max de `b-1` bits sobre coordenadas escaladas a N(0,1), residual + QJL de 1 bit
  (signos de una proyección gaussiana), guardando `residual_norm` y `vector_norm`.
- **El escalado de reconstrucción es matemáticamente insesgado.** Verifiqué la
  de-cuantización: con `P = G/√d` y `m = d` proyecciones,
  `E[Pᵀ·s] = √d·√(2/π)·r̂`, y el factor `scale = residual_norm·√(π/2d)` cancela
  exactamente: `√(π/2d)·√(2d/π) = 1`, de modo que `hat_r_rot ≈ r_rot` en esperanza
  (`turboquant_adapter.py:170-186`). Coincide con el estimador QJL canónico
  `‖r‖·√(π/2m)·⟨Sq, sign(Sr)⟩`.
- El test unitario `tests/unit/test_turboquant.py` cubre cos-sim > 0.75 y error de
  producto interno < 0.20, que la implementación cumple holgadamente a 4 bits.
- El perfil/registry y la persistencia SQL (`quantization_profiles`,
  `quantized_vectors`) están bien modelados (`db/models/tables.py:222-249`).

### 2.2. Hallazgos críticos

**H-1 (CRÍTICA): `turbovec` es una dependencia NO declarada.**
`turboquant_candidate_index.py:10` hace `from turbovec import IdMapIndex` **a nivel de
módulo**, y `retrieval_orchestrator.py:37` importa `TurboQuantCandidateIndex` también a
nivel de módulo. Pero `turbovec` **no está en `pyproject.toml`** (ni en `ml`, `dev` ni
`all`); solo se instala mediante el script lateral `install_gpu_deps.ps1:18`
(`pip install turbovec==0.7.0`). Consecuencias:
- Un `pip install -e ".[all]"` limpio **no** instala `turbovec`. En ese entorno, el
  import de `retrieval_orchestrator` falla → `QueryService` no carga → **todos los
  endpoints `/queries/*` y los tests que los importan se rompen** con `ImportError`.
- La afirmación de "63 tests passing" solo puede ser cierta en el `.venv312` donde
  alguien corrió el script manual. Es un agujero de reproducibilidad serio.
- *Acción:* declarar `turbovec` en `pyproject.toml` (extra `all`/`ml`) y/o hacer el
  import perezoso y tolerante a ausencia (como ya se hace en `health.py:118`).

**H-2 (CRÍTICA): triple persistencia de vectores — no hay "reemplazo de Qdrant".**
`docs/turboquant-integration.md` afirma que TurboQuant reemplaza la persistencia de
embeddings y mantiene "la RAM limpia". La realidad del pipeline de ingesta:
1. Qdrant recibe el **vector float32 completo** (`mem_builder_job.py:256-278`,
   `memory_enrichment_job.py:195-217` y `:369-389`).
2. `turbovec` escribe un índice cuantizado `.tvim` (`ingestion_orchestrator.py:76`,
   `turboquant_candidate_index.py:76-77`).
3. SQL `quantized_vectors` recibe `idx_blob`+`qjl_blob`+normas
   (`ingestion_orchestrator.py:63-73`).

Son **tres copias** del mismo embedding. No hay ahorro de RAM/almacenamiento; hay
**sobrecoste neto** de cómputo (cuantizar en cada ingesta) y de disco (blobs SQL). La
narrativa de "decoplar y comprimir para hardware de consumo" no se materializa.

**H-3 (CRÍTICA): el `TurboQuantAdapter` propio está, en la práctica, muerto.**
La de-cuantización (`dequantize`) **solo se invoca en el test unitario** y en el
passthrough `QuantizationPolicyService.dequantize` (que nadie llama). El `grep`
confirma que en el camino de retrieval/ingesta **no se desempaqueta ningún blob**:
- La búsqueda real usa `turbovec.IdMapIndex.search` (cuantización **interna** de la
  librería, no la del adapter) — `turboquant_candidate_index.py:100-108`.
- Los blobs SQL solo se leen para mapear `uint64_id → (node_id, memory_layer)`
  (`turboquant_candidate_index.py:117-123`); `idx_blob`/`qjl_blob` **nunca** se leen.
- El reranking opera sobre **texto** (`título + snippet`), no sobre vectores
  de-cuantizados (`retrieval_orchestrator.py:855-858`), contradiciendo el "Stage 3"
  de `turboquant-integration.md` ("se decuantizan para aproximar el vector original").

Es decir: se calcula y almacena un esquema de cuantización sofisticado cuyos bits
**no participan en ningún score**. El trabajo útil de ANN lo hace `turbovec`; el
`TurboQuantAdapter` es redundante en producción.

**H-4 (ALTA): divergencia con el algoritmo de referencia.**
La implementación de referencia (paper + `turboquant-py` + análisis QJL) **estima el
producto interno directamente** con la proyección de la *query*
(`⟨q,k̂_mse⟩ + ‖r‖·√(π/2m)·⟨Sq, sign(Sr)⟩`) y subraya que el QJL de 1 bit "no tiene
capacidad de reconstrucción". Atenex en cambio **reconstruye** el vector residual
(`Pᵀ·s`) — insesgado en esperanza, pero de **alta varianza por vector** y subóptimo —
y, peor aún, ni siquiera lo usa para puntuar. Si en el futuro se quisiera usar el
adapter para reranking exacto, debería implementarse el estimador de producto interno,
no la reconstrucción.

### 2.3. Hallazgos medios sobre VecQuant

- **H-5 (MEDIA): recarga de índice por consulta.** `search` hace
  `IdMapIndex.load(...)` por **cada capa y cada query** desde disco
  (`turboquant_candidate_index.py:100`), sin caché en memoria. Penaliza la latencia y
  el IO; contradice el objetivo de "< 5 ms" del propio doc de integración.
- **H-6 (MEDIA): reescritura completa del índice en cada `add_vectors`.** Por cada lote
  se hace `remove` de cada id (en bucle, con excepción suprimida) seguido de
  `add_with_ids` y `index.write(...)` del archivo entero
  (`turboquant_candidate_index.py:71-77`). Escala mal con colecciones grandes.
- **H-7 (BAJA): codebook fijo N(0,1).** El registry usa centroides Lloyd-Max para
  N(0,1) (`profile_registry.py`). El paper observa que las coordenadas rotadas siguen
  una distribución **Beta** (no exactamente normal); el escalado `·√d` es una
  aproximación razonable, y el propio doc lista la "auto-calibración del codebook" como
  pendiente. Aceptable, pero documentar la aproximación.
- **H-8 (BAJA): `_use_turbovec()` excluye el perfil MAX.** Solo LITE/STANDARD usan el
  índice de candidatos (`retrieval_orchestrator.py:104-106`); MAX va directo a Qdrant.
  Coherente, pero significa que el camino "VecQuant" no se ejercita en el perfil alto.

---

## 3. Flujo de ingesta — calidad real

Cadena de jobs (workers) bien orquestada, pero con **señales heurísticas** donde los
documentos del repo sugieren capacidades más avanzadas.

- **Segmentación / chunking** (`mem_builder_job.py:29-133`): por `TokenBudgetPolicy`,
  anclada a nodos reales (`node_ids`), con `heading_path`, `page_numbers`, `bboxes`.
  Sólido y trazable. ✅
- **Embeddings** (`embedding_adapter.py`): EmbeddingGemma vía SentenceTransformers con
  truncado Matryoshka (`truncate_dim`), GPU+fp16 cuando hay CUDA. ✅
  - **H-9 (MEDIA): fallback hash silencioso.** Si el modelo no carga y *no* es strict,
    se generan embeddings deterministas por hash de tokens (`_fallback_embed`,
    `embedding_adapter.py:95-107`). En perfil **DEV (default)**, `strict_mode_enabled`
    es `False` (`settings.py:118-123`), de modo que el sistema "funciona" produciendo
    vectores **no semánticos** y cuantizándolos/indexándolos igual. La calidad de
    recuperación se degrada de forma invisible. Para evaluar calidad real **hay que
    forzar `ATENEX_PROFILE=prod` o `ATENEX_REQUIRE_EMBEDDINGS=true`**.
- **Proposiciones** (`memory_enrichment_job.py:33-129`): **no son extracción atómica
  por LLM**; son *split de oraciones por regex* (`split_sentences`, oraciones > 20
  caracteres) + clasificación por *keywords* (`classify_proposition`). El README las
  describe como "atomic assertions extracted from spans" → **contraste**. (La tesis sí
  las plantea como heurísticas/complementarias, así que el desajuste es README↔tesis.)
- **Resúmenes** (`memory_enrichment_job.py:238-298`): **extractivos por frecuencia de
  términos** (`summarize_texts`), no abstractivos por LLM. El README dice
  "hierarchical summaries" sin aclarar que son extractivos → **contraste**.
- **Grafo de relaciones** (`memory_enrichment_job.py:410-542`): `APPEARS_IN` por
  proposición→documento, `ELABORATES` por pares contiguos, marcadores léxicos
  ("however/sin embargo" → `CONTRADICTS`, "means/se define" → `DEFINES`,
  "because/provoca" → `SUPPORTS`) y `MENTIONS` por solapamiento de keywords con
  filtrado de términos frecuentes. Es un grafo **heurístico**, útil pero pobre frente a
  GraphRAG/ToPG que la tesis cita como referencia (§3.6). Severidad: media.

---

## 4. Pipeline de consulta (RAG) y multi-hop (PRAG)

`RetrievalOrchestrator` (`application/orchestrators/retrieval_orchestrator.py`):
routing por features, scoring por capa (chunks/proposiciones/resúmenes/visual), fusión
RRF dense+sparse, reranking y `EvidencePack`. Diseño correcto y route-aware
(`_route_source_weight`, `_result_limit`).

- **Dense:** turbovec (LITE/STANDARD) o Qdrant (MAX/fallback). **Sparse:** Qdrant
  sparse (SPLADE o lexical-hash) o BM25 local. Fusión RRF con pesos 0.65/0.35 + bonus
  léxico. ✅ funcional.
- **Multi-hop (PRAG):** expansión de grafo desde top-5 proposiciones con relaciones
  permitidas según intención (`retrieval_orchestrator.py:224-317`). Real pero limitada
  por la calidad heurística del grafo (§3).
- **H-10 (BAJA — verificado, mayormente resuelto): reranker instanciado por llamada,
  pero es singleton.** En `_rerank_hits` se hace `RerankerAdapter(required=...)` dentro
  del método (`retrieval_orchestrator.py:854-858`), llamado varias veces por query. Sin
  embargo, `RerankerAdapter` **es singleton de clase** (`_instance`/`_model` a nivel de
  clase, `reranker_adapter.py:14-44`): el cross-encoder se carga **una sola vez** y los
  `__init__` posteriores son no-ops. El coste por llamada se reduce a `get_settings()` y
  comprobaciones triviales. *Acción menor:* inyectar el reranker como dependencia en vez
  de re-instanciarlo, y reutilizar `predict` en una sola pasada por query.
- **H-11 (BAJA): re-fit de BM25 en cada scoring.** `BM25SparseEncoder.score` hace
  `fit(texts)` en cada llamada (`bm25_encoder.py:137-157`). Correcto pero O(corpus) por
  query en el camino local.

---

## 5. Ruta visual — "ColPali" es un nombre engañoso

**H-12 (ALTA, contraste):** No existe modelo ColPali ni late-interaction multi-vector.
`ColPaliAdapter` (`infrastructure/visual/colpali_adapter.py`) embebe el **texto** de la
página con EmbeddingGemma y lo etiqueta `retrieval_backend: "page_text_embedding"`
(`colpali_adapter.py:97,197`). El render de PNG (pypdfium2/PIL) es **solo para el
viewer**, no alimenta ningún embedding visual. El README ("ColPali-style visual page
retrieval", "multi-vector") y la tesis (§2.11/§3.7, que citan ColPali real) quedan
desalineados con la implementación, que es *text-of-page retrieval*. La política
strict-visual y el binding de cita a `page_asset_path` sí están implementados
(`retrieval_orchestrator.py:417-423`, `answer_orchestrator.py:501-510`).

---

## 6. Answering, verificación y citas

`AnswerOrchestrator` (`application/orchestrators/answer_orchestrator.py`) está bien
construido: plan por modo, prompts versionados, **verificación en dos pasos**
(determinística + segunda pasada LLM), **una regeneración** controlada, binding de
citas y `evidence_trace` rico persistido.

- **H-13 (MEDIA): grounding heurístico con piso inflado.**
  `grounding_score = min(1, 0.35 + coverage·0.45 + citation_score·0.2)`
  (`answer_orchestrator.py:538`), donde `coverage` es solapamiento de tokens
  respuesta↔evidencia. El piso 0.35 garantiza que toda respuesta no vacía parte de
  0.35; con `min_grounding_score = 0.35` (`settings.py:116`) el umbral strict es casi
  trivial de pasar. La "verificación" es real pero **débil como garantía**.
- **H-14 (BAJA): binding solo de los primeros 5 items** y solo si el marcador `[n]`
  aparece en el draft (`answer_orchestrator.py:413-438`). Razonable, pero limita la
  cobertura de citas en respuestas largas.
- ✅ Strict mode en answering es serio: exige texto no vacío, ≥1 cita resuelta a span
  real / página con asset, y `grounding_score ≥ min` (`answer_orchestrator.py:482-518`).

---

## 7. Evaluación

Existe infraestructura (`evaluation/`, `EvaluationRunModel`, scorers de retrieval y
answer), pero **no hay golden sets reproducibles por modo** ni una puerta de aceptación
ejecutada. La tesis (§5–§6) define un protocolo serio (Recall@k, MRR, nDCG, RAGAS,
ALCE, robustez, latencia p50/p95, memoria, ablaciones) que **el repo aún no ejercita**.
Severidad: alta para cualquier afirmación de calidad.

---

## 8. Contraste documental: tesis vs. repo

**H-15 (ALTA, fuente de verdad):** La **tesis no contempla cuantización vectorial de
embeddings** (TurboQuant/VecQuant). Su §2.6 ("Modelos locales, cuantización y perfiles
de despliegue") trata la cuantización **de modelos** (GGUF/SLM) y los perfiles de
hardware; sus contribuciones (§1.9) listan parsing estructural, recuperación híbrida
dense+sparse, memoria multicapa, routing, grounding y citas — **no** VQ. Por tanto,
TurboQuant es una capa de ingeniería añadida en el repo/README/AGENTS que **no forma
parte del contrato académico evaluado**. Hay que decidir y documentar: (a) integrarla
de verdad y evaluarla, o (b) marcarla explícitamente como optimización experimental
fuera del alcance de la tesis. Hoy el README la presenta como central, lo que crea
expectativa no respaldada.

**H-16 (MEDIA): el inventario anterior se contradecía a sí mismo.** `final-gap-inventory.md`
(eliminado) afirmaba en sus líneas 43-44 "ruff 0 issues / mypy 0 errors / 100% verde"
y en sus líneas 470-473 "`ruff check .` reporta 6 issues y `mypy` reporta 5 errores".
Contradicción interna directa — razón suficiente para reemplazarlo por este documento.

---

## 9. Limpieza de datos: estado y procedimiento

**Ejecutado en esta sesión:**
- 🗑️ `backend/atenex_nova.db` (SQLite de desarrollo, 265 MB) **eliminado**. El esquema
  se recrea automáticamente al arrancar (`db/session.py:create_all_tables`).

**Pendiente de ejecutar por el usuario** (el shell del agente no respondía; los
terminales del usuario sí funcionan). Ejecutar desde `backend/`:

```powershell
# Limpieza total: SQL (drop+recreate) + Qdrant (todas las colecciones) + storage
.venv312\Scripts\python.exe scripts\clean_all.py --yes
```

El script `backend/scripts/clean_all.py` (creado en esta sesión):
- Hace `drop_all` + `create_all` sobre la DB configurada (sirve para SQLite **y**
  PostgreSQL según `ATENEX_DATABASE_URL`).
- Lista y borra **todas** las colecciones de Qdrant en `ATENEX_QDRANT_URL`.
- Vacía `storage/turbovec` (`*.tvim`), `storage/visual_pages` y `storage/uploads`.
- Flags: `--keep-uploads`, `--sql-only`, `--qdrant-only`, `--storage-only`.

Alternativa manual mínima para Qdrant (si se prefiere curl):
```powershell
# Lista
curl http://localhost:6333/collections
# Borra una colección
curl -X DELETE http://localhost:6333/collections/<nombre>
```

---

## 10. Tabla resumen de hallazgos (por severidad)

| ID | Severidad | Hallazgo | Evidencia |
|---|---|---|---|
| H-1 | CRÍTICA | `turbovec` no declarado en `pyproject`; import a nivel de módulo rompe `/queries/*` sin él | `pyproject.toml`, `install_gpu_deps.ps1:18`, `turboquant_candidate_index.py:10`, `retrieval_orchestrator.py:37` |
| H-2 | CRÍTICA | Triple persistencia (Qdrant float32 + .tvim + blobs SQL); no hay reemplazo/ahorro | `mem_builder_job.py:256-278`, `ingestion_orchestrator.py:63-77` |
| H-3 | CRÍTICA | `TurboQuantAdapter.dequantize` muerto en producción; blobs SQL nunca puntúan | `turboquant_candidate_index.py:117-123`, grep `dequantize` |
| H-4 | ALTA | Diverge del estimador TurboQuant de referencia (reconstrucción vs. IP directo) | `turboquant_adapter.py:170-186` vs. arXiv:2504.19874 |
| H-5 | MEDIA | Índice turbovec se recarga de disco por capa y por query | `turboquant_candidate_index.py:100` |
| H-6 | MEDIA | Reescritura completa del `.tvim` en cada `add_vectors` | `turboquant_candidate_index.py:71-77` |
| H-9 | MEDIA | Fallback hash de embeddings silencioso en DEV (no semántico) | `embedding_adapter.py:95-107`, `settings.py:118-123` |
| H-10 | BAJA | Reranker re-instanciado por llamada, pero **es singleton** (carga 1 vez); solo conviene inyectarlo | `retrieval_orchestrator.py:854-858`, `reranker_adapter.py:14-44` |
| H-12 | ALTA | "ColPali" no es ColPali: embebe texto de página, no visión multi-vector | `colpali_adapter.py:97,197` |
| H-13 | MEDIA | Grounding heurístico con piso 0.35 ≈ umbral strict | `answer_orchestrator.py:538`, `settings.py:116` |
| H-15 | ALTA | La tesis no contempla VQ; TurboQuant es capa de repo sin respaldo académico | Tesis §1.9, §2.6 |
| H-16 | MEDIA | El inventario anterior se contradecía (ruff/mypy 0 vs 6/5) | `final-gap-inventory.md` (eliminado) |
| — | MEDIA | `mypy ignore_errors=true` en módulos núcleo invalida el "verde" | `pyproject.toml:83-100` |

(Severidad de H-10 corregida a la baja tras verificar que `RerankerAdapter` es singleton.)

---

## 11. Acciones recomendadas (prioritizadas)

1. **Declarar `turbovec` en `pyproject.toml`** y volver perezosos/tolerantes los
   imports de `TurboQuantCandidateIndex` (H-1). Bloqueante para reproducibilidad.
2. **Decidir el rol de VecQuant** (H-2/H-3/H-15): o bien (a) **usar** el índice
   cuantizado como reemplazo real de Qdrant en perfiles bajos (dejar de escribir
   float32 a Qdrant en LITE/STANDARD), o (b) **eliminar** el `TurboQuantAdapter`/blobs
   SQL redundantes y quedarse solo con `turbovec`. Hoy se paga el coste de los tres.
3. **Cachear el índice turbovec en memoria** por colección/capa (H-5/H-6).
4. **Confirmar y, si procede, cachear el reranker** (H-10).
5. **Renombrar/clarificar la ruta "visual"** o integrar un ColPali real (H-12).
6. **Alinear README/AGENTS con la tesis**: marcar proposiciones/resúmenes/grafo como
   heurísticos y TurboQuant como optimización experimental (H-15).
7. **Endurecer grounding** (quitar el piso 0.35 artificial o separarlo del umbral
   strict) y **construir golden sets por modo** (§7, H-13).
8. **Cerrar la limpieza** ejecutando `scripts/clean_all.py` para Qdrant + storage (§9).

---

## 12. Validaciones a ejecutar (cuando el runtime esté disponible)

```powershell
# 1) Limpieza total
cd backend; .venv312\Scripts\python.exe scripts\clean_all.py --yes

# 2) ¿turbovec instalado?
.venv312\Scripts\python.exe -c "import turbovec, numpy; print('turbovec OK', turbovec.__version__ if hasattr(turbovec,'__version__') else 'n/a')"

# 3) Test específico de cuantización
.venv312\Scripts\python.exe -m pytest tests/unit/test_turboquant.py -v

# 4) Suite completa
.venv312\Scripts\python.exe -m pytest tests -q

# 5) Salud de dependencias en caliente (Ollama/Qdrant/embeddings/docling/visual/turbovec)
curl http://127.0.0.1:8000/health/dependencies

# 6) Calidad real: forzar perfil prod para NO usar embeddings hash
$env:ATENEX_PROFILE = "prod"   # activa strict + require_embeddings + require_qdrant
```

> Nota: hasta no ejecutar (4) y (5) con runtimes activos, cualquier afirmación de
> "100% verde" o de calidad de recuperación es **no verificada**.

---

# 13. Plan de corrección completo (orientado a subagentes)

> Objetivo del plan: eliminar de raíz **H-2 (persistencia triple)** y **H-3 (adapter
> TurboQuant muerto)**, y cerrar el resto de hallazgos. El plan está descompuesto en
> **work packages ejecutables por subagentes** (uno por bloque), con orden de ejecución,
> archivos exactos, criterios de aceptación, tests y un *prompt de despliegue* listo
> para pasar al `Task tool`. Cada subagente debe trabajar en su paquete, correr sus
> tests y dejar el repo verde antes de ceder el turno al siguiente.

## 13.0. Decisión de arquitectura objetivo

El problema central es que hoy hay **tres representaciones** del mismo embedding
(float32 en Qdrant + `.tvim` de turbovec + blobs Lloyd-Max+QJL en SQL) y la
representación "propia" (blobs) **no puntúa nada**. El objetivo es **una sola
representación canónica comprimida que SÍ puntúe**.

**Opción A — RECOMENDADA: TurboQuantprod propio como motor canónico; `turbovec`
opcional como acelerador; Qdrant solo sparse en LITE/STANDARD.**

- La representación canónica para dense en LITE/STANDARD son los **códigos TurboQuantprod
  en SQL `quantized_vectors`** (idx + signos QJL + normas).
- El scoring de candidatos usa el **estimador insesgado de producto interno** de
  TurboQuantprod sobre esos códigos (los bits *sí* puntúan). Esto elimina H-3.
- **No se escribe float32 dense a Qdrant** en LITE/STANDARD. Qdrant queda como índice
  **sparse-only** (y dense solo en perfil MAX, donde no se usa cuantización). Esto
  elimina H-2 (deja una sola copia dense comprimida + sparse).
- `turbovec` se vuelve un **backend de aceleración opcional** detrás de
  `CandidateIndexPort`, construido *a partir* de los mismos códigos; si no está
  instalado, se usa el motor puro-python. Esto mitiga H-1 (deja de ser dependencia dura).

**Opción B — alternativa simple: `turbovec` como índice primario, borrar el adapter
propio.** Se mantiene `turbovec` como único índice dense local, se **elimina** el
`TurboQuantAdapter`, la tabla `quantized_vectors` y `QuantizationPolicyService` (código
muerto), y se reemplaza el id-map por una tabla mínima `vector_id_map`. También cierra
H-2/H-3 (por borrado), pero **mantiene `turbovec` como dependencia dura** (hay que
declararla sí o sí) y descarta el trabajo de cuantización propio.

> **El plan siguiente implementa la Opción A.** Para Opción B, ejecutar solo SA-1, SA-5
> (variante "borrar blobs"), SA-6, SA-7, SA-8, SA-9 y omitir SA-2/SA-3. La elección se
> controla con un flag de settings `ATENEX_CANDIDATE_BACKEND ∈ {purepy, turbovec, auto}`.

## 13.1. Invariante post-corrección (criterio de "hecho")

1. En LITE/STANDARD, una ingesta produce **exactamente una** copia dense (códigos
   TurboQuantprod en SQL) + sparse (Qdrant o local). **Cero** float32 dense en Qdrant.
2. La búsqueda de candidatos dense puntúa con el **estimador de producto interno**
   (no con reconstrucción ni con `dequantize`); el ranking aproximado debe coincidir
   con el exacto (Recall@10 del estimador ≥ 0.90 vs. IP exacto sobre un set sintético).
3. `pip install -e ".[all]"` (sin correr `install_gpu_deps.ps1`) **no rompe imports**;
   `turbovec` ausente ⇒ se usa puro-python sin error.
4. `dequantize` queda solo como utilidad de diagnóstico (o se elimina); ningún camino
   de producción depende de reconstruir el vector.
5. `ruff`, `mypy` (sin ampliar los `ignore_errors`), `pytest`, `npm run build/lint`
   verdes con runtimes activos.

## 13.2. Orden de ejecución (DAG de subagentes)

```
SA-1 (deps + imports perezosos)         ─┐
SA-2 (estimador IP en adapter)          ─┼─► SA-3 (PurePyCandidateIndex)
                                          │        │
                                          │        ▼
                                          └─► SA-4 (factory/selección backend) ─► SA-5 (ingesta: 1 copia)
                                                                                      │
                                                                                      ▼
                                                                                  SA-6 (retrieval + cleanup/rebuild)
SA-7 (quality fixes)  ── independiente, puede ir en paralelo tras SA-1 ──┐
SA-9 (docs)           ── tras SA-5/SA-6 ─────────────────────────────────┼─► SA-8 (tests/validación final, cierra todo)
```

Regla: **SA-8 corre al final** y es la puerta de aceptación. SA-7 y SA-9 pueden
paralelizarse. SA-2→SA-3→SA-4→SA-5→SA-6 es la cadena crítica.

---

## 13.3. SA-1 — Saneamiento de dependencias e imports perezosos

- **Objetivo:** que el repo no dependa de `turbovec` en tiempo de import; declararlo
  como extra opcional. Cierra H-1.
- **Archivos:** `backend/pyproject.toml`; `backend/atenex_nova/infrastructure/indexes/turboquant_candidate_index.py`; `backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py`; `backend/atenex_nova/application/orchestrators/ingestion_orchestrator.py`; `backend/atenex_nova/infrastructure/visual/colpali_adapter.py`.
- **Cambios concretos:**
  1. En `pyproject.toml` añadir extra `accel = ["turbovec==0.7.0"]` y referenciarlo en
     `all`. Documentar que es opcional.
  2. Mover `from turbovec import IdMapIndex` a import **perezoso** dentro de los métodos
     del backend turbovec (no a nivel de módulo), con `try/except ImportError`.
  3. En `retrieval_orchestrator.py` e `ingestion_orchestrator.py`, importar el índice de
     candidatos vía **factory** (ver SA-4), no la clase concreta turbovec.
- **Aceptación:** en un venv sin `turbovec`, `python -c "import atenex_nova.application.orchestrators.retrieval_orchestrator"` no lanza `ImportError`; `pytest tests/unit -q` recolecta sin errores de import.
- **Tests:** añadir `tests/unit/test_imports_without_turbovec.py` que simule ausencia (monkeypatch de `sys.modules["turbovec"]=None`) y verifique import OK.
- **Riesgos:** imports circulares al introducir factory; mitigar con import perezoso dentro de funciones.
- **Prompt de despliegue:** *"Eres SA-1. En Atenex Nova, vuelve opcional la dependencia `turbovec`: declárala como extra `accel` en backend/pyproject.toml, convierte todos los `from turbovec import ...` en imports perezosos guardados con try/except dentro de métodos, y asegura que importar retrieval_orchestrator/ingestion_orchestrator no falle sin turbovec. Añade tests/unit/test_imports_without_turbovec.py. Deja ruff/mypy verdes."*

## 13.4. SA-2 — Estimador de producto interno en `TurboQuantAdapter` (núcleo de H-3)

- **Objetivo:** que los bits Lloyd-Max+QJL **puntúen**. Implementar el estimador
  insesgado de TurboQuantprod, vectorizado sobre un lote de códigos.
- **Archivos:** `backend/atenex_nova/infrastructure/vector_quantization/turboquant_adapter.py`; `backend/atenex_nova/domain/ports/quantizer.py`; `backend/tests/unit/test_turboquant.py`.
- **Cambios concretos:**
  1. Añadir al puerto `VectorQuantizerPort` el método
     `estimate_inner_products(query_vector, codes, profile) -> list[float]`.
  2. Implementarlo según el paper (arXiv:2504.19874):
     `IP(q,k) ≈ ‖q‖·v_norm_k · ( ⟨q_rot, k̂_v_rot⟩ + r_norm·√(π/(2·d))·⟨P·q_rot, signs⟩ )`,
     donde `q_rot = R·(q/‖q‖)`, `k̂_v_rot = centroids[idx]/√d`, `signs ∈ {±1}` desde
     `qjl_blob`, y `P` es la matriz QJL ya cacheada. Para ranking, `‖q‖` es constante y
     puede omitirse, pero debe incluirse `v_norm_k`.
     Precomputar `q_rot` y `P·q_rot` **una vez** por query y reutilizarlos para todos los
     códigos (vectorización numpy: apilar `idx` y `signs` en matrices).
  3. Marcar `dequantize` como utilidad de diagnóstico (docstring) — no eliminar todavía.
- **Aceptación:** sobre 1.000 vectores aleatorios `d=384`, el ranking top-10 por
  `estimate_inner_products` coincide con el IP exacto en **Recall@10 ≥ 0.90** y la
  correlación de Spearman ≥ 0.95; error medio |IP_est − IP_exacto| < 0.05 a 4 bits.
- **Tests:** ampliar `test_turboquant.py` con `test_inner_product_ranking_recall` y
  `test_estimator_unbiased` (media del error ≈ 0).
- **Riesgos:** errores de escalado/normalización; cubrir con el test de insesgadez.
- **Prompt de despliegue:** *"Eres SA-2. Implementa en TurboQuantAdapter el método estimate_inner_products(query, codes, profile) usando el estimador insesgado de TurboQuantprod (Lloyd-Max + corrección QJL del residual), vectorizado y precomputando P·q_rot una sola vez por query. Añádelo al puerto VectorQuantizerPort. Añade tests de Recall@10≥0.90 vs IP exacto y de insesgadez. NO uses reconstrucción de vector para puntuar."*

## 13.5. SA-3 — `PurePyTurboQuantCandidateIndex` (CandidateIndexPort)

- **Objetivo:** un índice de candidatos 100% local sin `turbovec`, que lee los códigos
  de `quantized_vectors` y puntúa con el estimador de SA-2.
- **Archivos (nuevo):** `backend/atenex_nova/infrastructure/indexes/purepy_candidate_index.py`; usa `QuantizedCodeStore` (`get_vectors_by_layer`).
- **Cambios concretos:**
  1. `add_vectors`: delega en `QuantizationPolicyService.quantize` + `QuantizedCodeStore.save_vector` (ya existe el guardado; este índice **no** mantiene archivo aparte).
  2. `search(collection, layers, query, top_n)`: carga códigos por capa
     (`get_vectors_by_layer`), agrupa por `profile_id`, llama
     `estimate_inner_products` en lote y devuelve top_n `{node_id, score, memory_layer}`.
  3. Caché LRU en memoria por `(collection, layer)` de los arrays decodificados (idx,
     signs, normas) para evitar releer SQL en cada query; invalidación en `add/remove`.
  4. `remove_vectors`/`delete_collection_indexes`: delega en `QuantizedCodeStore`.
- **Aceptación:** dado un set indexado, `search` devuelve los mismos top-k que un cálculo
  IP exacto con Recall@10 ≥ 0.90; latencia < 50 ms para 10k vectores `d=384` en CPU.
- **Tests:** `tests/unit/test_purepy_candidate_index.py` (recall + persistencia + borrado).
- **Riesgos:** memoria si la colección es enorme; mitigar con la caché LRU acotada y
  fallback a lectura por lotes.
- **Prompt de despliegue:** *"Eres SA-3. Crea PurePyTurboQuantCandidateIndex implementando CandidateIndexPort, que persiste/lee códigos en quantized_vectors vía QuantizedCodeStore y puntúa con TurboQuantAdapter.estimate_inner_products (de SA-2), con caché LRU por (colección,capa). Tests de recall vs IP exacto y de CRUD."*

## 13.6. SA-4 — Factory de índice de candidatos y selección de backend

- **Objetivo:** desacoplar orquestadores del backend concreto; elegir purepy/turbovec
  por settings y disponibilidad.
- **Archivos (nuevo):** `backend/atenex_nova/infrastructure/indexes/candidate_index_factory.py`; `backend/atenex_nova/shared/config/settings.py`; `dependencies.py`; orquestadores.
- **Cambios concretos:**
  1. Settings: `candidate_backend: Literal["auto","purepy","turbovec"] = "auto"`.
  2. `build_candidate_index(session) -> CandidateIndexPort`: `auto` ⇒ turbovec si
     importable y `_use_turbovec()` activo, si no PurePy.
  3. Reemplazar instanciaciones directas de `TurboQuantCandidateIndex(session)` en
     `retrieval_orchestrator.py:102`, `ingestion_orchestrator.py:27`,
     `colpali_adapter.py:139` y `collection_cleanup_service.py:139` por la factory.
- **Aceptación:** con `ATENEX_CANDIDATE_BACKEND=purepy` el sistema funciona end-to-end
  sin turbovec; con `turbovec` usa el acelerado; `mypy` ve todo contra `CandidateIndexPort`.
- **Tests:** `tests/unit/test_candidate_index_factory.py` (selección por flag y por disponibilidad).
- **Dependencias:** SA-1, SA-3.
- **Prompt de despliegue:** *"Eres SA-4. Crea una factory build_candidate_index(session) que devuelva PurePy o turbovec según ATENEX_CANDIDATE_BACKEND y disponibilidad. Sustituye todas las instanciaciones directas de TurboQuantCandidateIndex por la factory en orquestadores, colpali_adapter y collection_cleanup_service. Tests de selección."*

## 13.7. SA-5 — Ingesta: una sola copia canónica (núcleo de H-2)

- **Objetivo:** dejar de duplicar dense. En LITE/STANDARD, Qdrant pasa a **sparse-only**;
  el dense vive solo como códigos cuantizados.
- **Archivos:** `backend/atenex_nova/workers/jobs/mem_builder_job.py` (EmbedDocument); `backend/atenex_nova/workers/jobs/memory_enrichment_job.py` (EmbedPropositions/EmbedSummaries); `backend/atenex_nova/infrastructure/qdrant/qdrant_adapter.py`; `backend/atenex_nova/infrastructure/visual/colpali_adapter.py`.
- **Cambios concretos:**
  1. Introducir helper `dense_goes_to_qdrant(settings) -> bool` (True solo en perfil MAX).
  2. En los tres jobs de embed: siempre `candidate_index.add_vectors(...)` (canónico);
     **solo** hacer `qdrant.upsert` con vector dense cuando `dense_goes_to_qdrant`. En
     LITE/STANDARD, hacer upsert **sparse-only**.
  3. `QdrantAdapter.init_collection`/`upsert`: permitir puntos **sin** vector dense
     (colección con solo `sparse` cuando el perfil no usa Qdrant dense), o crear la
     colección sparse-only. Ajustar `search` para no exigir dense.
  4. Quitar el `chunk.embedding_ref = point_id` cuando no haya punto Qdrant dense (o
     apuntarlo al `node_id`/código).
  5. Visual: idem (canónico vía candidate index; Qdrant `pages_visual` opcional según
     perfil), preservando el binding de cita por `page_asset_path`.
- **Aceptación:** tras ingerir un documento en STANDARD, **no** existen vectores dense
  en las colecciones Qdrant (solo sparse); sí existen códigos en `quantized_vectors`; la
  búsqueda dense devuelve resultados vía candidate index. En MAX, comportamiento dense
  por Qdrant intacto.
- **Tests:** `tests/integration/test_ingest_single_copy.py` (verifica ausencia de dense
  en Qdrant en STANDARD y presencia de códigos); regresión de la cadena de jobs.
- **Dependencias:** SA-4.
- **Riesgos:** ruptura del esquema Qdrant (dense+sparse) existente; cubrir con
  `init_collection` condicional y migración de colecciones nuevas (la limpieza de §9
  garantiza arranque limpio).
- **Prompt de despliegue:** *"Eres SA-5. Refactoriza los jobs de embed (chunks, proposiciones, summaries, visual) para que el dense canónico sea SIEMPRE el índice de candidatos cuantizado, y Qdrant reciba dense float32 SOLO en perfil MAX; en LITE/STANDARD Qdrant pasa a sparse-only (ajusta init_collection/upsert/search del QdrantAdapter para puntos sin dense). Test de integración que verifique una sola copia dense."*

## 13.8. SA-6 — Retrieval, limpieza y rebuild coherentes

- **Objetivo:** que la recuperación puntúe con el estimador, eliminar el camino muerto y
  alinear cleanup/rebuild con el nuevo modelo de una sola copia.
- **Archivos:** `backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py`; `backend/atenex_nova/application/services/collection_cleanup_service.py`; `backend/atenex_nova/workers/jobs/mem_builder_job.py` (RebuildCollection).
- **Cambios concretos:**
  1. `_score_chunks/_score_propositions/_score_summaries`: usar el `score` del candidate
     index (ya estimado por IP) como dense; la rama Qdrant dense solo se activa en MAX.
  2. Inyectar el reranker como dependencia (resuelve H-10) y aplicarlo en **una** pasada
     final, no por capa, para reducir coste.
  3. Cleanup: `_delete_vector_indexes` debe borrar (a) colecciones Qdrant existentes,
     (b) `quantized_vectors` por colección, (c) archivos `.tvim` si el backend turbovec
     estuvo activo. Ya hay base; verificar que cubre purepy (borrado SQL).
  4. Rebuild: además de requeue, borrar códigos `quantized_vectors` de los documentos.
- **Aceptación:** una query en STANDARD recupera por estimador (logs muestran
  `retrieval_stage="dense_turbo_ip"`); borrar una colección elimina códigos, sparse
  Qdrant y `.tvim`; rebuild deja la colección sin códigos previos antes de re-ingerir.
- **Tests:** `tests/integration/test_retrieval_purepy.py`, `test_cleanup_removes_codes.py`.
- **Dependencias:** SA-3, SA-4, SA-5.
- **Prompt de despliegue:** *"Eres SA-6. Ajusta el RetrievalOrchestrator para puntuar dense con el estimador del candidate index (rama Qdrant dense solo en MAX), inyecta el reranker como dependencia y aplícalo en una sola pasada. Alinea CollectionCleanupService y RebuildCollection para borrar quantized_vectors. Tests de retrieval purepy y de limpieza."*

## 13.9. SA-7 — Lote de calidad (H-9, H-12, H-13 y consistencia)

- **Objetivo:** cerrar defectos de calidad que no dependen del rediseño VQ.
- **Archivos:** `settings.py`, `embedding_adapter.py`, `answer_orchestrator.py`, `colpali_adapter.py` (+ DTO/labels), `bm25_encoder.py`.
- **Cambios concretos:**
  1. **H-9:** emitir `WARNING` visible y un campo en `/health/dependencies` cuando se
     usan embeddings *fallback hash*; documentar que para evaluar calidad hay que correr
     en `prod`/`require_embeddings`. Opcional: prohibir indexar con embeddings fallback
     salvo flag explícito `ATENEX_ALLOW_FALLBACK_EMBEDDINGS`.
  2. **H-13:** separar el piso del grounding del umbral strict: bajar el offset 0.35 a un
     valor calibrable (`grounding_floor`, default 0.0–0.15) o derivar el umbral de un set
     de calibración; documentar la fórmula.
  3. **H-12:** renombrar `ColPaliAdapter` → `VisualPageRetriever` (alias de compat) y/o
     etiquetar claramente `retrieval_backend: "page_text_embedding"` en UI/DTO; o, si se
     desea ColPali real, abrir issue separado (no en este lote).
  4. Refit BM25: cachear el corpus tokenizado por colección cuando aplique (H-11).
- **Aceptación:** health expone `embeddings.fallback=true/false`; el grounding no parte
  artificialmente de 0.35; la UI/DTO no afirma "ColPali" donde es texto de página.
- **Tests:** unit de grounding (sin piso inflado), de health fallback flag.
- **Dependencias:** SA-1.
- **Prompt de despliegue:** *"Eres SA-7. Cierra H-9 (warning + flag de embeddings fallback), H-13 (separar piso de grounding del umbral strict, hacerlo calibrable) y H-12 (clarificar/renombrar la ruta 'ColPali' que en realidad es page_text_embedding). Añade tests. No toques el rediseño de VecQuant."*

## 13.10. SA-8 — Tests, benchmarks y validación final (puerta de aceptación)

- **Objetivo:** demostrar el invariante §13.1 con runtimes activos.
- **Archivos:** `backend/tests/integration/*`, `backend/tests/e2e/*`, `backend/scripts/clean_all.py` (ya existe), `evaluation/`.
- **Cambios concretos:**
  1. Test de "una sola copia" (de SA-5) en e2e completo de ingesta→consulta→respuesta.
  2. Benchmark de recall del estimador vs IP exacto y de latencia de candidatos.
  3. Golden sets mínimos por modo (`exact`, `factual_local`, `multi_hop`, `global`,
     `argumentative`, `visual`) con criterio de aprobación.
  4. Ejecutar limpieza, levantar Ollama/Qdrant/modelos, correr `pytest tests -q`,
     `ruff`, `mypy` (sin ampliar ignores), `npm run build/lint`, y `/health/dependencies`.
- **Aceptación:** todos los checks de §0/§13.1 en verde **con evidencia adjunta** (logs),
  sin skips por dependencias ausentes.
- **Dependencias:** todas las anteriores.
- **Prompt de despliegue:** *"Eres SA-8. Implementa los tests de integración/e2e del invariante de una sola copia y del estimador (recall vs IP exacto), crea golden sets mínimos por modo, y ejecuta la suite completa + ruff + mypy + frontend + health con runtimes activos. Reporta evidencia real (no afirmes verde sin logs)."*

## 13.11. SA-9 — Alineación documental (cierra H-15 y consistencia)

- **Objetivo:** que README/AGENTS/turboquant-integration/tesis describan exactamente lo
  implementado tras SA-1..SA-7.
- **Archivos:** `README.md`, `AGENTS.md`, `docs/turboquant-integration.md`, `docs/architecture-backend.md`, esta auditoría.
- **Cambios concretos:**
  1. `turboquant-integration.md`: reescribir §2 (ahora **una** copia canónica; describir
     el estimador IP; turbovec como acelerador opcional).
  2. README: marcar proposiciones/resúmenes/grafo como **heurísticos**, la ruta visual
     como *page-text embedding*, y TurboQuant como optimización local (no contribución
     de tesis). Quitar claims no verificables ("63 passed", "100% green") o anclarlos a
     un comando reproducible.
  3. Nota de alcance: la tesis no evalúa VQ; documentar VQ como ingeniería local-first
     fuera del contrato académico (o proponer su inclusión formal).
- **Aceptación:** no quedan afirmaciones contradichas por el código; enlaces vivos.
- **Dependencias:** SA-5, SA-6.
- **Prompt de despliegue:** *"Eres SA-9. Reescribe docs/turboquant-integration.md y ajusta README/AGENTS para reflejar: una sola copia dense canónica + estimador IP + turbovec opcional; proposiciones/resúmenes/grafo heurísticos; ruta visual = page_text_embedding; TurboQuant como optimización fuera del alcance de la tesis. Elimina claims no reproducibles."*

## 13.12. Matriz hallazgo → subagente

| Hallazgo | Subagente(s) que lo cierran |
|---|---|
| H-1 (turbovec no declarado / import duro) | SA-1, SA-4 |
| H-2 (persistencia triple) | SA-5 (+ SA-6 cleanup) |
| H-3 (adapter muerto / bits no puntúan) | SA-2, SA-3, SA-6 |
| H-4 (diverge del estimador de referencia) | SA-2 |
| H-5 / H-6 (recarga / reescritura de índice) | SA-3 (caché LRU) |
| H-9 (fallback hash silencioso) | SA-7 |
| H-10 (reranker por llamada) | SA-6 |
| H-12 (ColPali engañoso) | SA-7, SA-9 |
| H-13 (grounding con piso inflado) | SA-7 |
| H-15 (tesis no contempla VQ) | SA-9 |
| H-16 / mypy ignores | SA-8 (no ampliar ignores), SA-9 |

## 13.13. Comando para orquestar los subagentes

Lanzar en el orden del DAG (§13.2). SA-7 y SA-9 pueden ir en paralelo a la cadena
crítica tras SA-1. SA-8 siempre al final como puerta. Cada subagente debe terminar con
su paquete de tests en verde antes de ceder el turno; el coordinador valida el
invariante §13.1 antes de declarar el cierre.

---

# 14. Estado tras corrección (validado 2026-06-16) — LEER PRIMERO

> Esta sección refleja el **código actual** del repositorio tras ejecutar la cadena de
> subagentes SA-1 → SA-7 del plan §13, más una corrección de tipos posterior. Es la
> fuente de verdad vigente. Verificado por lectura de código y ejecución real de
> herramientas con `backend/.venv312`.

## 14.1. Verificación ejecutada en esta ronda

| Verificación | Resultado | Evidencia |
|---|---|---|
| `pytest tests` (unit+integration+e2e) | ✅ **93 passed, 0 skipped** | Con Qdrant+Ollama vivos (§15, 2026-06-16) |
| `pytest tests` (sin Qdrant live) | ✅ **90 passed, 3 skipped** | Sesión anterior, `.venv312` |
| `mypy atenex_nova` | ✅ **Success: no issues found in 155 source files** | Ejecutado tras fix de tipos |
| `ruff check atenex_nova` | ✅ **All checks passed (0 issues)** | Subagente SA-8-verify |
| `npm run lint` (frontend) | ✅ ESLint exit 0 | Subagente SA-8-verify |
| `npm run build` (frontend) | ✅ `tsc -b` + Vite OK | Subagente SA-8-verify |
| Golden sets por modo / benchmark latencia con runtimes vivos | ❌ Pendiente | Requiere evaluación manual (SA-8) |
| `/health/dependencies` con stack levantado | ✅ Hecho | `ok` — embeddings locales vía Ollama |
| Métricas reales recall/answer/grounding | ❌ Pendiente | Golden sets no implementados |

## 14.2. Estado por hallazgo (contraste con §10)

| ID | Severidad orig. | Estado actual | Evidencia en código |
|---|---|---|---|
| **H-1** turbovec no declarado / import duro | CRÍTICA | ✅ **Cerrado** | `pyproject.toml:55-61` extra `accel`; imports perezosos (`_id_map_index_type()`, factory); `tests/unit/test_imports_without_turbovec.py` |
| **H-2** triple persistencia | CRÍTICA | ✅ **Cerrado** | `application/policies/indexing_policy.py` `dense_goes_to_qdrant()`; Qdrant dense solo en MAX; jobs upsert sparse-only en LITE/STANDARD; `tests/integration/test_ingest_single_copy.py` |
| **H-3** adapter muerto / bits no puntúan | CRÍTICA | ✅ **Cerrado** | `TurboQuantAdapter.estimate_inner_products`; `PurePyTurboQuantCandidateIndex.search` lo usa; retrieval audita `dense_turbo_ip`; `dequantize` solo diagnóstico |
| **H-4** diverge del estimador de referencia | ALTA | ✅ **Cerrado** | Implementado estimador IP insesgado (no reconstrucción); `test_inner_product_ranking_recall`, `test_estimator_unbiased` |
| **H-5 / H-6** recarga / reescritura de índice | MEDIA | ✅ **Cerrado en ruta canónica** (purepy con caché LRU) / ⚠️ persiste solo en backend turbovec opcional | `purepy_candidate_index.py` (LRU por colección/capa) |
| **H-9** fallback hash silencioso | MEDIA | ✅ **Cerrado** | `ATENEX_ALLOW_FALLBACK_EMBEDDINGS`, `ensure_indexable()`, WARNING visible, `/health/dependencies` expone `fallback`; `test_embeddings_fallback_health.py` |
| **H-10** reranker por llamada | BAJA | ✅ **Cerrado** | Reranker inyectado en `__init__`; rerank neural en una pasada (`_rank_hits`) |
| **H-11** re-fit BM25 por scoring | BAJA | ❌ **Pendiente** | `bm25_encoder.py` aún hace `fit` por llamada |
| **H-12** "ColPali" engañoso | ALTA | ✅ **Cerrado** | `VisualPageRetriever` (+ alias `ColPaliAdapter`); `retrieval_backend: page_text_embedding` |
| **H-13** grounding con piso 0.35 | MEDIA | ✅ **Cerrado** | `grounding_floor=0.0` (`settings.py:118`); fórmula `floor + coverage·0.55 + citation·0.45` sin offset fijo (`answer_orchestrator.py:538-539`); `test_grounding_floor.py` |
| **H-15** tesis no contempla VQ | ALTA | 🟡 **Parcial** | Docs (`turboquant-integration.md`, README, AGENTS) alineados; nota académica formal de alcance aún recomendable |
| **H-16** inventario contradictorio | MEDIA | ✅ **Cerrado** | `final-gap-inventory.md` eliminado; este doc es la fuente |
| **mypy** `ignore_errors` en núcleo | MEDIA | 🟡 **Sin cambio (no agravado)** | `pyproject.toml:87-104` mantiene overrides; mypy pasa limpio en 155 files **sin ampliar** los ignores |

**Resumen:** 10/13 hallazgos cerrados; 2 parciales (H-15 nota académica, mypy ignores
heredados); 1 pendiente real (H-11).

## 14.3. Invariante §13.1 — veredicto actual

| # | Criterio | Estado |
|---|---|---|
| 1 | Una copia dense en LITE/STANDARD; cero float32 dense en Qdrant | ✅ Cumple (tests integración + E2E) |
| 2 | Scoring por estimador IP; Recall@10 ≥ 0.90 vs IP exacto | ✅ Cumple (`test_turboquant`, `test_purepy_candidate_index`) |
| 3 | `pip install` sin turbovec no rompe imports | ✅ Cumple (`test_imports_without_turbovec`) |
| 4 | `dequantize` solo diagnóstico; producción no reconstruye | ✅ Cumple |
| 5 | ruff / mypy / pytest / npm verdes | ✅ Cumple (93/0 con Qdrant live; mypy 155 files) |

## 14.4. Errores encontrados y corregidos en esta ronda de validación

1. **Regresión E2E por `indexing_policy.dense_goes_to_qdrant`.** Asumía
   `settings.embedding_profile`, pero los E2E inyectan un `SimpleNamespace` sin ese
   atributo → `AttributeError` (5 E2E en rojo). **Corregido**: lectura defensiva con
   `getattr` sobre `embedding_profile` y *fallback* a `embedding_dimensions ≥ 768`.
2. **6 errores de mypy introducidos por SA-1..SA-7** (no cubiertos por los overrides):
   - `turboquant_candidate_index.py`: `_id_map_index_type() -> type` provocaba
     `no-any-return` + 3 `attr-defined` sobre `.load`. **Corregido**: anotar `-> Any`.
   - `indexing_policy.py`: `no-any-return` por `getattr`. **Corregido**: `cast`.
   - `candidate_index_factory.py`: `import-untyped` de `turbovec`. **Corregido**:
     `# type: ignore[import-untyped]`.
   - Resultado: **mypy limpio en 155 archivos** sin ampliar `ignore_errors`.

## 14.5. Qué falta (pendientes reales)

- **SA-8 completo (puerta de aceptación con runtimes vivos):** golden sets mínimos por
  modo (`exact`, `factual_local`, `multi_hop`, `global`, `argumentative`, `visual`),
  benchmark de latencia de candidatos (10k vectores) y recall estimador vs IP exacto a
  escala, y correr la suite con Ollama+Qdrant+modelos reales. Hoy la validación es
  local sin runtimes (tests con mocks/fallback).
- **H-11 (BAJA):** cachear el corpus tokenizado de BM25 por colección en lugar de
  re-`fit` por query.
- **H-15 (cierre académico):** decidir y documentar formalmente si VQ entra al contrato
  de la tesis o se declara optimización experimental fuera de alcance.
- **mypy `ignore_errors` (MEDIA):** estrechar progresivamente los overrides de
  `pyproject.toml:87-104` para que el núcleo (`retrieval_orchestrator`, workers,
  servicios) entre al chequeo estricto. No agravado, pero sigue invalidando el "verde"
  de tipos como señal de calidad del núcleo.
- **Backend turbovec opcional (H-5/H-6):** si se usa `ATENEX_CANDIDATE_BACKEND=turbovec`,
  persiste la recarga/reescritura de `.tvim` por operación. La ruta canónica purepy ya
  no tiene este problema; documentado como límite del acelerador opcional.

## 14.6. Acciones manuales para el usuario (no automatizables aquí)

1. **Limpieza total previa a re-ingesta:** `cd backend; .venv312\Scripts\python.exe
   scripts\clean_all.py --yes` (Qdrant + PostgreSQL + `storage/`).
2. **Qdrant vivo:** `docker compose up qdrant` (6333) — elimina los warnings de
   compatibilidad cliente/servidor y habilita la ruta sparse/dense real.
3. **Embeddings locales (offline-first):** `ollama pull embeddinggemma` (una vez). El
   backend usa Ollama por defecto (`ATENEX_EMBEDDING_BACKEND=ollama`), igual que el LLM,
   sin Hugging Face ni autenticación. El fallback hash solo aparece si Ollama no responde.
4. **turbovec opcional:** `pip install -e ".[accel]"` + `ATENEX_CANDIDATE_BACKEND=auto`
   si se desea el acelerador; por defecto el sistema usa la ruta pura-python.

## 14.7. Archivos clave tocados por la corrección (referencia)

- **VQ / índices:** `domain/ports/quantizer.py`,
  `infrastructure/vector_quantization/turboquant_adapter.py`,
  `infrastructure/indexes/purepy_candidate_index.py`,
  `infrastructure/indexes/turboquant_candidate_index.py`,
  `infrastructure/indexes/candidate_index_factory.py`.
- **Ingesta / retrieval:** `application/policies/indexing_policy.py`,
  `application/orchestrators/ingestion_orchestrator.py`,
  `application/orchestrators/retrieval_orchestrator.py`,
  `workers/jobs/mem_builder_job.py`, `workers/jobs/memory_enrichment_job.py`,
  `infrastructure/qdrant/qdrant_adapter.py`.
- **Calidad / visual / answer:** `shared/config/settings.py`,
  `infrastructure/embeddings/embedding_adapter.py`,
  `infrastructure/visual/colpali_adapter.py`, `workers/jobs/visual_index_job.py`,
  `application/orchestrators/answer_orchestrator.py`,
  `presentation/api/routers/health.py`, `presentation/api/dto/schemas.py`.
- **Tests nuevos:** `tests/unit/test_imports_without_turbovec.py`,
  `tests/unit/test_purepy_candidate_index.py`,
  `tests/unit/test_candidate_index_factory.py`, `tests/unit/test_grounding_floor.py`,
  `tests/unit/test_embeddings_fallback_health.py`,
  `tests/integration/test_ingest_single_copy.py`,
  `tests/integration/test_retrieval_purepy.py`,
  `tests/integration/test_cleanup_removes_codes.py`.
- **Docs:** `docs/turboquant-integration.md`, `README.md`, `AGENTS.md`.

---

# 15. Prueba end-to-end con servicios levantados (2026-06-16)

> Procedimiento ejecutado para validar la arquitectura post-corrección con runtimes
> reales. Complementa §12 y cierra la auditoría operacionalmente.

## 15.1. Servicios levantados

| Servicio | Comando | Puerto | Estado |
|---|---|---|---|
| **Qdrant** | `docker compose up -d qdrant` (desde raíz) | 6333/6334 | ✅ `healthz` → 200 |
| **Ollama** | Ya en ejecución local | 11434 | ✅ `/api/tags` → 200 |
| **API FastAPI** | `.venv312\Scripts\python.exe -m uvicorn atenex_nova.main:app --reload --port 8000` | 8000 | ✅ `/health` → `{"status":"ok"}` |
| **Worker** | `.venv312\Scripts\python.exe -m atenex_nova.workers.main` | — | ✅ polling jobs (recupera tras `clean_all`) |
| **Frontend Vite** | `npm run dev` (desde `frontend/`) | 5173 | ✅ ready |
| **PostgreSQL** | `docker compose --profile prod up -d` | 5432 | ⚠️ No levantado (dev usa SQLite) |

## 15.2. Limpieza previa

```powershell
cd backend
.venv312\Scripts\python.exe scripts\clean_all.py --yes
```

**Resultado:** SQL drop+recreate, 24 colecciones Qdrant eliminadas, `storage/turbovec`,
`storage/visual_pages`, `storage/uploads` recreados vacíos.

## 15.3. Health check (evidencia)

`GET http://127.0.0.1:8000/health/dependencies`:

| Dependencia | Disponible | Notas |
|---|---|---|
| llm (Ollama) | ✅ | `gemma4:12b` en GPU local |
| qdrant | ✅ | Colecciones vacías post-clean |
| embeddings | ✅ | Ollama `embeddinggemma` local (768d → truncado MRL al dim del perfil) |
| docling | ✅ | import OK |
| visual | ✅ | directorio vacío |
| turbovec | ✅ | paquete instalado en `.venv312` |

**Status global:** `ok`. Embeddings 100% locales vía Ollama (`embeddinggemma`), igual
que el LLM — sin Hugging Face ni autenticación. Requisito único: `ollama pull
embeddinggemma` (una vez). El fallback hash solo se activa si Ollama no responde.

## 15.4. Suite de tests con runtimes vivos

```powershell
cd backend
.venv312\Scripts\python.exe -m pytest tests -q
```

| Métrica | Sin Qdrant (sesión anterior) | **Con Qdrant+Ollama (esta sesión)** |
|---|---|---|
| Passed | 90 | **93** |
| Skipped | 3 | **0** |
| Failed | 0 | **0** |
| Duración | ~367 s | **~267 s** |

Los 3 tests que antes hacían *skip* por Qdrant no disponible ahora **pasan** con el
servicio vivo.

## 15.5. Prueba manual recomendada (UI)

1. Abrir `http://localhost:5173/`
2. Crear colección → subir PDF/TXT de prueba
3. Esperar a que el worker complete la cadena de jobs (consola worker: `succeeded`)
4. Consultar en chat: verificar respuesta con citas y evidencia
5. Inspeccionar en Qdrant (`http://localhost:6333/dashboard`): colección `collection_*`
   debe tener puntos **solo sparse** (sin vector dense en LITE/STANDARD)
6. Inspeccionar SQL: filas en `quantized_vectors` con `idx_blob`/`qjl_blob` poblados

## 15.6. Veredicto final de la auditoría

| Área | Veredicto |
|---|---|
| Arquitectura hexagonal + pipeline multi-capa | ✅ Sólida y operativa |
| VecQuant/TurboQuant (Opción A §13) | ✅ **Implementada** — una copia dense + estimador IP |
| Reproducibilidad (`pip install -e ".[all]"` sin turbovec) | ✅ Imports OK; purepy por defecto |
| Tests automatizados | ✅ **93/93** con stack local completo |
| Calidad semántica real | ✅ Embeddings locales vía Ollama (`embeddinggemma`) |
| Golden sets / evaluación académica | ❌ Pendiente (SA-8, H-15) |
| Deuda técnica menor | H-11 (BM25 cache), mypy ignores heredados |

**Documento cerrado operacionalmente.** Para producción/evaluación de calidad: login HF,
golden sets por modo, y opcionalmente `docker compose --profile prod up -d` si se
migra a PostgreSQL.
