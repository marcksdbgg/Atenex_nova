# Auditoría técnica contrastiva

Estado: **Implemented / Verified** para el ledger Repo Context actualizado el
2026-07-31.

La auditoría integral anterior del RAG documental se conserva sin reescribir en
[archive/rag-v0/auditoria-completa-2026-06-16.md](archive/rag-v0/auditoria-completa-2026-06-16.md).
Sus resultados son **Historical** y no se mezclan con la verificación actual.

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
- Revalidar por separado la aplicación RAG heredada y el frontend si vuelven a formar
  parte de un release.

## Regla de actualización

Un cambio de contrato, arquitectura o gap debe actualizar conjuntamente:

1. [../README.md](../README.md);
2. [baseline.md](baseline.md);
3. este ledger;
4. el documento especializado y sus pruebas.

`Implemented` afirma existencia; `Verified` requiere evidencia nombrada;
`Planned` es trabajo pendiente; `Historical` nunca describe el runtime vigente.
