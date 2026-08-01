# Repository Context: Indexing and Storage

Estado: **Implemented / Verified** para el core SQLite. La capa semántica es
**Implemented / Optional** y sus proveedores vivos no están incluidos en el claim.

## Invariantes

- La autoridad es el worktree actual: `HEAD` más bytes tracked y untracked no
  ignorados.
- El scanner no ejecuta código, hooks, builds ni gestores de paquetes.
- Una generación solo se activa si una segunda captura conserva repositorio, `HEAD`
  y fingerprint.
- Una consulta devuelve una sola generación o falla cerrada si la activación cambia
  durante la llamada.
- Los extractos se revalidan contra el hash de la fuente viva antes de responder.
- El sidecar está ligado al root canónico; reutilizarlo con otro repositorio falla.
- Los parsers y servicios opcionales degradan por archivo o por señal, con
  diagnóstico explícito.

## Descubrimiento

`GitRepositoryScanner` usa argumentos Git sin shell:

```text
git ls-files --cached --others --exclude-standard -z
git status --porcelain=v1 -z --untracked-files=all
```

Fuera de Git usa una enumeración de filesystem confinada al root. Las rutas públicas
son relativas POSIX. Antes y después de leer se valida inventario, identidad y SHA-256
del archivo; una captura inestable se reintenta de forma acotada o falla.

Política predeterminada:

- máximo 100 000 candidatos y 2 000 000 bytes por archivo;
- excluye `.git`, `.atenex`, venvs, `node_modules`, builds, coverage, caches,
  storage y bases derivadas;
- excluye binarios, extensiones de claves, nombres secretos conocidos y patrones
  de credenciales;
- no sigue symlinks, incluso si apuntan dentro del root; distingue escapes;
- respeta `.gitignore` para archivos no rastreados;
- registra cada exclusión como diagnóstico sin guardar el contenido.

`content_hash`, `content_fingerprint`, `worktree_fingerprint` y `repository_id` son
SHA-256 en hexadecimal minúsculo de 64 caracteres.

## Extracción

| Familia | Implementación |
|---|---|
| Python | AST de la biblioteca estándar; fallback acotado ante sintaxis inválida |
| TypeScript/TSX/JavaScript/Java/SQL | `tree-sitter-language-pack` si la gramática ya está precargada |
| Las cinco familias anteriores sin gramática o con errores | extractor conservador por patrones + diagnóstico |
| Markdown, JSON/JSONC, YAML, TOML, CSS y shell | estructura/léxico conservador |
| Texto no soportado | chunks léxicos acotados |

Indexar nunca descarga una gramática. `ATENEX_TREE_SITTER_CACHE_DIR` selecciona un
caché preparado. La identidad persistida del parser incluye versión de esquema,
tamaños de chunk, versión del paquete y disponibilidad de cada gramática. Cambiar
cualquiera de esas entradas invalida la reutilización incremental.

Los chunks tienen como máximo 80 líneas y 12 000 caracteres por defecto. Símbolos,
chunks y relaciones reciben IDs estables derivados de ruta, hash, span y contenido.
Las relaciones conservan tipo, método, confianza, línea de evidencia y estado
resuelto/no resuelto.

## SQLite

La ubicación predeterminada es:

```text
<repo>/.atenex/context/index.sqlite3
```

`--data-dir` cambia el directorio, no el root fuente. El esquema v1 contiene:

- `metadata`;
- `generations`;
- `files`;
- `chunks`;
- `symbols`;
- `edges`;
- `diagnostics`;
- `search_fts`, una tabla virtual FTS5.

SQLite usa foreign keys, WAL, `synchronous=FULL` y `busy_timeout=30000`. Las lecturas
abren el archivo existente en modo `ro` y `query_only`; una consulta no crea ni migra
un sidecar ausente.

FTS5 indexa path, nombre, qualified name, heading y contenido con `_` como parte del
token. El planificador léxico intenta primero coincidencia por todos los términos y
complementa la lista con una unión de términos para cubrir flujos repartidos entre
archivos.
Usa prefijos para enlazar palabras como `enqueue` con identificadores como
`enqueueEvent`, elimina stopwords comunes y aplica un vocabulario bilingüe pequeño y
determinista para conceptos frecuentes de repositorio. Los conceptos arquitectónicos
`offline`, `flow`, `API`, `persistence` e `isolation` añaden señales como outbox,
sync, route, processor, projector, transaction, auth y RLS. Los tokens compuestos por
`/`, `:`, `.` o `-` conservan su forma y aportan también sus componentes. No usa un
LLM para reformular la consulta.

La recuperación añade una pasada literal sensible a mayúsculas sobre el texto de la
generación para identificadores o cadenas que BM25 pueda dispersar. El ranking combina
BM25, cobertura de términos en contenido/path/símbolo, coincidencias exactas y tipo de
fuente; penaliza pruebas cuando la consulta no las pide y diversifica por archivo y
subsistema (`services/db`, `services/sync`, `routes`, etc.), no solo por aplicación.
Cada resultado conserva sus componentes de score y el motivo efectivo
(`fts5_all_terms`, `fts5_any_term` o literal), de modo que el orden sea auditable.

## Publicación e incrementalidad

La construcción completa ocurre en una transacción:

```text
building -> complete/anterior
         -> active/nueva
```

1. Capturar el snapshot. Si coincide exactamente con la generación activa y no se
   pidió `--full`, devolverla sin publicar otra generación.
2. Insertar la generación `building` y todos sus artefactos cuando existe un cambio.
3. Resolver únicamente targets inequívocos.
4. Validar conteos e integridad.
5. Volver a capturar el worktree mediante el callback de validación.
6. Marcar la activa anterior como `complete`, la nueva como `active` y actualizar
   `metadata.active_generation`.
7. Retener la activa y una inactiva; eliminar sus filas FTS antes del cascade.
8. Commit.

Cualquier excepción revierte la transacción, por lo que la generación anterior sigue
activa. Un run incremental reutiliza la extracción solo cuando coinciden ruta, hash y
fingerprint del parser. La comprobación no-op exige igualdad de repositorio, `HEAD`,
fingerprints de contenido/worktree, esquema y parser. `--full` omite tanto el no-op
como la reutilización.

El diseño no mantiene leases de lectores. En su lugar cada servicio comprueba de
nuevo el ID activo antes de cerrar la respuesta y falla con
`GENERATION_CHANGED_DURING_QUERY` si hubo publicación concurrente.

## Semántica opcional

Al definir `ATENEX_REPO_CONTEXT_SEMANTIC=1`, el composition root añade:

- embeddings HTTP locales de Ollama;
- una colección Qdrant separada por repositorio y generación;
- contextualización con ruta, lenguaje, líneas y tipo de chunk;
- fusión determinista Reciprocal Rank Fusion;
- un puerto opcional para reranking.

SQLite se activa primero como core válido. Luego se construye la proyección semántica.
Qdrant escribe un sentinel de completitud con repositorio, generación, identidad del
embedding, dimensiones y conteo. Solo un sentinel compatible habilita la consulta,
incluso después de reiniciar el proceso. Un build parcial o una caída degrada
`search_repo` al core con `SEMANTIC_UNAVAILABLE`.

Los diagnósticos persistentes de construcción permanecen en `status` y `doctor`.
Las consultas MCP solo incluyen diagnósticos que afecten esa respuesta concreta; no
repiten por cada búsqueda todos los warnings históricos del índice.

No hay adapter de reranker configurado en v1.

## Seguridad y recuperación

- `safe_relative_path` rechaza absolutos, drives Windows y `..`.
- `resolve_inside` vuelve a comprobar el root canónico.
- Las consultas de fuente nunca aceptan un root enviado por MCP.
- Un sidecar corrupto/incompatible o sin generación activa produce
  `INDEX_UNAVAILABLE`; no simula un resultado vacío.
- El sidecar completo es derivado y puede eliminarse de forma manual, con el servidor
  detenido y después de resolver su ruta exacta. El producto no ofrece una herramienta
  MCP de borrado.

Pruebas y resultados actuales: [evaluation-repo-context.md](evaluation-repo-context.md).
