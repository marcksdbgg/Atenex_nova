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

El RAG documental existente se conserva como bounded context mantenido y como base de
trabajo para la tesis y el corpus literario. Repo Context continúa siendo el producto
primario de esta versión. Su adapter de respuestas Ollama
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

### Contrato vigente del RAG documental

Estado de implementación: **Implemented**. Estado de validación: **Verified** en
pruebas focalizadas del checkout. Estado del corpus vivo reconstruido con este
contrato: **Planned**. La calidad comparable a NotebookLM y el aprendizaje continuo
no forman parte de los claims actuales.

La implementación mantenida:

- aplica una allowlist al importar corpus y excluye metadata administrativa,
  sidecars, bases, archives, dependencias, builds y symlinks fuera del root;
- reconoce transcripciones y conserva timestamps, offsets de fuente y metadata
  estructural fuera del cuerpo dominante;
- subdivide incluso un nodo individual sobredimensionado con hard cap de 800 tokens,
  overlap de 80 y spans trazables;
- separa inputs de embedding para query y documento, registra el fingerprint de
  compatibilidad `emb-v2`, procesa Ollama en lotes ordenados y validados y omite
  perfiles PurePy legados incompatibles;
- usa dense Qdrant como camino primario cuando está disponible, valida schema/dimensión
  publica upserts en lotes idempotentes y limita el fallback PurePy exhaustivo por
  cardinalidad;
- evita inicializar Docling para TXT y usa un lock advisory de proceso que permite
  reiniciar el único worker SQLite después de un crash sin confundir archivo
  persistente con dueño vivo;
- pagina el inventario completo de documentos y summaries, contextualiza follow-ups
  y ejecuta variantes deterministas acotadas para rutas complejas; la fusión RRF
  conserva la procedencia de cada etapa;
- crea exactamente un summary de sección por chunk y uno de documento con procedencia;
  una operación explícita reduce esos summaries a una memoria extractiva de colección
  única y embebible;
- evalúa una barrera temporal de readiness para chunks, propositions, summaries,
  embeddings, graph y visual cuando corresponda, y en reanudación degrada `READY` y
  agenda la reparación mínima de artefactos incompletos;
- bloquea consultas mientras haya rebuild, estados transitorios, una colección vacía
  o ningún documento `READY`; los documentos `FAILED` quedan fuera y se informan como
  corpus gap. Toda evidencia recuperada se valida y rehidrata desde SQL, y un payload
  con fingerprint incompatible se descarta;
- limpia de forma simétrica e idempotente chunks, propositions, summaries, visuales,
  aristas y sus representaciones candidate/Qdrant antes de reparse o rebuild;
- empaqueta evidencia por relevancia, cobertura y citabilidad; las rutas global,
  jerárquica y argumentativa ejecutan maps acotados y una reducción final;
- segmenta la salida en claims, audita citation binding y soporte léxico por claim y
  permite que el verificador LLM reduzca, pero no eleve, el veredicto determinista;
- devuelve metadata de evidencia compacta y hace visible en la UI un verdict
  `unverified`, `conflicting`, sin citas o con grounding bajo.

La memoria de colección entregada es extractiva y su procedencia es explícita; no es
todavía una jerarquía temática aprendida. La barrera de readiness usa artefactos y
timestamps de jobs, no un `generation_id` común con activación atómica en SQL,
Qdrant, candidate indexes, summaries y graph. El grafo permanece heurístico e
intra-documento. El reranker neural vivo y calibrado tampoco está **Verified**.

Por tanto permanecen **Planned**: `generation_id` y activación atómica definitivos,
reconciliación completa entre stores, rebuild limpio del corpus vivo, benchmark Jesús
G de 150 preguntas con revisión humana, reranker vivo calibrado, grafo cross-document
evaluado y comparación reproducible con NotebookLM/EOS. El estado por entrega y las
puertas G0–G6 se registran en
[plan-rag-sintesis-corpus.md](plan-rag-sintesis-corpus.md). La evidencia causal está
en [auditoria-rag-respuestas-sota-2026-08-02.md](auditoria-rag-respuestas-sota-2026-08-02.md).

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

### Semántica requerida

Estado: **Implemented / Verified** para la composición obligatoria de Ollama, Qdrant,
readiness y RRF, tanto con fakes como con servicios vivos sobre Atenex Nova y
`client-romero`. El reranker concreto sigue **Planned**.

- Embeddings locales con contexto de archivo, símbolo y rol.
- Qdrant separado por repositorio y generación.
- Fusión RRF de señales exactas, léxicas, estructurales y semánticas.
- Puerto para reranking de un conjunto pequeño de
  candidatos; el adapter concreto sigue **Planned**.
- La indexación falla si no puede completar o reutilizar la proyección semántica.
- Un lock advisory de proceso por sidecar serializa como una sola operación la
  publicación SQLite y su proyección semántica requerida.
- El servidor no publica herramientas sin sentinel semántico compatible.
- `search_repo` y el foco de `repo_overview` usan fusión híbrida por defecto.

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

`trace_symbol` admite orientación entrante, saliente o `both`. `analyze_impact`
resuelve rutas exactas mediante el índice de paths, incluye siempre el archivo
objetivo y acepta archivos estructurales sin símbolos extraídos.

El contrato detallado y los envelopes de respuesta están en
[mcp-tools.md](mcp-tools.md).

Una integración local puede ejecutar `index` incremental inmediatamente antes de
abrir el transporte `stdio`, como hace
`backend/scripts/serve_repo_context_mcp.sh`. Esa preparación ocurre fuera de la
superficie MCP; durante la conversación las seis herramientas permanecen de solo
lectura. Para roots relativos, el launcher resuelve el directorio de trabajo del
proceso y exige que sea un checkout Git. Una configuración de proyecto puede pasar
además el checkout principal esperado para restringir el root a ese checkout o sus
worktrees. El registro global de Codex usa `.` deliberadamente para seguir el
repositorio de cada sesión.

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
   implementación y enlaza la auditoría viva e histórica del RAG.
6. [auditoria-rag-respuestas-sota-2026-08-02.md](auditoria-rag-respuestas-sota-2026-08-02.md)
   es la evidencia vigente sobre calidad de respuesta documental.
7. [plan-rag-sintesis-corpus.md](plan-rag-sintesis-corpus.md) es el ledger de
   ejecución: distingue artefactos **Implemented** y pruebas **Verified** de las
   puertas G0–G6 todavía **Planned**.
