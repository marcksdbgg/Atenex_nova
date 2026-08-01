# Atenex Nova — contrato de producto

Estado del documento: **Implemented** como contrato vigente. El core determinista
existe y su smoke acceptance está **Verified**; proveedores semánticos vivos,
reranking concreto y la matriz exhaustiva de release siguen marcados por separado.

## Producto

Atenex Nova es un motor local de inteligencia de repositorios. Su primera entrega,
`atenex-context`, construye un índice verificable del worktree y lo expone mediante
CLI y un servidor MCP de solo lectura. El objetivo no es introducir el repositorio
completo en cada prompt, sino permitir que un agente descubra el contexto necesario,
abra el código fuente exacto y compruebe el impacto y las pruebas relacionadas.

El motor es general:

- Atenex Nova es el primer repositorio de desarrollo y autoindexación.
- `/mnt/ssd/Nyro/panaderia_romero/client-romero/` es la prueba externa obligatoria.
- Ningún extractor, ranking o herramienta puede depender de nombres propios de esos
  dos repositorios.

El RAG documental existente se conserva como bounded context legado y como base de
trabajo futura para la tesis y el corpus literario. No es la promesa principal de
esta versión y no se eliminará durante el pivote. Su adapter de respuestas Ollama
solicita texto visible (`think=false`); Atenex conserva en su propia capa de
aplicación la planificación, evidencia y verificación. Los marcadores heurísticos
de ruta se comparan como palabras o frases completas, no como subcadenas. La UI
reconcilia respuestas persistidas cuando se interrumpe el transporte y no elimina
el turno pendiente mientras el backend continúa procesándolo.
El perfil de idioma explícito de una colección prevalece sobre la detección de la
consulta; en un corpus `es`, generación, reparación y respuesta se mantienen en
español sin una etapa de traducción. Las preguntas simples no se convierten en
`multi_hop` por llevar signo de interrogación ni adoptan síntesis global solo porque
se recuperó un resumen. El grounding combina de forma conservadora la señal
determinista y la revisión LLM: esta última puede reducir, pero no inflar, score o
veredicto. Cada marcador `[n]` —incluidos grupos como `[2, 4]`— debe corresponder a
evidencia citable y a un enlace resuelto; el sistema no fabrica marcadores al final
de una respuesta.

## Invariantes

1. **Local-first.** La indexación determinista funciona sin red, GPU, Ollama ni
   Qdrant.
2. **Fuente verificable.** Código, pruebas y configuración actuales prevalecen sobre
   resúmenes, memoria e índice.
3. **Worktree real.** La identidad de una consulta incluye `HEAD` y un fingerprint de
   cambios confirmados y no confirmados.
4. **Índice derivado.** El índice puede reconstruirse. No contiene decisiones que no
   existan también en archivos versionados.
5. **Lectura segura.** MCP v1 no escribe archivos, no ejecuta comandos solicitados por
   el cliente y no sale del root autorizado.
6. **Evidencia.** Resultados estructurales incluyen ruta relativa, rango de líneas,
   hash de contenido y procedencia de la relación.
7. **Degradación explícita.** Un parser o servicio opcional ausente reduce cobertura,
   pero nunca se disfraza como recuperación completa.
8. **Generaciones coherentes.** Los lectores solo observan generaciones completas y
   atómicamente activadas.
9. **Presupuesto estricto.** RepoMap y paquetes de contexto respetan el presupuesto
   solicitado y declaran truncamiento.
10. **Sin segunda verdad.** Resúmenes sirven para navegar; antes de modificar, el
    agente debe leer la fuente exacta.

## Alcance funcional v1

### Core determinista

Estado: **Implemented / Verified** en la suite focalizada y los dos repositorios
de aceptación.

- Descubrimiento Git-aware de archivos rastreados y no rastreados no ignorados.
- Fallback seguro para directorios sin Git.
- Snapshots por hashes de contenido, estado Git y fingerprint del worktree.
- Indexación incremental, no-op seguro para snapshots idénticos y reutilización por
  hash cuando existe un cambio parcial.
- SQLite sidecar con FTS5, símbolos, fragmentos, relaciones y componentes.
- Extracción sintáctica para Python, TypeScript, TSX, JavaScript, SQL y Java.
- Representación estructural-léxica para Markdown, JSON/JSONC, YAML, TOML, CSS y
  shell.
- Búsqueda exacta sobre la fuente viva y FTS5 adaptativo: intersección estricta,
  relajación determinista, prefijos, cobertura de términos y vocabulario bilingüe
  acotado; consulta del grafo por separado.
- Descomposición determinista de focos transversales y fusión RRF por path para
  separar offline, transporte, persistencia y autorización sin depender de un LLM.
- RepoMap reproducible con centralidad, foco fusionado, diversidad por subsistema y
  límite de tokens.
- CLI de indexación, servicio, estado y diagnóstico.
- MCP stdio de solo lectura con seis herramientas.
- Skill de proyecto portable para imponer el flujo overview → búsqueda → fuente →
  impacto/pruebas en Codex y Claude.

### Semántica opcional

Estado: **Implemented / Optional** para Ollama, Qdrant, readiness y RRF. Los
contratos están verificados con fakes; el reranker concreto y la revalidación con
servicios vivos están **Planned**.

- Embeddings locales con contexto de archivo, símbolo y rol.
- Qdrant separado por repositorio y generación.
- Fusión RRF de señales exactas, léxicas, estructurales y semánticas.
- Puerto y coordinación opcional para reranking de un conjunto pequeño de
  candidatos; el adapter concreto sigue **Planned**.
- Operación completa del core si los servicios no están disponibles.

## Interfaces públicas

El ejecutable canónico es `atenex-context`:

```text
atenex-context index --repo PATH [--data-dir PATH] [--full]
atenex-context serve --repo PATH [--data-dir PATH] [--transport stdio]
atenex-context status --repo PATH [--data-dir PATH] [--json]
atenex-context doctor --repo PATH [--data-dir PATH] [--json]
```

MCP v1:

- `repo_overview`
- `search_repo`
- `get_symbol`
- `trace_symbol`
- `analyze_impact`
- `related_tests`

El contrato detallado y los envelopes de respuesta están en
[mcp-tools.md](mcp-tools.md).

Una integración local puede ejecutar `index` incremental inmediatamente antes de
abrir el transporte `stdio`, como hace
`backend/scripts/serve_repo_context_mcp.sh`. Esa preparación ocurre fuera de la
superficie MCP; durante la conversación las seis herramientas permanecen de solo
lectura.

## Datos y seguridad

La ubicación predeterminada es:

```text
<repo>/.atenex/context/index.sqlite3
```

`--data-dir` permite mantener el sidecar fuera del repositorio. El scanner:

- normaliza rutas relativas POSIX;
- respeta `.gitignore`;
- excluye secretos, binarios, dependencias, builds, bases de datos y archivos
  demasiado grandes;
- rechaza escapes mediante `..` o enlaces simbólicos;
- ejecuta procesos con argumentos, nunca mediante shell;
- registra exclusiones y fallos de análisis.

Véase [indexing-and-storage.md](indexing-and-storage.md).

## Criterios de aceptación

El smoke manifest versionado cumple actualmente 13/13 hits, Recall@20 medio 1.0 y
MRR 0.90384615 sobre Atenex Nova y `client-romero`. Incluye regresiones para una
consulta natural de punta a punta del flujo offline y su `repo_overview`. Esto
demuestra la primera versión
usable, no sustituye el held-out set ni las mediciones de rendimiento descritas en
el protocolo completo.

- El conjunto gold de identificadores exactos obtiene 100 % de recuperación.
- Al menos 95 % de los archivos elegibles se analizan sintácticamente; todo resto
  queda diagnosticado y disponible por búsqueda léxica.
- Recall@20 mínimo de 0.85 y MRR mínimo de 0.65 en el conjunto versionado.
- Al menos 80 % de las tareas incluyen un archivo correcto dentro de 8 000 tokens.
- El modo híbrido no es inferior a la mejor señal individual en el conjunto global.
- MCP no modifica la fuente ni accede fuera del root.
- El mismo snapshot, configuración y consulta producen el mismo RepoMap.
- Atenex Nova y `client-romero` completan sus escenarios E2E.

El procedimiento y los goldens se definen en
[evaluation-repo-context.md](evaluation-repo-context.md).

## Fuera de alcance de v1

- Nueva interfaz web para Repo Context.
- Transporte MCP remoto o multiusuario.
- Escritura de memoria, archivos o decisiones desde MCP.
- Ejecución de pruebas o comandos mediante herramientas MCP.
- Inferencia completa de llamadas dinámicas.
- Garantía de resolución total para metaprogramación, reflexión o SQL construido
  dinámicamente.
- Sustituir o reescribir el RAG documental heredado.

## Autoridad documental

1. Este archivo define el contrato.
2. [plan-repo-context-mcp.md](plan-repo-context-mcp.md) define la secuencia de
   implementación.
3. [architecture-repo-context.md](architecture-repo-context.md) define límites y
   componentes.
4. [README.md](../README.md) describe el snapshot ejecutable y la puesta en marcha.
5. [auditoria-completa.md](auditoria-completa.md) contrasta el contrato con la
   implementación y enlaza la auditoría histórica del RAG.
