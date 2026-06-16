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
| Limpieza de la DB relacional de desarrollo (SQLite) | ✅ Hecho | Se borró `backend/atenex_nova.db` (265 MB) |
| Limpieza de Qdrant (servicio Docker) y PostgreSQL | ⚠️ No ejecutado | El shell del agente está caído; se entrega script ejecutable |
| Limpieza de `storage/` (turbovec, visual_pages, uploads) | ⚠️ No ejecutado | Idem; cubierto por el script |
| Ejecución de la suite de tests (`pytest`) | ❌ No ejecutado | Shell del agente caído |
| Verificar que `turbovec` está instalado en `.venv312` | ❌ No verificable | El venv está fuera del índice (gitignored) |
| Métricas reales de recuperación/answer/grounding | ❌ No ejecutado | Requiere runtimes (Ollama, Qdrant, modelos) |

> **Limpieza realizada en esta sesión:** se eliminó la base SQLite de desarrollo
> `backend/atenex_nova.db` (que contenía las colecciones de dev, 265 MB). No había
> ficheros `-wal`/`-shm`. Para **Qdrant + PostgreSQL + `storage/`** se entrega el
> script `backend/scripts/clean_all.py` (ver §9), porque esos sistemas requieren un
> proceso vivo / cliente HTTP que el shell del agente no pudo lanzar.

**Conclusión global del veredicto:** la arquitectura hexagonal está bien planteada y
el pipeline multi-capa es real y funcional, pero la integración "VecQuant/TurboQuant"
**no está implementada como la describen los documentos del repositorio**: hay
redundancia de persistencia, código de cuantización propio que no participa en el
scoring, una dependencia no declarada (`turbovec`) y desalineaciones de nombre
("ColPali") y de fuente de verdad (la tesis no contempla cuantización vectorial).

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
- **H-10 (ALTA, requiere verificación runtime): reranker instanciado por llamada.** En
  `_rerank_hits` se hace `RerankerAdapter(required=...)` **dentro del método**, en cada
  invocación (`retrieval_orchestrator.py:854-858`), y `_rerank_hits` se llama varias
  veces por query (una por capa + fusión). Si `RerankerAdapter` carga el cross-encoder
  en el constructor, esto implica **recargar el modelo varias veces por consulta** →
  latencia catastrófica. *Acción:* confirmar si hay singleton/caché en
  `reranker_adapter.py`; si no, cachear el modelo. (No pude leer ese archivo en
  profundidad en esta pasada; marcado para verificación.)
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
| H-10 | ALTA* | Reranker posiblemente instanciado/recargado por llamada y varias veces por query | `retrieval_orchestrator.py:854-858` (*verificar* `reranker_adapter.py`) |
| H-12 | ALTA | "ColPali" no es ColPali: embebe texto de página, no visión multi-vector | `colpali_adapter.py:97,197` |
| H-13 | MEDIA | Grounding heurístico con piso 0.35 ≈ umbral strict | `answer_orchestrator.py:538`, `settings.py:116` |
| H-15 | ALTA | La tesis no contempla VQ; TurboQuant es capa de repo sin respaldo académico | Tesis §1.9, §2.6 |
| H-16 | MEDIA | El inventario anterior se contradecía (ruff/mypy 0 vs 6/5) | `final-gap-inventory.md` (eliminado) |
| — | MEDIA | `mypy ignore_errors=true` en módulos núcleo invalida el "verde" | `pyproject.toml:83-100` |

\* Severidad sujeta a confirmación de `reranker_adapter.py` en runtime.

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
