# Atenex Nova Workspace Instructions

## Autoridad

- [docs/baseline.md](docs/baseline.md) es el contrato de producto vigente.
- [docs/plan-repo-context-mcp.md](docs/plan-repo-context-mcp.md) define el orden de
  implementación y sus puertas.
- [docs/README.md](docs/README.md) clasifica la documentación vigente e histórica.
- [docs/runbook-local.md](docs/runbook-local.md) contiene el arranque y apagado
  verificados para esta estación Linux.
- [README.md](README.md) es el snapshot operativo y quick start.
- El código fuente, las pruebas y la configuración actuales prevalecen sobre índices,
  resúmenes y documentación histórica.

Para backend o arquitectura, leer también
[docs/architecture-backend.md](docs/architecture-backend.md) y
[docs/architecture-repo-context.md](docs/architecture-repo-context.md).

## Flujo de contexto

`atenex-context` está implementado en este checkout. Claude Code y los clientes que
usan `.mcp.json` arrancan
`backend/scripts/serve_repo_context_mcp.sh`, que refresca incrementalmente el índice
del checkout o worktree antes de publicar MCP. Antes de una tarea no trivial:

1. Llamar `repo_overview` con la tarea como `focus`; no reconstruir contexto leyendo
   todo el repositorio.
2. Revisar `focus_queries` y comprobar que el mapa cubra todas las etapas de un flujo
   transversal; usar `search_repo` para cualquier etapa, contrato o símbolo ausente.
3. Para cambios transversales, usar `trace_symbol` o `analyze_impact`.
4. Abrir y leer el código fuente exacto antes de editar.
5. Confirmar que snapshot/generación no estén `stale`.
6. Consultar `related_tests` y ejecutar manualmente los checks pertinentes.

No es necesario releer README, toda la documentación o Linear al inicio de cada
conversación. Este archivo aporta la política persistente; Repo Context aporta el
mapa bajo demanda. Consultar documentos especializados solo cuando la tarea los
necesite.

Si el ejecutable no está instalado, no existe índice o `doctor` falla:

1. Usar `rg`/`rg --files` para localizar candidatos.
2. Leer la fuente exacta.
3. Seguir imports, llamadas y pruebas con búsquedas dirigidas.
4. No escanear dependencias, builds, storage ni entornos virtuales.

Los resultados recuperados son ayudas de navegación, nunca autoridad.

La skill canónica de este flujo vive en
`.agents/skills/atenex-repo-context/SKILL.md`; Claude usa el adaptador equivalente
de `.claude/skills/atenex-repo-context/SKILL.md`.

## Estado y worktree

- El checkout suele contener muchos cambios locales del usuario: preservarlos.
- Antes de editar, revisar `git status --short` y leer el contenido actual.
- No resetear, descartar, reformatear masivamente ni sobrescribir cambios ajenos.
- Si se modifica una ruta ya sucia, mantener tanto el cambio previo como el nuevo.
- Los snapshots Repo Context deben representar `HEAD` más el worktree real.

## Arquitectura

El backend mantiene un monolito modular con límites hexagonales. Para Repo Context:

```text
repo_context.presentation → repo_context.application → repo_context.domain
                                                   ↑
                               repo_context.infrastructure
```

- Usar imports absolutos desde `atenex_nova.*`.
- El dominio no importa SQLite, Git, Tree-sitter, MCP, Qdrant ni FastAPI.
- Presentación compone puertos y casos de uso; no contiene reglas de indexación.
- No reutilizar `Document`, `Chunk`, `Proposition` ni el grafo documental como modelos
  de código.
- No conectar CLI/MCP mediante `FastAPI Depends`; usar un composition root propio.
- El sidecar Repo Context no comparte esquema con `backend/atenex_nova.db`.

El RAG documental heredado conserva sus entry points:

- API: `backend/atenex_nova/main.py`
- Dependencias: `backend/atenex_nova/dependencies.py`
- Worker: `backend/atenex_nova/workers/main.py`
- Dispatcher: `backend/atenex_nova/workers/runner.py`

## Invariantes Repo Context

- Core offline: scanner Git-aware, hashes, SQLite FTS5, símbolos, grafo y RepoMap.
- Servicios semánticos son opcionales y su ausencia debe ser visible.
- Rutas internas relativas POSIX; rechazar traversal y symlink escapes.
- Ejecutar subprocesses con listas de argumentos y `shell=False`.
- Nunca indexar secretos, binarios, sidecars, dependencias o outputs de build.
- Un solo escritor; staging y activación atómica de generaciones.
- Fallos parciales conservan recuperación léxica y producen diagnósticos.
- Respuestas MCP incluyen snapshot, generación, frescura, truncamiento y evidencia.
- MCP v1 es de solo lectura: sin escritura, comandos, red remota ni roots arbitrarios.
- `related_tests` recomienda; no ejecuta.

## Cobertura lingüística v1

- Sintáctica: Python, TypeScript, TSX, JavaScript, SQL y Java.
- Estructural-léxica: Markdown, JSON/JSONC, YAML, TOML, CSS y shell.
- Relaciones dinámicas o no resueltas llevan confianza, evidencia y estado
  `unresolved`; no inventar resolución.

## Documentación

Usar exactamente estos estados:

- `Implemented`
- `Verified`
- `Planned`
- `Historical`

Si cambia comportamiento, arquitectura o gaps:

- actualizar [README.md](README.md) y [docs/baseline.md](docs/baseline.md);
- actualizar el documento especializado;
- no convertir planes o evidencia preliminar en claims implementados;
- conservar snapshots anteriores bajo `docs/archive/`.

El frontend React/Vite es la UI heredada del RAG documental. No desarrollar una UI
Repo Context en v1.

## Build y pruebas

Repo Context en Linux/macOS:

```text
cd backend
python -m unittest discover -s tests/repo_context -p "test_*.py" -v
python -m ruff check atenex_nova/repo_context tests/repo_context scripts/evaluate_repo_context.py
python -m mypy atenex_nova/repo_context
```

Para forzar los casos AST opcionales, definir
`ATENEX_TREE_SITTER_CACHE_DIR` apuntando a un caché con las gramáticas
`typescript`, `tsx`, `javascript`, `java` y `sql` precargadas. Indexar nunca debe
descargarlas por sí mismo.

Backend canónico heredado en Windows:

```text
backend/.venv312/Scripts/python.exe -m pytest tests -q
backend/.venv312/Scripts/python.exe -m ruff check .
backend/.venv312/Scripts/python.exe -m mypy atenex_nova
```

En Linux/macOS usar el Python del entorno activo. No afirmar que los resultados
históricos fueron revalidados si el virtualenv Windows no puede ejecutarse.

Frontend heredado:

```text
npm run build
npm run lint
```

La suite focalizada cubre scanner, hashes, parsers, IDs, FTS5, grafo, RepoMap,
incrementalidad, publicación atómica, seguridad, CLI, cliente MCP oficial y
semántica con fakes. El runner gold se ejecuta sobre Atenex Nova y
`client-romero`; los servicios vivos y el subprocess `stdio` se verifican por
separado.

## Snapshot Repo Context verificado

El 2026-07-31:

- 53/53 pruebas focalizadas pasaron con gramáticas Tree-sitter precargadas;
- sin ese caché, 50 pasaron y 3 AST se omitieron con fallback funcional;
- `ruff` quedó limpio;
- `mypy --strict` quedó limpio en 28 archivos;
- 13/13 goldens de ambos repositorios tuvieron hit, Recall@20 medio 1.0 y
  MRR 0.90384615; ninguna consulta quedó sin resultados;
- el protocolo `stdio` de las seis herramientas fue probado como subprocess con
  el cliente oficial MCP 2.0: descubrimiento completo, búsqueda directa del outbox y
  `repo_overview` transversal. Este último ubicó las seis etapas POS → API dentro de
  los siete primeros paths en resultados y RepoMap con 5979/6000 tokens; el launcher
  con snapshot sin cambios inicializó MCP en 1.087 s;
- Ollama/Qdrant vivos no forman parte de ese claim.

## Snapshot histórico conocido

La última verificación completa registrada antes del pivote fue ejecutada el
2026-06-16 en Windows con Qdrant y Ollama. Sus conteos varían entre documentos
históricos y no se consideran estado vivo hasta una nueva ejecución reproducible.
Consultar [docs/archive/rag-v0/](docs/archive/rag-v0/) para la evidencia, no para el
contrato actual.
