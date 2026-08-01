# `atenex-context` Operations

Estado: **Implemented**. Los comandos siguientes existen en el entry point
`atenex-context`.

Para las rutas, servicios systemd/Docker, puertos y comandos exactos de la estación
Linux actual, consultar [runbook-local.md](runbook-local.md). Este documento conserva
el contrato operativo portable; el runbook es el procedimiento específico de la PC.

## Modelo operativo

Un proceso se liga a un root canónico y un sidecar. El core requiere Python y SQLite
FTS5; no requiere FastAPI, PostgreSQL, Qdrant, Ollama, GPU ni frontend. Indexar es una
acción explícita del operador o del launcher local antes de iniciar MCP. Ninguna
herramienta MCP reconstruye el índice durante una conversación.

## Instalar

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,repo-context]"
```

Python 3.12 es el runtime canónico. `repo-context` instala el SDK MCP y el adapter
opcional Tree-sitter. El core también funciona sin ese extra salvo `serve`.

La estación Linux verificada el 2026-07-30 usa, sin modificar el Python del
sistema, un runtime portable Python 3.11 bajo `backend/.venv-context-runtime/` y un
venv bajo `backend/.venv-context/`; ambos están ignorados por Git. El paquete base
se verificó con una firma válida de CachyOS. Esta excepción operativa no cambia el
objetivo canónico Python 3.12 del proyecto.

Tree-sitter solo utiliza gramáticas ya presentes. Ejemplo de preparación explícita
de un caché local:

```bash
python -c "import tree_sitter_language_pack as p; p.configure(p.PackConfig(cache_dir='/ruta/al/cache')); p.prefetch(['typescript','tsx','javascript','java','sql'])"
export ATENEX_TREE_SITTER_CACHE_DIR=/ruta/al/cache
```

La preparación puede usar red; `index` nunca descarga. Sin una gramática, se usa el
parser conservador y se registra `tree_sitter_unavailable`.

## Construir y consultar

```bash
atenex-context index --repo PATH [--data-dir PATH] [--full] [--json]
atenex-context status --repo PATH [--data-dir PATH] [--json]
atenex-context doctor --repo PATH [--data-dir PATH] [--json]

atenex-context overview --repo PATH [--focus TEXTO] [--max-tokens N] [--json]
atenex-context search --repo PATH QUERY [--mode MODO] [--top-k N] [--json]
atenex-context symbol --repo PATH SIMBOLO_O_RUTA [--no-source] [--json]
atenex-context trace --repo PATH SIMBOLO --direction DIRECCION [--depth N] [--json]
atenex-context impact --repo PATH SIMBOLO_O_RUTA [--depth N] [--json]
atenex-context tests --repo PATH SIMBOLO_O_RUTA [--top-k N] [--json]
```

`--mode` puede repetirse con `lexical`, `symbol` o `semantic`. `trace --direction`
acepta `callers`, `callees`, `dependencies` y `dependents`. Las consultas aceptan
`--max-tokens` entre 128 y 32 000; el valor predeterminado es 4 000.

La ubicación predeterminada es:

```text
PATH/.atenex/context/index.sqlite3
```

`--data-dir` puede apuntar fuera del repositorio y resulta especialmente útil para
aceptación o índices privados. Un sidecar se liga al root absoluto canónico; no debe
compartirse entre roots.

Si el snapshot completo coincide con la generación activa, el run normal termina sin
publicar otra generación. Cuando hay cambios reutiliza artefactos solo si coinciden
ruta, SHA-256 y fingerprint del parser. `--full` omite el no-op y vuelve a extraer
todo. Si el worktree cambia antes de activar, la transacción se revierte y la
generación anterior permanece.

## Estado y diagnóstico

`status` vuelve a escanear el root y muestra:

- identidad/ruta del repositorio y sidecar;
- generación, schema, `HEAD` y fingerprint indexados;
- `HEAD` y fingerprint actuales;
- `stale`, disponibilidad core/semántica, conteos y diagnósticos.

`doctor` no repara ni instala. Comprueba root, FTS5, binding/generación activa,
presencia del SDK MCP, disponibilidad semántica y cobertura declarada por el
registry de extractores. `healthy` considera solo checks requeridos;
`serve_available` requiere además el SDK MCP.

Si `stale=true`, ejecutar de nuevo `index`. Si aparece
`REPOSITORY_BINDING_MISMATCH`, elegir otro `--data-dir` o reconstruir el sidecar
correcto. Un sidecar ausente/corrupto no se crea como efecto de una consulta.

## Servir MCP

```bash
atenex-context serve --repo PATH [--data-dir PATH] --transport stdio
```

En esta estación, Claude Desktop/Code y Cursor usan el launcher persistente:

```bash
backend/scripts/serve_repo_context_mcp.sh PATH [EXPECTED_CHECKOUT]
```

El launcher resuelve el root, ejecuta una actualización incremental y después
reemplaza el proceso con el servidor `stdio`. No imprime la indexación por stdout.
Cuando Claude crea un worktree, el argumento `.` liga el proceso a ese worktree y el
segundo argumento identifica el checkout principal esperado. El launcher compara los
`git-common-dir`: permite worktrees del mismo repositorio y rechaza otro `cwd` antes de
indexar. Por eso `.` no se admite sin `EXPECTED_CHECKOUT` y el launcher no debe
registrarse globalmente con un root relativo. El sidecar derivado queda bajo
`INSTALL_ROOT/.atenex/context/repositories/HASH_DEL_ROOT/`; así no ensucia el
worktree ni comparte una base ligada a otro root. El checkout principal conserva
`INSTALL_ROOT/.atenex/context/index.sqlite3`. El runtime y las gramáticas son
compartidos desde la instalación principal; se pueden reubicar con las variables
`ATENEX_CONTEXT_INSTALL_ROOT`, `ATENEX_CONTEXT_RUNTIME_ROOT`,
`ATENEX_CONTEXT_PYTHON`, `ATENEX_CONTEXT_TREE_SITTER_CACHE` y
`ATENEX_CONTEXT_SOURCE_ROOT`.

El servidor valida una generación activa antes de iniciar y registra exactamente:

```text
repo_overview
search_repo
get_symbol
trace_symbol
analyze_impact
related_tests
```

Stdout pertenece al protocolo; los errores de proceso se escriben en stderr. El root
no forma parte de los argumentos de herramientas y no puede cambiar durante el
proceso. El contrato completo está en [mcp-tools.md](mcp-tools.md).

La política reusable para agentes está en
`.agents/skills/atenex-repo-context/SKILL.md`; Claude carga el adaptador de
`.claude/skills/atenex-repo-context/SKILL.md`. La skill no reemplaza `AGENTS.md`:
describe cómo comprobar calidad de recuperación y cuándo ampliar una consulta.

## Semántica opcional

```bash
export ATENEX_REPO_CONTEXT_SEMANTIC=1
export ATENEX_REPO_CONTEXT_OLLAMA_URL=http://127.0.0.1:11434
export ATENEX_REPO_CONTEXT_EMBEDDING_MODEL=embeddinggemma
export ATENEX_REPO_CONTEXT_QDRANT_URL=http://127.0.0.1:6333

atenex-context index --repo PATH
```

La indexación publica primero el core SQLite. Después intenta embeddings y Qdrant.
El JSON de `index` muestra `semantic.state=ready` o `degraded`. Solo una proyección
finalizada y compatible se usa en consultas futuras. Un fallo de proveedor conserva
la generación lexical/estructural y `search --mode semantic` devuelve esa
degradación explícitamente.

No existe adapter de reranker configurado en esta versión.

## Evaluación

```bash
cd backend
python -m unittest discover -s tests/repo_context -p "test_*.py" -v
python -m ruff check atenex_nova/repo_context tests/repo_context \
  scripts/evaluate_repo_context.py
python -m mypy atenex_nova/repo_context
```

El runner gold está documentado en
[evaluation-repo-context.md](evaluation-repo-context.md). Para no modificar el
repositorio evaluado, pase un `--data-dir ID=PATH` externo.

## Limpieza segura

El índice es derivado. Con servidores detenidos:

1. resolver el root y el `--data-dir` exactos;
2. comprobar que la ruta termina en el directorio sidecar esperado y no es un
   symlink;
3. mover o eliminar únicamente ese directorio;
4. ejecutar `index` para reconstruir.

No hay comando de borrado ni herramienta MCP destructiva. Las colecciones Qdrant se
separan por repository/generation, pero su limpieza automática no forma parte de v1.
