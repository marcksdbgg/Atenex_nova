# Plan de corrección operacional y VecQuant

> **Estado de cierre (2026-06-16):** SA-1..SA-9 implementados en código. Backend **96 passed / 3 skipped**, ruff/mypy limpios, frontend build verde. Import sessions durables, pipeline-status real en `/collections`, VecQuant `purepy` en `auto`, summaries lineales, visual TXT skipped, SQLite worker guard activo. Validación runtime manual (screenshot / carga 500 TXT) pendiente si los servicios no están levantados.

> Documento de ejecución para subagentes. Este plan parte de la auditoría viva de
> `/collections`, SQLite, Qdrant, workers y VecQuant realizada el 2026-06-16/17.
> No reemplaza a `docs/auditoria-completa.md`; la complementa con el plan de cierre
> para que el sistema procese corpus grandes sin ocultar estado real.

## 1. Objetivo

Corregir Atenex Nova hasta que la ingesta masiva, la trazabilidad, el worker y el
retrieval dense cuantizado funcionen de forma consistente, observable y medible.

El resultado esperado es:

- VecQuant/TurboQuant conectado de verdad en el camino por defecto.
- `candidate_backend=auto` sin rutas muertas ni falsos aceleradores.
- Ingesta de miles de TXT sin trabajo cuadrático innecesario.
- `/collections` mostrando estado real desde jobs, auditoría e import sessions.
- Importación masiva con conteos durables: descubiertos, aceptados, duplicados,
  omitidos, fallidos y pendientes.
- SQLite protegido de concurrencia peligrosa o sustituido por PostgreSQL para carga
  masiva.
- Validación final con métricas reales, no solo tests unitarios.

## 2. Estado actual verificado

Snapshot operacional:

- API viva en `127.0.0.1:8000`.
- Frontend vivo en `localhost:5173`.
- Qdrant vivo en `6333/6334`, pero Docker lo marca `unhealthy` por healthcheck con
  `curl` ausente en la imagen.
- Ollama vivo en `11434`.
- PostgreSQL no está levantado; el backend usa SQLite:
  `backend/atenex_nova.db`.
- Colección viva: `Jesus G`, id `7a283d12-8f04-4f8d-9217-383631162ebd`.
- Documentos persistidos: `410` total, `407 ready`, `3 failed`.
- Uploads en disco: `410` archivos, no hay discrepancia DB-storage.
- Jobs aproximados al momento de auditoría: más de `4000` total, con cientos
  pendientes y varios `running`.
- La UI muestra `COLA 0`, pero la DB tiene jobs pendientes y corriendo.

Errores confirmados:

- `sqlite3.OperationalError: database is locked` en jobs de visual indexing.
- `Recovered stale running job` repetido.
- Qdrant `pages_visual` con `0` puntos aunque hay eventos visuales marcados como
  `succeeded`.
- Logs actuales no están persistidos como archivos; API/worker escriben a stdout.
- Qdrant contiene colecciones residuales no alineadas con la SQLite viva.

## 3. Problemas a cerrar

### P0. VecQuant/TurboQuant está mal cableado en el camino real

El problema no es solo matemático; es de wiring.

Estado observado:

- `candidate_backend=auto` puede elegir `TurboQuantCandidateIndex` si `turbovec` está
  instalado.
- En STANDARD/LITE, `dense_goes_to_qdrant=False`.
- En esa combinación, la ingesta puede no escribir `.tvim`, pero retrieval intenta
  buscar en el backend `turbovec`.
- Resultado: dense cuantizado puede quedar inoperante y el sistema cae a sparse,
  BM25, Qdrant o rerank textual, pagando igual cuantización SQL.

Decisión obligatoria:

- Ruta canónica recomendada: `purepy` como backend por defecto para
  STANDARD/LITE, usando `quantized_vectors` y `TurboQuantAdapter.estimate_inner_products`.
- `turbovec` debe ser acelerador explícito solo cuando el índice `.tvim` exista, esté
  actualizado y tenga cobertura por colección/capa.
- `auto` no puede elegir `turbovec` solo porque el paquete sea importable.

### P0. `embed_summaries` tiene coste cuadrático

Cada documento genera un `collection_summary`. Luego cada `EmbedSummariesJobHandler`
carga todos los resúmenes de colección existentes y los vuelve a embeber.

Efecto:

- Con N documentos, el trabajo puede crecer cerca de `N^2 / 2`.
- Con 1900 TXT, esto puede producir millones de embeddings pequeños.
- VecQuant no puede compensar un pipeline que repite trabajo masivamente.

### P0. Visual indexing corre para TXT/plain

`INDEX_VISUAL_PAGES` se encola para documentos de texto y procesa páginas textuales.
Además el adapter visual persiste JSON local por colección releyendo y reescribiendo el
archivo completo.

Efecto:

- Trabajo innecesario para TXT.
- Posible coste O(N²) por persistencia local de páginas visuales.
- Errores Qdrant `400` invisibles o mal representados.
- `/collections` no muestra el bloqueo real.

### P0. `/collections` no muestra estado real de jobs

La UI calcula:

- documentos totales desde documentos cargados;
- activos desde documentos no `ready`/`failed`;
- cola desde `uploadQueues` local.

No calcula estado real desde `/jobs`.

Efecto:

- Muestra `COLA 0` aunque hay cientos de jobs pendientes.
- Oculta `running`, `pending`, `failed`, stale jobs y locks.
- La trazabilidad avanzada parece viva, pero no representa el pipeline completo.

### P1. Importación masiva sin sesión durable

La UI y API no guardan una sesión de importación con conteos reconciliables.

Faltan:

- archivos descubiertos;
- archivos intentados;
- documentos creados;
- duplicados por checksum;
- omitidos por extensión;
- fallidos por parseo o validación;
- jobs encolados;
- jobs pendientes por tipo;
- tiempo de inicio/fin;
- errores por archivo.

Además la carga masiva frontend puede lanzar el primer lote completo con `Promise.all`,
saltándose el límite posterior de 8.

### P1. SQLite no soporta esta concurrencia de workers

SQLite está recibiendo:

- API;
- varios workers;
- auditoría;
- Qdrant callbacks;
- escrituras de jobs;
- escrituras de quantized vectors;
- escrituras de relaciones y summaries.

Con dos workers activos aparecen locks reales. Para cargas masivas hay que:

- usar PostgreSQL; o
- forzar un solo worker y limitar concurrencia mientras `database_url` sea SQLite.

## 4. Invariantes de cierre

El plan solo está completo cuando se cumpla todo:

1. En STANDARD/LITE, una consulta real produce candidatos dense desde VecQuant o
   registra explícitamente por qué no lo hizo.
2. `candidate_backend=auto` nunca selecciona un backend sin índice utilizable.
3. Si `auto` elige `turbovec`, existen `.tvim` por colección/capa y su cobertura
   coincide con `quantized_vectors`.
4. Si no hay `.tvim`, `auto` usa `PurePyTurboQuantCandidateIndex`.
5. `embed_summaries` no re-embebe todos los resúmenes de colección en cada documento.
6. TXT/plain no ejecuta visual indexing salvo flag o modo visual explícito.
7. `/collections` muestra conteos reales de jobs: pending, running, failed, stale,
   succeeded reciente y cola por tipo.
8. Toda importación masiva tiene `import_session_id` y resumen durable.
9. No hay `database is locked` durante una ingesta de prueba con lote mediano.
10. Qdrant no queda con colecciones residuales tras cleanup/rebuild.
11. Los docs actualizados no afirman capacidades no verificadas.
12. La validación final incluye tests, health, UI screenshot y métricas de latencia.

## 5. DAG de subagentes

Ejecutar en este orden:

```text
SA-0 Snapshot y guardrails
  |
  +--> SA-1 VecQuant auto/purepy/turbovec
  |       |
  |       +--> SA-2 Retrieval dense y métricas VecQuant
  |
  +--> SA-3 Summaries sin coste cuadrático
  |
  +--> SA-4 Visual indexing para TXT y Qdrant visual
  |
  +--> SA-5 Import sessions durables
  |       |
  |       +--> SA-6 UI /collections estado real
  |
  +--> SA-7 SQLite/worker/concurrencia
          |
          +--> SA-8 Cleanup/rebuild/Qdrant consistency
                  |
                  +--> SA-9 Validación final y docs
```

Reglas:

- SA-1 y SA-3 son críticos y pueden correr en paralelo si no tocan los mismos archivos.
- SA-6 depende de SA-5 porque necesita datos durables de importación.
- SA-9 corre al final.
- Ningún subagente debe revertir cambios de otro.
- Cada subagente debe entregar archivos tocados, tests ejecutados y riesgos restantes.

## 6. Paquetes de trabajo

### SA-0. Snapshot y guardrails

Objetivo: dejar evidencia inicial reproducible antes de tocar código.

Responsabilidad:

- Levantar estado de procesos, puertos, DB, Qdrant y jobs.
- Guardar comandos en el reporte final del subagente.
- No limpiar ni reiniciar servicios.

Archivos esperados:

- Ninguno, salvo que se cree un script read-only de diagnóstico bajo `backend/scripts/`
  si se decide conservarlo.

Comandos:

```powershell
Get-NetTCPConnection -State Listen
docker ps
curl.exe http://127.0.0.1:8000/health/dependencies
backend/.venv312/Scripts/python.exe -m pytest tests/unit/test_openapi_documentation_contract.py -q
```

Consultas SQL read-only mínimas:

```sql
select status, count(*) from documents group by status;
select job_type, status, count(*) from jobs group by job_type, status order by job_type, status;
select memory_layer, count(*) from quantized_vectors where deleted_at is null group by memory_layer;
```

Aceptación:

- Reporte con cifras iniciales.
- Identificar si se está usando SQLite o PostgreSQL.
- Identificar workers activos.

Prompt sugerido:

> Eres SA-0. Haz snapshot read-only de Atenex Nova: servicios, SQLite/Postgres, Qdrant,
> documentos, jobs, audit events y storage. No edites ni limpies nada. Entrega cifras
> y comandos.

### SA-1. VecQuant backend selection correcto

Objetivo: corregir `candidate_backend=auto` para que no elija `turbovec` si no hay
índice `.tvim` utilizable.

Archivos principales:

- `backend/atenex_nova/infrastructure/indexes/candidate_index_factory.py`
- `backend/atenex_nova/infrastructure/indexes/turboquant_candidate_index.py`
- `backend/atenex_nova/infrastructure/indexes/purepy_candidate_index.py`
- `backend/atenex_nova/application/orchestrators/ingestion_orchestrator.py`
- `backend/atenex_nova/shared/config/settings.py`
- `backend/tests/unit/test_candidate_index_factory.py`
- `backend/tests/integration/test_retrieval_purepy.py`

Cambios requeridos:

1. Añadir una comprobación explícita de disponibilidad de índice:
   `candidate_index.is_usable(collection_id, memory_layer)` o helper equivalente.
2. Cambiar `auto`:
   - usa `purepy` por defecto en STANDARD/LITE;
   - usa `turbovec` solo si está configurado explícitamente o si `.tvim` existe,
     está actualizado y cubre la capa pedida;
   - cae a `purepy` con warning/audit si `turbovec` no tiene cobertura.
3. Si se decide que `turbovec` debe acelerarse en auto, entonces la ingesta debe
   escribir `.tvim` también en STANDARD/LITE. Esta variante requiere:
   - garantía de consistencia SQL codes <-> `.tvim`;
   - cleanup de `.tvim` en rebuild/delete;
   - tests de cobertura.
4. Registrar en audit de retrieval:
   - backend elegido;
   - capas usadas;
   - hits dense;
   - fallback reason.

Decisión recomendada:

- No escribir `.tvim` automáticamente todavía.
- Hacer `purepy` el backend canónico en `auto`.
- Reservar `turbovec` para `ATENEX_CANDIDATE_BACKEND=turbovec`.

Tests:

```powershell
cd backend
.venv312/Scripts/python.exe -m pytest tests/unit/test_candidate_index_factory.py tests/integration/test_retrieval_purepy.py -q
```

Aceptación:

- Con `turbovec` instalado pero sin `.tvim`, `auto` usa `purepy`.
- Retrieval devuelve hits dense desde `quantized_vectors`.
- El audit incluye `candidate_backend="purepy"` y `retrieval_stage="dense_turbo_ip"`.
- No hay ruta silenciosa donde dense quede vacío sin warning.

Prompt sugerido:

> Eres SA-1. Corrige `candidate_backend=auto`: no debe elegir `turbovec` solo porque el
> paquete esté instalado. Si no hay `.tvim` usable por colección/capa, debe usar
> `PurePyTurboQuantCandidateIndex`. Añade audit del backend elegido, tests unitarios e
> integración. No toques UI ni summaries.

### SA-2. Retrieval dense y métricas VecQuant

Objetivo: probar que VecQuant participa en retrieval real y medir su rendimiento.

Archivos principales:

- `backend/atenex_nova/application/orchestrators/retrieval_orchestrator.py`
- `backend/atenex_nova/application/services/query_service.py`
- `backend/atenex_nova/infrastructure/vector_quantization/turboquant_adapter.py`
- `backend/atenex_nova/infrastructure/indexes/purepy_candidate_index.py`
- `backend/tests/integration/test_retrieval_purepy.py`
- `backend/tests/e2e/test_*`

Cambios requeridos:

1. Exponer métricas por consulta:
   - `dense_candidate_backend`;
   - `dense_hits`;
   - `dense_latency_ms`;
   - `sparse_hits`;
   - `fusion_hits`;
   - `fallback_reason`.
2. Garantizar que una búsqueda en STANDARD/LITE intente dense VecQuant antes de caer a
   sparse.
3. Añadir test con corpus mínimo:
   - ingesta;
   - búsqueda;
   - assert de hits dense;
   - assert de audit `dense_turbo_ip`.
4. Añadir benchmark pequeño local:
   - 1k, 10k vectores sintéticos;
   - recall@10 vs IP exacto;
   - latencia p50/p95.

Aceptación:

- Se puede responder: "VecQuant se usó en esta query" con evidencia.
- Si no se usa, queda motivo visible.
- Recall@10 del estimador en benchmark controlado >= 0.90.

Prompt sugerido:

> Eres SA-2. Instrumenta retrieval para demostrar uso real de VecQuant: backend dense,
> hits, latencia, fallback reason y stage `dense_turbo_ip`. Añade test e2e mínimo y
> benchmark sintético recall/latencia. No cambies UI.

### SA-3. Summaries sin re-embedding cuadrático

Objetivo: eliminar el coste cuadrático de `embed_summaries`.

Archivos principales:

- `backend/atenex_nova/workers/jobs/memory_enrichment_job.py`
- `backend/atenex_nova/infrastructure/db/repositories/sql_summary_repo.py`
- `backend/atenex_nova/infrastructure/db/models/tables.py`
- `backend/tests/unit/*summary*`
- `backend/tests/integration/*summary*`

Cambios requeridos:

1. Separar summaries por alcance:
   - section summaries del documento;
   - document summary del documento;
   - collection summary agregado.
2. `EmbedSummariesJobHandler` no debe hacer:
   `summaries.extend(await summary_repo.list_by_collection(...))` en cada documento.
3. Opciones válidas:
   - embeber solo summaries creados por el job actual;
   - o crear job dedicado `EMBED_COLLECTION_SUMMARY` con debounce/coalescing;
   - o actualizar un único collection summary por colección en vez de crear uno por
     documento.
4. Evitar re-indexar summaries ya embebidos.
5. Añadir columna/metadata `embedding_ref` o equivalente para detectar si ya está
   embebido.

Tests:

- Ingesta de 5 documentos:
  - `embed_summaries` no debe embeber 1+2+3+4+5 collection summaries.
  - número de summary vectors debe crecer linealmente.
- Rebuild limpia summaries antiguos.

Aceptación:

- Para N documentos, cantidad de embeddings de summaries es O(N), no O(N²).
- Audit de `embed_summaries` muestra `summary_count` pequeño por documento.
- No se pierden summaries de colección; solo se actualizan de forma controlada.

Prompt sugerido:

> Eres SA-3. Elimina el coste cuadrático de summaries. `EmbedSummariesJobHandler` no
> debe re-embeber todos los collection summaries por documento. Diseña un flujo lineal
> con job o coalescing para collection summary. Añade tests de crecimiento O(N).

### SA-4. Visual indexing solo cuando corresponde

Objetivo: desactivar visual indexing para TXT/plain salvo configuración explícita.

Archivos principales:

- `backend/atenex_nova/workers/jobs/memory_enrichment_job.py`
- `backend/atenex_nova/workers/jobs/visual_index_job.py`
- `backend/atenex_nova/infrastructure/visual/colpali_adapter.py`
- `backend/atenex_nova/infrastructure/qdrant/qdrant_adapter.py`
- `backend/atenex_nova/shared/config/settings.py`
- `backend/tests/integration/*visual*`

Cambios requeridos:

1. Añadir política:
   - `should_index_visual(document, nodes, settings)`.
2. Para `text/plain`, `text/markdown`, `text/csv`:
   - no encolar `INDEX_VISUAL_PAGES` por defecto;
   - marcar visual como `skipped_text_only`;
   - no bloquear `ready`.
3. Para PDF/imagen:
   - mantener visual indexing si está habilitado.
4. Arreglar upsert visual en STANDARD:
   - si Qdrant visual requiere vector, mandar sparse o no reportar `succeeded`;
   - no tragar `400` como éxito.
5. Evitar reescritura completa de JSON local por página en corpus grandes, o al menos
   documentar que solo se usa como fallback pequeño.

Aceptación:

- TXT no genera jobs visuales por defecto.
- PDF sigue generando visual pages.
- Qdrant visual no queda con `0` puntos cuando audit dice indexed.
- `/health/dependencies` o audit reportan visual disabled/skipped claramente.

Prompt sugerido:

> Eres SA-4. Implementa política visual: TXT/plain no debe ejecutar
> `INDEX_VISUAL_PAGES` salvo flag explícito. Corrige audit para skipped y evita marcar
> succeeded si Qdrant visual rechaza puntos. Añade tests para TXT skipped y PDF indexed.

### SA-5. Import sessions durables

Objetivo: persistir el ciclo de importación masiva para reconciliar 1900 archivos vs
410 documentos.

Archivos principales:

- `backend/atenex_nova/infrastructure/db/models/tables.py`
- `backend/atenex_nova/domain/entities/*`
- `backend/atenex_nova/presentation/api/dto/schemas.py`
- `backend/atenex_nova/presentation/api/routers/collections.py`
- `backend/atenex_nova/application/services/document_service.py`
- `backend/atenex_nova/infrastructure/db/repositories/*`
- `docs/api-endpoints.md`

Modelo sugerido:

`import_sessions`

- `id`
- `collection_id`
- `source_kind`: `upload_batch`, `local_folder`
- `source_root`
- `collection_path`
- `status`: `running`, `completed`, `completed_with_errors`, `failed`, `cancelled`
- `discovered_count`
- `attempted_count`
- `created_count`
- `deduplicated_count`
- `skipped_count`
- `failed_count`
- `queued_jobs_count`
- `started_at`
- `completed_at`
- `error`

`import_session_items`

- `id`
- `session_id`
- `relative_path`
- `source_path`
- `checksum`
- `mime_type`
- `status`: `created`, `deduplicated`, `skipped`, `failed`, `queued`
- `document_id`
- `job_id`
- `error`

Cambios requeridos:

1. `import-folder` debe devolver `import_session_id`.
2. La carga por archivos debe poder crear una sesión también.
3. Deduplicación por checksum debe quedar explícita por item.
4. Formatos no soportados deben poder omitirse antes de encolar parse, si se decide.
5. API para consultar sesión:
   - `GET /collections/{id}/import-sessions`
   - `GET /import-sessions/{id}`
   - `GET /import-sessions/{id}/items`

Aceptación:

- Si se importan 1900 archivos y 410 son únicos, la UI/API lo muestran así:
  `1900 discovered`, `410 created`, `1490 deduplicated/skipped`.
- Si el frontend falla, el backend conserva la sesión.
- No se pierde la explicación del conteo.

Prompt sugerido:

> Eres SA-5. Diseña e implementa import sessions durables para upload batch y
> import-folder. Deben persistir descubiertos, creados, duplicados, omitidos, fallidos
> y jobs encolados por item. Añade endpoints y tests. No cambies todavía la UI salvo
> tipos mínimos.

### SA-6. `/collections` con estado real

Objetivo: rediseñar la ruta `/collections` para mostrar el estado real de jobs,
import sessions y auditoría.

Archivos principales:

- `frontend/src/pages/Pages.tsx`
- `frontend/src/services/api.ts`
- `backend/atenex_nova/presentation/api/routers/jobs.py`
- `backend/atenex_nova/presentation/api/routers/observability.py`
- `backend/atenex_nova/presentation/api/dto/schemas.py`
- `docs/architecture-frontend.md`

Cambios requeridos:

1. Añadir endpoint resumen por colección:
   - documentos por estado;
   - jobs por estado/tipo;
   - jobs stale;
   - import sessions recientes;
   - errores recientes;
   - último audit event por stage.
2. `/collections` debe reemplazar `COLA` local por cola real:
   - `pending`;
   - `running`;
   - `failed`;
   - `stale/recovered`.
3. Mostrar un panel "Estado real del pipeline":
   - parse;
   - segment;
   - embed chunks;
   - propositions;
   - summaries;
   - graph;
   - visual.
4. Logs de colección no deben limitarse a 8 sin indicar que es un recorte.
5. Trazabilidad avanzada debe mostrar:
   - jobs pendientes del documento;
   - jobs running;
   - jobs failed;
   - audit events;
   - fallback embeddings;
   - backend dense usado.
6. Carga masiva frontend:
   - no lanzar `initialBatch` completo con `Promise.all`;
   - procesar en lotes configurables;
   - mostrar sesión durable si existe.

Aceptación:

- En el estado auditado, la UI no puede decir `COLA 0`.
- Debe mostrar cientos de pending/running si existen.
- Debe mostrar `database is locked` y Qdrant visual errors en errores recientes.
- Screenshot desktop de `/collections` prueba los conteos reales.

Prompt sugerido:

> Eres SA-6. Corrige `/collections` para mostrar estado real desde jobs/import sessions,
> no desde estado local de React. Añade endpoint resumen si hace falta. Arregla carga
> masiva para procesar por lotes reales. Verifica con navegador y screenshot.

### SA-7. SQLite, workers y concurrencia

Objetivo: impedir locks y estados corruptos durante ingesta masiva.

Archivos principales:

- `backend/atenex_nova/workers/main.py`
- `backend/atenex_nova/workers/runner.py`
- `backend/atenex_nova/infrastructure/db/session.py`
- `backend/atenex_nova/shared/config/settings.py`
- `docker-compose.yml`
- `README.md`

Cambios requeridos:

1. Detectar SQLite en runtime.
2. Si DB es SQLite:
   - limitar workers efectivos a 1;
   - limitar concurrencia interna;
   - usar timeout/busy_timeout y WAL de forma explícita;
   - advertir en `/health/dependencies`.
3. Si DB es PostgreSQL:
   - permitir múltiples workers.
4. Añadir lock/claim atómico de jobs:
   - evitar que dos workers tomen el mismo pending;
   - usar update condicional o transacción adecuada.
5. Revisar `requeue_stale_running`:
   - no reencolar jobs realmente activos;
   - registrar stale con timestamps claros.

Aceptación:

- Con SQLite y dos workers iniciados, el sistema advierte o bloquea el segundo worker.
- No aparecen `database is locked` en ingesta de prueba pequeña.
- README dice claramente: cargas masivas requieren PostgreSQL o worker único.

Prompt sugerido:

> Eres SA-7. Endurece workers/SQLite. Si el backend usa SQLite, limita a un worker o
> bloquea concurrencia peligrosa; añade health warning. Implementa claim de job seguro
> y tests. No cambies VecQuant.

### SA-8. Cleanup, rebuild y consistencia Qdrant

Objetivo: que SQL, storage y Qdrant no queden desalineados.

Archivos principales:

- `backend/atenex_nova/application/services/collection_cleanup_service.py`
- `backend/atenex_nova/workers/jobs/rebuild_collection_job.py`
- `backend/scripts/clean_all.py`
- `backend/atenex_nova/infrastructure/qdrant/qdrant_adapter.py`
- `backend/tests/integration/test_cleanup_removes_codes.py`

Cambios requeridos:

1. Cleanup por colección debe borrar:
   - documents;
   - nodes;
   - chunks;
   - propositions;
   - summaries;
   - relation_edges;
   - quantized_vectors;
   - visual page cache;
   - `.tvim` si existe;
   - Qdrant collections por naming real;
   - import sessions si corresponde.
2. Detectar Qdrant orphan collections:
   - endpoint o script read-only `diagnose_qdrant_orphans`.
3. Rebuild debe cancelar o borrar jobs pendientes/running de la colección antes de
   reencolar.
4. Qdrant healthcheck Docker:
   - reemplazar `curl` por método disponible o quitar healthcheck inválido.

Aceptación:

- Tras borrar colección no quedan Qdrant collections de ese id.
- Tras rebuild no quedan jobs duplicados antiguos.
- `clean_all.py --yes` deja Qdrant, SQL y storage alineados.

Prompt sugerido:

> Eres SA-8. Alinea cleanup/rebuild/Qdrant. Borra todos los artefactos derivados por
> colección, detecta orphans de Qdrant, corrige healthcheck inválido y añade tests de
> cleanup. No cambies UI salvo si necesitas exponer diagnóstico.

### SA-9. Validación final y documentación

Objetivo: demostrar cierre completo.

Archivos principales:

- `README.md`
- `AGENTS.md`
- `docs/auditoria-completa.md`
- `docs/turboquant-integration.md`
- `docs/jobs-and-workers.md`
- `docs/api-endpoints.md`
- `docs/architecture-frontend.md`
- `docs/plan-correccion-vecquant-operacional.md`

Validación requerida:

Backend:

```powershell
cd backend
.venv312/Scripts/python.exe -m ruff check .
.venv312/Scripts/python.exe -m mypy atenex_nova
.venv312/Scripts/python.exe -m pytest tests -q
```

Frontend:

```powershell
cd frontend
npm run lint
npm run build
```

Runtime:

```powershell
curl.exe http://127.0.0.1:8000/health/dependencies
curl.exe http://127.0.0.1:8000/collections
curl.exe "http://127.0.0.1:8000/jobs?limit=50"
```

Prueba manual mínima:

1. Iniciar Qdrant y Ollama.
2. Usar PostgreSQL para carga masiva o SQLite con worker único.
3. Crear colección limpia.
4. Importar carpeta de prueba con duplicados conocidos.
5. Verificar import session:
   - discovered;
   - created;
   - deduplicated;
   - skipped;
   - failed.
6. Esperar pipeline.
7. Verificar `/collections`:
   - cola real;
   - jobs por tipo;
   - errores recientes;
   - audit stages.
8. Ejecutar query y confirmar audit:
   - `dense_candidate_backend`;
   - `dense_turbo_ip`;
   - hits dense > 0 cuando haya códigos.

Aceptación:

- La documentación coincide con el código.
- No quedan claims de "VecQuant optimiza todo" sin benchmark.
- Se documenta exactamente cuándo `purepy`, `turbovec` y Qdrant dense se usan.
- Se incluye evidencia de screenshot o navegador para `/collections`.

Prompt sugerido:

> Eres SA-9. Ejecuta validación final completa: backend tests, ruff, mypy, frontend
> lint/build, health runtime, prueba de import session y `/collections` con navegador.
> Actualiza docs para reflejar exactamente el estado real. No declares verde sin logs.

## 7. Matriz de errores a subagentes

| Error | Subagente principal | Subagentes relacionados |
|---|---|---|
| `candidate_backend=auto` elige `turbovec` sin `.tvim` usable | SA-1 | SA-2, SA-9 |
| VecQuant no demuestra hits dense reales | SA-2 | SA-1, SA-9 |
| `embed_summaries` re-embebe summaries de colección | SA-3 | SA-9 |
| Visual indexing corre para TXT | SA-4 | SA-6, SA-9 |
| Qdrant visual marca éxito pero `pages_visual` queda vacío | SA-4 | SA-8 |
| `/collections` muestra `COLA 0` con jobs pendientes | SA-6 | SA-5, SA-7 |
| No hay import session durable | SA-5 | SA-6 |
| Carga masiva lanza demasiados uploads concurrentes | SA-6 | SA-5 |
| SQLite `database is locked` | SA-7 | SA-8 |
| Qdrant orphans / storage desalineado | SA-8 | SA-9 |
| Docs contradicen runtime | SA-9 | Todos |

## 8. Criterios de no regresión

Añadir tests o checks para impedir que reaparezcan estos estados:

1. `auto` con `turbovec` instalado y `.tvim` ausente debe usar `purepy`.
2. `auto` con `.tvim` stale debe usar `purepy` o reconstruir antes de usar.
3. `embed_summaries` no puede cargar todos los collection summaries en cada documento.
4. TXT/plain no puede encolar visual indexing por defecto.
5. `/collections` debe mostrar jobs reales si existen pending/running.
6. Importación masiva debe crear sesión durable.
7. Con SQLite no deben correr múltiples workers efectivos.
8. Cleanup debe borrar Qdrant collections del corpus.

## 9. Métricas obligatorias

Registrar y exponer:

- documentos descubiertos por import session;
- documentos creados;
- duplicados por checksum;
- omitidos por tipo;
- fallos por tipo;
- jobs pending/running/failed por colección;
- duración p50/p95 por stage;
- embeddings generados por stage;
- fallback embeddings true/false;
- candidate backend usado por query;
- dense hits por query;
- dense latency p50/p95;
- Qdrant upsert failures;
- stale jobs recuperados.

## 10. Orden recomendado de implementación inmediata

1. SA-1: arreglar `candidate_backend=auto`.
2. SA-3: eliminar coste cuadrático de summaries.
3. SA-4: desactivar visual indexing para TXT/plain.
4. SA-7: proteger SQLite/worker.
5. SA-5: import sessions durables.
6. SA-6: `/collections` con estado real.
7. SA-8: cleanup/Qdrant consistency.
8. SA-2: métricas y benchmark VecQuant.
9. SA-9: validación final y docs.

La razón de este orden es práctica: primero se detiene el trabajo inútil y las rutas
muertas; luego se hace observable; al final se mide y documenta.

## 11. Definición de "funciona al completo"

El sistema se considera corregido cuando una carga de prueba de al menos 500 TXT con
duplicados conocidos cumple:

- la import session explica exactamente el total físico vs documentos únicos;
- no aparecen locks SQLite si se usa modo SQLite protegido;
- no se encola visual indexing para TXT;
- `embed_summaries` mantiene crecimiento lineal;
- `/collections` muestra cola real durante la ejecución;
- Qdrant queda alineado con SQL al finalizar;
- una query posterior usa VecQuant dense o reporta fallback explícito;
- tests backend/frontend pasan;
- docs quedan alineados con el comportamiento observado.

