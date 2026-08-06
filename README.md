# Atenex Nova

**Motor local de contexto verificable para repositorios grandes.**

La primera versión usable es `atenex-context`: cataloga el worktree actual,
construye un índice incremental local y expone seis consultas de solo lectura por
CLI y MCP. Combina búsqueda literal/FTS5, símbolos, relaciones estáticas y un
RepoMap acotado. Cada runtime MCP requiere Ollama, Qdrant y una proyección semántica
compatible con la generación SQLite activa; la búsqueda híbrida es el modo normal.

El RAG documental anterior se conserva como subsistema histórico; su API FastAPI y
su frontend no son requisitos del nuevo core.

## Estado verificado

| Capacidad | Estado | Evidencia vigente |
|---|---|---|
| Scanner Git/worktree y políticas de seguridad | **Implemented / Verified** | pruebas de tracked/untracked, secretos, binarios, tamaño, traversal y symlinks |
| SQLite FTS5 incremental y generaciones atómicas | **Implemented / Verified** | no-op para snapshot idéntico, activación transaccional, recuperación natural estricta/relajada y rechazo de snapshot cambiante |
| Publicación single-writer por sidecar | **Implemented / Verified** | lock advisory cubre generación SQLite y proyección semántica; una prueba concurrente confirma un solo escritor activo |
| Parsers, símbolos, grafo y RepoMap | **Implemented / Verified** | Python AST; Tree-sitter opcional para TS/TSX/JS/Java/SQL; fallback diagnosticado |
| CLI `atenex-context` | **Implemented / Verified** | indexación, estado, doctor y seis consultas |
| MCP de seis herramientas | **Implemented / Verified** | descubrimiento y llamada con cliente oficial MCP 2.0 |
| Transporte MCP `stdio` | **Implemented / Verified** | subprocess real: inicialización, seis schemas y `repo_overview` sin error |
| Ollama + Qdrant + RRF | **Implemented / Verified** | proyección requerida y búsqueda híbrida verificadas con servicios vivos el 2026-08-03 en Atenex Nova y `client-romero` |
| Reranker concreto | **Planned** | existe el puerto y la coordinación, no un adapter configurado para Repo Context |
| RAG documental mantenido | **Implemented / Verified** | correcciones de ingesta, retrieval, memoria, síntesis, verificación y UI respaldadas por tests focalizados; rebuild limpio, benchmark humano y runtime completo siguen **Planned** |

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

Verificación del contrato semántico requerido (2026-08-03):

- 59/59 pruebas Repo Context pasaron con gramáticas Tree-sitter precargadas; `ruff`
  y `mypy` quedaron limpios.
- Atenex Nova publicó la generación 18 con 396 archivos, 1.672 chunks y
  `ollama:embeddinggemma`; una segunda indexación reutilizó el sentinel compatible.
- `search_repo` sin `modes` devolvió `lexical`, `symbol` y `semantic`; el foco de
  `repo_overview` incluyó resultados con evidencia semántica.
- Un subprocess con el cliente oficial MCP, launcher global `.` y
  `cwd=client-romero` devolvió `repo.name=client-romero`, generación 10, 793 archivos,
  2.837 chunks, las seis herramientas y foco semántico. No sirvió el índice de Atenex.
- El registro global de Codex quedó con argumento `.` y
  `startup_timeout_sec=900`; las conversaciones ya abiertas deben reiniciar MCP o
  abrir un chat nuevo para tomar la configuración.

Corrección y revalidación del launcher (2026-08-04):

- 60/60 pruebas Repo Context pasaron con las cinco gramáticas Tree-sitter reales;
  `ruff` y `mypy` quedaron limpios.
- La publicación SQLite + semántica quedó serializada por un lock advisory de
  proceso por sidecar.
- El cliente MCP oficial arrancado con `cwd=client-romero` publicó generación 13 no
  obsoleta, seis herramientas y `repo.name=client-romero`.
- `trace_symbol` expuso `both` en su schema y `analyze_impact` resolvió por path
  exacto `apps/store/src/stores/syncStore.ts`, conservándolo en `affected_files`
  incluso tras compactar la respuesta.

Cierre verificable del checkout (2026-08-05):

- Repo Context descubrió 60 pruebas: 57 pasaron y 3 se omitieron porque el entorno
  Linux nuevo no tenía las gramáticas Tree-sitter precargadas; el test con el cliente
  MCP oficial sí pasó. Ruff quedó limpio y MyPy no encontró errores en sus 29
  archivos.
- El backend completo quedó limpio en Ruff y MyPy (`195` archivos). La suite general
  obtuvo 269 pruebas pasadas, 3 omitidas y 11 fallidas por condiciones del runtime
  vivo: el entorno `dev,repo-context` no incluye `torch`/reranker y la colección
  Qdrant `pages_visual` conserva un schema anterior que el guard vigente rechaza.
  No se borró ni reconstruyó esa colección durante la validación.
- El frontend pasó 3/3 pruebas de presentación de confianza, lint y build Vite.
- Estos resultados verifican el checkout y sus caminos herméticos; el stack
  documental vivo completo continúa **Planned** hasta instalar el extra ML y
  reconstruir las colecciones incompatibles siguiendo el runbook.

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

Snapshot diagnóstico del RAG documental (2026-08-02, **Historical** respecto del
checkout corregido):

- La colección estable auditada tenía 1.754 documentos `ready`, 3 `failed`, 3.018
  chunks y 788.945 propositions. Los 1.754 documentos listos conservaban algún job
  pendiente o activo; `READY` no equivale a enriquecimiento completo.
- 952 chunks excedían el contexto 2.048 de EmbeddingGemma. El 80,59 % de los tokens
  estimados estaba después de esa posición dentro de sus respectivos chunks, por lo
  que la representación densa no puede cubrir íntegramente las transcripciones.
- Las filas `collection_summary` se crean una por documento mediante selección
  extractiva; no constituyen una síntesis del corpus. Ningún summary tenía vector
  activo en el snapshot.
- Qdrant exponía solo propositions sparse. El candidate index PurePy puntuaba todos
  los códigos cuantizados y `score_propositions` consumió 48–69 s en los ensayos
  controlados.
- La pregunta exacta del usuario sobre eutanasia quedó `unverified` y Atenex afirmó
  que no había evidencia directa, aunque 22 documentos contenían `eutanasia` y una
  transcripción desarrollaba la respuesta. Forzar `global` repitió el falso negativo.

Remediación en el checkout actual:

- **Implemented / Verified** en pruebas focalizadas: allowlist de corpus; parsing de
  transcripciones con timestamps, offsets y metadata estructural; chunking con hard
  cap de 800 tokens y overlap de 80; prefijos separados query/documento; fingerprint
  `emb-v2`; carga lazy de Docling para TXT; lotes Ollama/Qdrant acotados e
  idempotentes; dense primario en Qdrant con validación de schema; lock SQLite
  recuperable tras crashes; paginación completa; contexto conversacional;
  multi-query determinista con RRF y corrección conservadora de `eutanacia`.
- **Implemented / Verified** en pruebas focalizadas: summaries de sección y documento
  con procedencia, construcción explícita de una memoria de colección, barrera
  temporal de readiness, síntesis map-reduce acotada, auditoría por claims, payload de
  evidencia compacto y avisos de confianza en la UI.
- **Implemented / Verified** en runtime vivo: transporte OpenAI-compatible opcional
  para las mismas pesas BF16 de EmbeddingGemma, servidor CUDA dedicado y SPLADE
  persistido por lotes. En la RTX 4060, el tramo de proposiciones pasó de 13,3/s a
  102,7/s end-to-end sin retirar el título contextual ni cambiar el fingerprint.
- **Implemented / Verified** en pruebas focalizadas: publicación fail-closed durante
  rebuild o estados transitorios; exclusión visible de documentos fallidos;
  revalidación y rehidratación de toda evidencia desde SQL; y limpieza simétrica e
  idempotente de SQL, Qdrant, candidate indexes, aristas y artefactos visuales.
- **Planned** antes de atribuir calidad al runtime: `generation_id` y activación
  atómica definitivos en todas las capas, rebuild limpio vivo, benchmark Jesús G de
  150 preguntas con revisión humana, reranker vivo calibrado, grafo cross-document y
  comparación controlada con NotebookLM/EOS.

Las pruebas demuestran comportamiento del código; no revalidan el índice de Jesús G
creado con el contrato de embeddings anterior. Ese índice debe reconstruirse antes de
una evaluación de calidad o de volver a declarar el stack documental **Verified** en
runtime vivo.

Verificación consolidada del checkout documental (2026-08-02, Ollama y Qdrant vivos;
las colecciones efímeras de prueba se retiraron antes del rebuild real):

- La ejecución conjunta de `backend/tests` terminó con 261 pruebas pasadas, 3
  omitidas por capacidades opcionales y 4 subtests pasados.
- Los extras ML, Docling, TurboVec, reranker BGE local y faster-whisper quedaron
  instalados sin requisitos rotos (`pip check`).
- `ruff` quedó limpio sobre `atenex_nova` y `tests`; `mypy` quedó limpio en 194
  archivos fuente.
- El frontend pasó 3/3 pruebas, build TypeScript/Vite y lint.
- Repo Context pasó 53 pruebas y omitió 3 AST al no haber gramáticas Tree-sitter
  precargadas; el fallback explícito permaneció funcional.

La verificación anterior usa bases temporales, dobles y degradaciones explícitas; no
es un rebuild ni un benchmark de calidad del corpus vivo.

El dictamen completo, la revisión de tesis/EOS y el contraste SOTA están en
[la auditoría de respuestas](docs/auditoria-rag-respuestas-sota-2026-08-02.md). Las
entregas y brechas se registran sin cerrar prematuramente G0–G6 en el
[ledger de síntesis de corpus](docs/plan-rag-sintesis-corpus.md).

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

Las consultas naturales del MCP usan recuperación híbrida requerida. La señal
léxica/estructural intenta coincidencia estricta y luego relajada, usa prefijos y un
vocabulario bilingüe acotado; la señal semántica aporta recuperación conceptual y la
fusión diversifica archivos/módulos. Los warnings persistentes del índice se
consultan con `status`/`doctor`; una búsqueda solo transporta diagnósticos pertinentes
a esa respuesta.

La skill canónica `.agents/skills/atenex-repo-context/SKILL.md` formaliza este
flujo y sus controles de calidad para Codex. Claude dispone del adaptador equivalente
en `.claude/skills/atenex-repo-context/SKILL.md`.

## Configuración de clientes

El repositorio incluye `.mcp.json` y `.cursor/mcp.json`. En esta estación ambos
usan `backend/scripts/serve_repo_context_mcp.sh`: actualiza incrementalmente el
índice del checkout/worktree y arranca el servidor con rutas absolutas, sin depender
del `PATH` limitado de una aplicación gráfica.

Configuración de proyecto conceptual equivalente (restringida a este checkout y sus
worktrees):

```toml
[mcp_servers.repo_context]
command = "/usr/bin/bash"
args = [
  "/ruta/Atenex_nova/backend/scripts/serve_repo_context_mcp.sh",
  ".",
  "/ruta/al/checkout/principal"
]
```

Para Claude Code, `.mcp.json` es suficiente. La aprobación del servidor de proyecto
es una decisión local de seguridad del cliente y no se guarda en Git:

```bash
claude mcp list
```

El tercer argumento identifica el checkout principal esperado; el launcher acepta sus
worktrees Git, pero rechaza cualquier repositorio diferente antes de indexar o
publicar herramientas. Codex, que mantiene MCP de usuario, usa en cambio un único
registro con `.`: el proceso hereda el directorio de la sesión y el launcher lo valida
como checkout Git antes de crear un sidecar separado por root.

Claude Desktop en la pestaña **Code** comparte `.mcp.json`, `CLAUDE.md` y la
configuración de Claude Code. Seleccione ambiente **Local** y esta carpeta como
proyecto. La pestaña **Chat** usa una configuración MCP separada.

## Semántica requerida

```bash
export ATENEX_REPO_CONTEXT_OLLAMA_URL=http://127.0.0.1:11434
export ATENEX_REPO_CONTEXT_EMBEDDING_MODEL=embeddinggemma
export ATENEX_REPO_CONTEXT_QDRANT_URL=http://127.0.0.1:6333

atenex-context index --repo ..
atenex-context search --repo .. "validación de acceso" \
  --mode lexical --mode symbol --mode semantic --json
```

SQLite sigue siendo la autoridad de fuente y snapshot. El launcher solo publica MCP
si el sentinel semántico coincide con repositorio, generación y modelo. `search_repo`
y el foco de `repo_overview` usan recuperación híbrida por defecto; una proyección
ausente o incompatible falla explícitamente con `SEMANTIC_UNAVAILABLE`.

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
- [Auditoría integral del RAG y respuestas](docs/auditoria-rag-respuestas-sota-2026-08-02.md)
- [Plan de reconstrucción hacia síntesis de corpus](docs/plan-rag-sintesis-corpus.md)
- [Mapa documental](docs/README.md)

El código, las pruebas y la configuración actuales son la autoridad final. El
histórico del RAG documental está en `docs/archive/rag-v0/`.

Nota operativa del RAG documental: el adapter de respuestas Ollama usa
`think=false` para que Gemma 4 entregue texto visible dentro del presupuesto de
generación; Atenex sigue realizando recuperación y verificación por separado. Los
marcadores heurísticos de ruta se comparan como palabras o frases completas para
evitar falsos modos visuales por subcadenas como `table` dentro de `establece`. La
vista de consulta reconcilia el chat después de una interrupción HTTP: mantiene el
turno pendiente y recupera la respuesta persistida en vez de ocultarla.
El idioma explícito de la colección prevalece sobre la detección heurística; para
`Jesus G`, prompts, reparaciones y respuestas son exclusivamente en español. La
recuperación incorpora el referente conversacional solo en follow-ups, pagina todo
el corpus y limita la expansión multi-query. El pack prioriza relevancia y cobertura
documental; los planes complejos ejecutan map-reduce real. El verificador audita
claims y sus citas sin permitir que la revisión LLM infle el score determinista. La
API compacta metadata sensible/voluminosa y la UI hace visible un verdict no
verificado. Un índice construido antes de `emb-v2` es incompatible y no debe usarse
para evaluar estas mejoras.
