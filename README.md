# Atenex Nova

**Motor local de contexto verificable para repositorios grandes.**

La primera versión usable es `atenex-context`: cataloga el worktree actual,
construye un índice incremental local y expone seis consultas de solo lectura por
CLI y MCP. Combina búsqueda literal/FTS5, símbolos, relaciones estáticas y un
RepoMap acotado. Ollama, Qdrant y la recuperación semántica son opcionales.

El RAG documental anterior se conserva como subsistema histórico; su API FastAPI y
su frontend no son requisitos del nuevo core.

## Estado verificado

| Capacidad | Estado | Evidencia del 2026-07-31 |
|---|---|---|
| Scanner Git/worktree y políticas de seguridad | **Implemented / Verified** | pruebas de tracked/untracked, secretos, binarios, tamaño, traversal y symlinks |
| SQLite FTS5 incremental y generaciones atómicas | **Implemented / Verified** | no-op para snapshot idéntico, activación transaccional, recuperación natural estricta/relajada y rechazo de snapshot cambiante |
| Parsers, símbolos, grafo y RepoMap | **Implemented / Verified** | Python AST; Tree-sitter opcional para TS/TSX/JS/Java/SQL; fallback diagnosticado |
| CLI `atenex-context` | **Implemented / Verified** | indexación, estado, doctor y seis consultas |
| MCP de seis herramientas | **Implemented / Verified** | descubrimiento y llamada con cliente oficial MCP 2.0 |
| Transporte MCP `stdio` | **Implemented / Verified** | subprocess real: inicialización, seis schemas y `repo_overview` sin error |
| Ollama + Qdrant + RRF | **Implemented / Optional** | contratos, namespace, sentinel de completitud, degradación y fusión verificados con fakes; proveedores vivos no revalidados |
| Reranker concreto | **Planned / Optional** | existe el puerto y la coordinación, no un adapter configurado |
| RAG documental heredado | **Historical / Maintained** | evidencia anterior archivada; no fue revalidado en esta entrega |

Verificación focalizada:

- 53 pruebas Repo Context: 53 pasaron con gramáticas precargadas.
- Sin caché Tree-sitter: 50 pasaron y 3 se omitieron; el fallback conservador siguió
  funcionando.
- `ruff`: 0 incidencias en el bounded context, su runner y pruebas.
- `mypy --strict`: 0 errores en 28 archivos del bounded context.
- Aceptación core sobre Atenex Nova y `client-romero`: 13/13 consultas con hit,
  Recall@20 medio 1.0 y MRR 0.90384615; cero consultas sin resultados.
- Índices de aceptación: Atenex 362 archivos/3508 símbolos/14532 relaciones;
  `client-romero` 816/11997/37049. Los conteos dependen del snapshot.
- Claude Code 2.1.220: `repo-context` figura `✔ Connected`; el cliente MCP 2.0
  ejecutó `repo_overview` y `search_repo` por el launcher persistente. La búsqueda
  léxica recuperó las tres etapas locales del outbox en 20 resultados y 3874 tokens.
  El overview transversal recuperó las seis etapas POS → API entre sus primeros siete
  paths tanto en `focus_results` como en RepoMap, con 5979/6000 tokens; con el índice
  vigente, MCP inicializó en 1.087 s.

Estas cifras no revalidan las suites completas del RAG o del frontend.

Verificación focalizada del RAG documental heredado (2026-07-31):

- 38 pruebas unitarias de routing, planificación, presupuesto de contexto, pasajes,
  BM25, citas y grounding pasaron; `ruff` quedó limpio en las rutas tocadas.
- La colección viva `Jesus G` (1757 documentos, perfil `es`) respondió en español a
  las dos consultas reportadas. `el dinero es enemigo del amor?` siguió
  `factual_local → direct_answer`, usó 8 evidencias y resolvió 3/3 marcadores; la
  respuesta quedó `verified` con grounding conservador 0.707.
- `Como se diferencia un enamorado de un imbecil?` siguió
  `multi_hop → hierarchical_synthesis`, usó 10 evidencias y resolvió 5/5
  marcadores; quedó `verified` con grounding 0.731. Esta es evidencia puntual, no
  una revalidación completa del RAG histórico.

## Instalación y primer índice

Para arrancar o detener rápidamente esta estación, usar primero el
[runbook local](docs/runbook-local.md). Distingue el MCP mínimo del stack documental
completo y contiene las rutas, puertos, verificaciones y apagado seguro de esta PC.

Python 3.12 es el runtime canónico:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,repo-context]"

atenex-context index --repo ..
atenex-context doctor --repo .. --json
atenex-context overview --repo .. --focus "arquitectura de recuperación"
```

En Windows, activar el entorno correspondiente y usar
`backend/.venv312/Scripts/python.exe`.

El core no necesita red ni servicios. Si `tree-sitter-language-pack` no tiene una
gramática ya precargada, el archivo se procesa con el extractor conservador y deja
un diagnóstico; la indexación nunca descarga gramáticas silenciosamente. Para usar
un caché preparado:

```bash
export ATENEX_TREE_SITTER_CACHE_DIR=/ruta/al/cache
```

La ubicación predeterminada del sidecar es
`.atenex/context/index.sqlite3`. Use `--data-dir PATH` para mantenerlo fuera del
repositorio.

## Consultas

```bash
atenex-context status --repo .. --json
atenex-context search --repo .. "RetrievalOrchestrator" --json
atenex-context symbol --repo .. "RetrievalOrchestrator" --json
atenex-context trace --repo .. "RetrievalOrchestrator" \
  --direction dependents --depth 2 --json
atenex-context impact --repo .. "backend/atenex_nova/main.py" --json
atenex-context tests --repo .. "TokenBudgetPolicy" --json
```

El servidor:

```bash
atenex-context serve --repo .. --transport stdio
```

Herramientas MCP públicas:

```text
repo_overview
search_repo
get_symbol
trace_symbol
analyze_impact
related_tests
```

Cada respuesta contiene la generación, `HEAD`, fingerprint, frescura,
truncamiento, diagnósticos y evidencia con rutas relativas y líneas. La fuente viva
se revalida antes de incluir extractos.

Las consultas naturales no dependen de embeddings: el core intenta coincidencia
estricta y luego relajada, usa prefijos y un vocabulario bilingüe acotado, y
diversifica archivos/módulos. Los warnings persistentes del índice se consultan con
`status`/`doctor`; una búsqueda solo transporta diagnósticos pertinentes a esa
respuesta.

La skill canónica `.agents/skills/atenex-repo-context/SKILL.md` formaliza este
flujo y sus controles de calidad para Codex. Claude dispone del adaptador equivalente
en `.claude/skills/atenex-repo-context/SKILL.md`.

## Configuración de clientes

El repositorio incluye `.mcp.json` y `.cursor/mcp.json`. En esta estación ambos
usan `backend/scripts/serve_repo_context_mcp.sh`: actualiza incrementalmente el
índice del checkout/worktree y arranca el servidor con rutas absolutas, sin depender
del `PATH` limitado de una aplicación gráfica.

Configuración conceptual equivalente:

```toml
[mcp_servers.repo_context]
command = "/usr/bin/bash"
args = ["/ruta/Atenex_nova/backend/scripts/serve_repo_context_mcp.sh", "."]
```

Para Claude Code, `.mcp.json` es suficiente. La aprobación del servidor de proyecto
es una decisión local de seguridad del cliente y no se guarda en Git:

```bash
claude mcp list
```

Claude Desktop en la pestaña **Code** comparte `.mcp.json`, `CLAUDE.md` y la
configuración de Claude Code. Seleccione ambiente **Local** y esta carpeta como
proyecto. La pestaña **Chat** usa una configuración MCP separada.

## Semántica opcional

```bash
export ATENEX_REPO_CONTEXT_SEMANTIC=1
export ATENEX_REPO_CONTEXT_OLLAMA_URL=http://127.0.0.1:11434
export ATENEX_REPO_CONTEXT_EMBEDDING_MODEL=embeddinggemma
export ATENEX_REPO_CONTEXT_QDRANT_URL=http://127.0.0.1:6333

atenex-context index --repo ..
atenex-context search --repo .. "validación de acceso" \
  --mode lexical --mode symbol --mode semantic --json
```

SQLite sigue siendo la autoridad. Una generación semántica se consulta únicamente
si su sentinel de completitud coincide con repositorio, generación y modelo; de lo
contrario la búsqueda degrada explícitamente al core.

## Evaluación reproducible

```bash
cd backend
python -m unittest discover -s tests/repo_context -p "test_*.py" -v
python -m ruff check atenex_nova/repo_context tests/repo_context \
  scripts/evaluate_repo_context.py
python -m mypy atenex_nova/repo_context

python scripts/evaluate_repo_context.py \
  --manifest tests/repo_context/goldens/acceptance.json \
  --repo atenex-nova=.. \
  --repo client-romero=/ruta/local/client-romero \
  --data-dir atenex-nova=/tmp/atenex-context/atenex \
  --data-dir client-romero=/tmp/atenex-context/client \
  --reindex --full --top-k 20
```

El reporte no incluye roots absolutos ni copia fuente privada.

## Documentación

- [Contrato de producto](docs/baseline.md)
- [Arquitectura](docs/architecture-repo-context.md)
- [Indexación y almacenamiento](docs/indexing-and-storage.md)
- [Contrato MCP](docs/mcp-tools.md)
- [Operación](docs/operations.md)
- [Runbook local de esta PC](docs/runbook-local.md)
- [Evaluación](docs/evaluation-repo-context.md)
- [Plan y ledger de ejecución](docs/plan-repo-context-mcp.md)
- [Auditoría contrastiva vigente](docs/auditoria-completa.md)
- [Mapa documental](docs/README.md)

El código, las pruebas y la configuración actuales son la autoridad final. El
histórico del RAG documental está en `docs/archive/rag-v0/`.

Nota operativa del RAG heredado: el adapter de respuestas Ollama usa
`think=false` para que Gemma 4 entregue texto visible dentro del presupuesto de
generación; Atenex sigue realizando recuperación y verificación por separado. Los
marcadores heurísticos de ruta se comparan como palabras o frases completas para
evitar falsos modos visuales por subcadenas como `table` dentro de `establece`. La
vista de consulta reconcilia el chat después de una interrupción HTTP: mantiene el
turno pendiente y recupera la respuesta persistida en vez de ocultarla.
El idioma explícito de la colección prevalece sobre la detección heurística; para
`Jesus G`, prompts, reparaciones y respuestas son exclusivamente en español. La
recuperación léxica tolera vocales sin tilde, selecciona pasajes centrados en la
consulta y no cuenta el texto fuente completo contra el presupuesto si no entra al
prompt. El verificador no puede inflar el score determinista: audita marcadores
simples o agrupados, rechaza relaciones de grafo como citas documentales y registra
en la traza índices inválidos, no citables o sin enlace.
