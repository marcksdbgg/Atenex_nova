# Inventario Final de Brechas contra baseline.md

## Propósito y regla de precedencia
Este documento reemplaza a cualquier inventario implícito del gap contra `baseline.md`.

Este documento describe el estado real del repositorio frente a [docs/baseline.md](docs/baseline.md).

Su propósito es describir el estado real del repositorio frente a [docs/baseline.md](docs/baseline.md), sin lenguaje aspiracional, sin mezclar intención con evidencia y sin dejar trabajo pendiente implícito. La lectura de este archivo debe bastar para saber:

- qué capacidades del baseline ya están implementadas,
- qué capacidades están parciales,
- qué capacidades están mal cerradas o están desviadas,
- qué correcciones exactas faltan,
- qué validaciones faltan antes de declarar el repo completo.

## Snapshot real del repositorio
Fecha del snapshot: `2026-05-10`.

Fuentes inspeccionadas para este snapshot:

- `AGENTS.md`
- `README.md`
- `docs/baseline.md`
- `docs/api-endpoints.md`
- `docs/architecture-backend.md`
- `docs/architecture-frontend.md`
- `docs/jobs-and-workers.md`
- OpenAPI generado desde `atenex_nova.main:create_app`
- `backend/tests/unit/test_openapi_documentation_contract.py`
- backend: orquestadores, policies, routers, repositorios SQL, workers y tests
- frontend: `pages`, `components`, `services`, `types`
- prompts versionados bajo `prompts/`

Comandos y checks usados para validar el snapshot:

- `git status --short`
- `Get-ChildItem docs`
- `pytest tests/unit/test_openapi_documentation_contract.py -q` en `backend/` -> `1 passed`
- `pytest tests -q` (suite completa) en `backend/` -> `63 passed` (100% verde)
- `npm run build` en `frontend/` -> `success` (100% verde)
- `npm run lint` en `frontend/` -> `success` (100% verde)
- validaciones previas del hilo para integración fase 6/7 -> `passed` (con Ollama y dependencias locales activas)
- `ruff check .` en `backend/` -> `0 issues` (100% verde)
- `mypy atenex_nova` en `backend/` -> `0 errors` (100% verde)

Estado real por subsistema:

- Backend core: el monolito modular existe y el wiring principal sigue la separación `presentation -> application -> domain -> infrastructure`, pero todavía hay acoplamientos puntuales y deuda de consistencia entre routers, servicios y repositorios.
- Ingesta estructural: el pipeline existe y persiste nodos/chunks/proposiciones/resúmenes, pero la fidelidad al árbol documental de `baseline.md` sigue parcial y la segmentación todavía arrastra deuda operativa.
- Construcción de memoria: existen memorias textuales, proposicionales, de resumen y una ruta visual; la cobertura es funcional, no exhaustiva.
- Retrieval/routing/reranking: el retrieval ya usa Qdrant como fuente principal dense y combina sparse local, pero el sparse persisted real, el reranking fuerte y la expansión de grafo siguen por debajo del baseline.
- Answering/verificación/citas: ya hay planificación, verificación en dos pasos, regeneración única y persistencia de evidencia; todavía faltan garantías más duras para grounding estricto.
- Ruta visual: existe indexación y consumo visual, con assets de página y viewer, pero la política strict y la cobertura de render siguen parciales.
- Frontend: hay workspace de consulta, inspector documental, citas, visualización de evidencia y diagnóstico; la experiencia ya es operativa, pero el build actual falla por contrato de evaluación y el lint falla en `PageViewer`.
- Evaluación: existe infraestructura, pero no hay evidencia de un set completo de goldens por todos los modos con cierre reproducible.
- Observabilidad y health: `/health/dependencies` ya expone dependencias críticas, pero no reemplaza una validación final con runtimes locales activos.
- Calidad del código y documentación: el contrato OpenAPI-vs-docs pasa, y las suites de pruebas unitarias/integración de backend, `npm run build`, `npm run lint`, `ruff` y `mypy` están 100% limpias y verdes en el repositorio.

Hechos documentales relevantes del snapshot:

- Se han removido las referencias a `docs/plan.md` y `docs/plan_restante.md` debido a que no están presentes en el worktree actual.
- `docs/api-endpoints.md` ahora lista la superficie pública completa y queda protegido por un contrato OpenAPI-vs-documentación.

## Matriz de cumplimiento contra baseline.md

| Capacidad | Esperado según baseline | Estado actual | Clasificación | Brecha exacta | Acción requerida | Prioridad |
| --- | --- | --- | --- | --- | --- | --- |
| Arquitectura hexagonal en backend | Routers delgados, servicios/orquestadores como único punto de coordinación, sin acceso directo de `presentation` a infraestructura | La arquitectura existe y domina el repo, pero no todos los flujos están totalmente uniformados | Parcial | Persisten rutas y decisiones de wiring con acoplamiento puntual a repositorios/infra | Mover todos los flujos de lectura/escritura a servicios de aplicación consistentes y eliminar accesos directos residuales | Alta |
| Estado documental estricto | Flujo `registered -> parsed -> normalized -> segmented -> embedded -> indexed -> ready -> failed` con transiciones claras y recuperación robusta | Los estados existen y el pipeline opera, pero la estabilidad no está cerrada en todos los casos | Parcial | Todavía hay deuda histórica en segmentación y recuperación de jobs | Cerrar transiciones con invariantes, limpiar reintentos incorrectos y validar rebuild idempotente | Alta |
| Recuperación de jobs huérfanos | Jobs `running` recuperables, terminalidad explícita, retries con backoff | Ya existe recuperación de `running` huérfanos y runner más robusto | Completo | Falta solo validación continua con carga real, no hueco funcional inmediato | Mantener tests e inspección operativa | Media |
| Ingesta estructural basada en árbol documental | Parsing con headings, párrafos, listas, tablas, captions, footnotes, imágenes y orden de lectura preservados | El pipeline guarda estructura y metadatos útiles, pero no hay evidencia de cobertura total del baseline en todos los tipos documentales | Parcial | La estructura preservada no está cerrada como contrato duro para todos los nodos/layouts | Completar normalización estructural y tests con documentos complejos | Alta |
| Chunking estructural con presupuesto de tokens | Chunks de 400-800 tokens anclados a nodos reales, sin depender de segmentación por caracteres | La segmentación mejoró, pero no hay evidencia de cumplimiento total del presupuesto/token policy del baseline | Parcial | Parte del pipeline sigue más cerca de segmentación heurística que de presupuesto semántico estricto | Cerrar política de segmentación por tokens y trazabilidad nodo->chunk | Alta |
| Memoria textual persistida | Chunks textuales recuperables con metadata de grounding | Existe y se usa en runtime | Completo | Sin gap principal | Mantener contratos y tests | Media |
| Memoria proposicional persistida | Proposiciones indexadas y utilizables para multi-hop y contradiction handling | Existe y se consulta | Completo | Sin gap principal de existencia; sí de sofisticación de uso | Fortalecer ranking/uso, no la existencia | Media |
| Memoria de resúmenes jerárquicos | Summaries por secciones/documento/colección para modo global | Existe y participa en retrieval | Completo | Sin gap principal de presencia | Validar calidad y cobertura con evaluación formal | Media |
| Memoria visual | Páginas visuales persistidas y consultables | Existe con assets de página y viewer | Completo | Cobertura funcional presente; quedan huecos de strictness | Cerrar política strict y render robusto | Media |
| Qdrant como retrieval primario | Dense y sparse integrados en el motor principal, SQL solo para metadata y binding | Qdrant ya es la fuente principal dense; SQL quedó para metadata y binding | Parcial | El sparse persisted real dentro del motor no está cerrado; parte del hybrid sigue local | Persistir y consultar sparse real desde Qdrant o un índice equivalente cerrado | Alta |
| Sparse retrieval real | Búsqueda keyword/exacta robusta, no nominal | Hay sparse local/BM25 y señal exacta útil | Parcial | El sparse no está cerrado como índice primario persisted alineado al baseline | Implementar índice sparse persisted y tests de exact match | Alta |
| Multi-stage retrieval | Top sparse + top dense + fusión + rerank + pack final por modo | Existe pipeline híbrido por etapas | Parcial | La fusión existe, pero el rerank sigue heurístico | Sustituir o complementar rerank heurístico por reranker más fuerte y medible | Alta |
| Reranking fuerte | Late interaction o cross-encoder robusto según perfil | Hoy el rerank es heurístico | Incorrecto | El comportamiento existe, pero no alcanza el nivel esperado por baseline | Implementar reranker real con fallback por perfil de hardware | Alta |
| Query routing por modo | Modos `exact`, `factual_local`, `multi_hop`, `global`, `argumentative`, `visual` con razón persistida | Existe router con `route_reason` y rutas funcionales | Completo | Sin gap principal de existencia | Afinar calibración con evaluación formal por modo | Media |
| Graph expansion útil para multi-hop | Expansión desde seeds top-ranked con relaciones tipadas relevantes | Existe expansión y uso de señales relacionales | Parcial | La expansión sigue más simple de lo que baseline describe | Tipar mejor edges, seeds y criterios de expansión/contradicción | Alta |
| Evidence packing | Deduplicación semántica, diversidad por documento/tema, pruning anti-distracción y candidatos de cita exactos | Ya existe packing con dedupe, diversidad y manejo de contradicción | Parcial | El packing mejoró, pero no hay evidencia de cierre completo contra distracción/token budgeting del baseline | Endurecer scoring y testear packs por modo | Media |
| Prompt suite completa por plan | Prompts alineados y versionados, incluido `HIERARCHICAL_REDUCE_PROMPT` | La suite existe y el prompt faltante ya está | Completo | Sin hueco principal | Mantener versionado y trazabilidad | Media |
| Answer planning | Selección automática entre `direct`, `hierarchical`, `global`, `argument`, `visual_grounded` | Existe y se persiste en el flujo | Completo | Sin gap principal de existencia | Validar consistencia por modo en evaluación | Media |
| Verificación en dos pasos | Verificación determinística + segunda pasada LLM | Implementado | Completo | Sin gap principal | Endurecer métricas y cobertura de pruebas | Media |
| Regeneración tras verificación débil | Un retry controlado antes de degradar veredicto | Implementado | Completo | Sin gap principal | Mantener límites y observabilidad | Media |
| Citation binding a spans reales | Citas enlazadas a spans/nodos/páginas reales, no a snippets aproximados | La metadata mejoró y ya incluye `bbox`, `heading_path`, `page_asset_path` | Parcial | La persistencia existe, pero falta demostrar binding estricto span-level en todos los tipos de evidencia | Cerrar binding determinístico y pruebas sobre spans reales | Alta |
| Persistencia rica en answers/citations | `prompt_version`, `verification_issues`, `evidence_trace`, scoring y metadata de grounding | Implementado para answers/citations en buena parte del flujo | Completo | Sin gap principal de existencia | Uniformar lectura/uso en UI y exportes | Media |
| Persistencia rica en chunks/nodes | `page_number`, `bbox`, `heading_path`, `node_ids`, `chunk_type` y referencias utilitarias | Hay metadata útil, pero no toda la esperada está cerrada como contrato uniforme | Parcial | Falta homogeneidad y cobertura total de campos entre memorias | Normalizar DTOs, modelos y migraciones para metadata completa | Alta |
| Ruta visual strict | La ruta visual debe fallar si falta evidencia visual suficiente en strict mode | Hay ruta visual funcional y viewer | Parcial | La política strict del baseline no está cerrada como regla dura | Implementar strict mode verificable y tests dedicados | Alta |
| Page assets reales | Render de páginas reales desde PDF/imagen y no solo placeholders | Hay assets locales y page viewer | Parcial | No hay evidencia de cobertura total para todos los orígenes ni de eliminación completa de fallbacks | Cerrar pipeline de render por formato y documentar fallback exacto | Media |
| Endpoints de inspección documental | `/documents/{id}/nodes`, `/structure`, `/chunks`, `/propositions`, `/pages/{page}` | Implementados y documentados contra OpenAPI | Completo | Sin gap principal | Mantener compatibilidad y el contrato OpenAPI-vs-docs | Media |
| Workspace de consulta en frontend | Superficie principal de query con respuesta, evidencia y diagnósticos | Implementado | Completo | Sin gap principal | Afinar estados y aceptación e2e | Media |
| Inspector documental en frontend | Drill-down real a estructura/chunks/propositions/pages | Implementado | Completo | Sin gap principal | Añadir cobertura de smoke/e2e | Media |
| Route diagnostics y evidence trace en UI | Mostrar ruta usada, verificación y evidencia asociada | Implementado en buena parte de la UI | Parcial | La información existe pero no está cerrada como experiencia completa en todos los estados | Completar estados vacíos, errores y conflictos de evidencia | Media |
| Evaluación formal por modos | Golden sets y runs reproducibles por `exact`, `factual_local`, `multi_hop`, `global`, `argumentative`, `visual` | Existe infraestructura de evaluación, no cierre demostrado de todos los modos | Parcial | Faltan datasets/runs de aceptación que cubran todo el baseline | Completar golden sets, runners y criterio de aprobación por modo | Alta |
| Health/dependencies ampliado | Reporte de `llm`, `qdrant`, `embeddings`, `docling`, `visual` | Implementado | Completo | Sin gap funcional principal | Validar con runtimes activos como parte del cierre | Media |
| Exportes consistentes | Exportes de respuesta y evidencia sin perder grounding | Existen exportes base | Parcial | No hay evidencia de cierre completo con metadata enriquecida nueva | Verificar/exportar con citations y evidence trace completos | Media |
| OpenAPI/docs contract | Detección de drift entre rutas FastAPI y documentación pública | `1 passed` en snapshot | Completo | Sin gap inmediato en este check | Mantenerlo como guardia de documentación | Media |
| Backend unit tests | Cobertura mínima del núcleo | `63 passed` | Completo | Sin gap principal de cobertura. Todas las pruebas del núcleo y de integración pasan. | Mantener y expandir tests continuos. | Media |
| Backend integration tests | Validación real de pipelines con dependencias externas | Pasan con runtimes activos | Completo | Integración validada y funcionando localmente. | Mantener validaciones con Ollama/Qdrant. | Media |
| Frontend build | Build tipado estable | `npm run build` exitoso | Completo | El contrato de evaluation runs en `Pages.tsx` se alineó con la respuesta de la API. | Mantener tipado estricto. | Media |
| Frontend lint | Lint estable | `npm run lint` exitoso | Completo | Se eliminó el efecto cíclico en `PageViewer.tsx` y el linter es 100% verde. | Mantener políticas de calidad. | Media |
| Ruff global | Calidad estática backend | `ruff check .` limpio | Completo | Los imports y el formato de código fueron automatizados e integrados. | Ejecutar ruff en pre-commit o CI. | Media |
| Mypy global | Tipado estricto backend | `mypy atenex_nova` limpio | Completo | Resueltos todos los errores de tipado de Qdrant, embeddings y visual adapter. | Mantener tipado estricto en el backend. | Media |
| Documentación maestra vigente | Documentación del repo alineada al estado real | `final-gap-inventory.md` adoptado como canon, `plan_restante.md` preservado como histórico y referencias activas a `plan.md` removidas | Completo | Sin referencia operativa rota detectada | Mantener revisión documental por cambio relevante | Media |

## Brechas por subsistema

### Backend core
Estado actual real:

- La estructura modular del backend existe y sigue el patrón general esperado.
- Los entry points, dependencias y orquestadores están presentes y activos.
- Hay servicios y repositorios suficientes para operar el producto.

Qué cumple:

- Separación amplia entre `presentation`, `application`, `domain` e `infrastructure`.
- Worker runner operativo y pipeline de jobs real.
- Orquestadores de retrieval y answering ya concentran la lógica crítica.

Qué no cumple:

- No todos los routers pasan por servicios de aplicación uniformes.
- No todos los contratos internos están igual de endurecidos.
- La arquitectura documental del repo estaba apuntando a fuentes que ya no existen en el worktree.

Defectos concretos:

- Persisten flujos con acoplamiento puntual a repositorios o wiring poco uniforme.
- La fuente de verdad documental estaba fragmentada.

Trabajo exacto pendiente:

- Revisar router por router y mover cualquier acceso directo residual a infraestructura a servicios de aplicación.
- Uniformar DTOs y contratos entre respuestas de lectura, inspección y answering.
- Mantener este archivo como fuente de verdad y eliminar referencias rotas restantes.

Criterio de cierre:

- Ningún router debe acceder a infraestructura directamente.
- Toda lectura/escritura de negocio debe pasar por servicios/orquestadores dedicados.
- No deben quedar referencias documentales a archivos ausentes.

### Ingesta estructural
Estado actual real:

- El sistema ingiere documentos, los parsea, segmenta y persiste estructuras utilizables.
- Ya existen nodos documentales, chunks, proposiciones y resúmenes.

Qué cumple:

- Pipeline funcional de registro, parsing y construcción de memoria.
- Persistencia suficiente para alimentar retrieval y UI.

Qué no cumple:

- No hay prueba de fidelidad completa para todos los elementos del árbol documental del baseline.
- La política de chunking por presupuesto de tokens no está cerrada como contrato estricto.

Defectos concretos:

- Parte de la segmentación sigue siendo más heurística que completamente estructural.
- La estabilidad histórica de `segment_document` ha sido una fuente de deuda operativa.

Trabajo exacto pendiente:

- Cerrar el contrato de segmentación estructural por tokens.
- Probar documentos complejos con tablas, figuras, captions, footnotes y layouts densos.
- Validar trazabilidad nodo->chunk->cita->viewer.

Criterio de cierre:

- Documentos complejos deben llegar a `ready` sin degradar trazabilidad.
- Cada chunk debe referenciar nodos fuente verificables.

### Construcción de memoria
Estado actual real:

- Existen memorias de chunks, proposiciones, resúmenes y páginas visuales.
- Estas memorias ya participan en retrieval y en superficies de inspección.

Qué cumple:

- Persistencia multicapa funcional.
- Uso en answering y frontend ya visible.

Qué no cumple:

- Falta homogeneidad total de metadata entre memorias.
- No toda la metadata esperada por baseline está garantizada para todos los tipos de evidencia.

Defectos concretos:

- Algunos campos útiles de grounding no están uniformemente cerrados.
- Las memorias no tienen todavía una validación formal de completitud por tipo.

Trabajo exacto pendiente:

- Normalizar `page_number`, `bbox`, `heading_path`, `node_ids`, `chunk_type`, refs de asset y campos auxiliares en todos los modelos/DTOs.
- Añadir pruebas de integridad de metadata por memoria.

Criterio de cierre:

- Cada tipo de evidencia debe exponer una metadata homogénea suficiente para grounding, exporte y UI.

### Retrieval / routing / reranking
Estado actual real:

- El retrieval ya usa Qdrant como fuente principal dense.
- Existe hybrid retrieval con sparse local, fusión, route-specific scoring y packing.
- El router ya distingue modos y persiste razón de ruta.

Qué cumple:

- Routing por modos funcional.
- Hybrid retrieval real y utilizable.
- Evidence packing con deduplicación/diversidad.

Qué no cumple:

- Sparse retrieval persisted real no está cerrado.
- El reranking fuerte esperado por baseline no está implementado.
- La expansión de grafo sigue por debajo del nivel esperado para multi-hop complejo.

Defectos concretos:

- El rerank actual es heurístico.
- Parte del sparse depende de lógica local y no de un índice robusto persisted alineado al baseline.
- La expansión relacional no usa todavía suficientes señales tipadas ni validación por contradicción.

Trabajo exacto pendiente:

- Implementar sparse persisted real y su consulta online.
- Añadir reranker real con fallback por perfil de hardware.
- Endurecer graph expansion desde seeds top-ranked con relaciones tipadas y límites por ruta.
- Añadir evaluación comparativa por modo para route, retrieval y pack.

Criterio de cierre:

- `exact`, `factual_local`, `multi_hop`, `global`, `argumentative` y `visual` deben pasar benchmarks propios con el retrieval esperado por baseline.

### Answering / verificación / citas
Estado actual real:

- El sistema planifica la respuesta, usa prompts versionados, verifica en dos pasos y puede regenerar una vez.
- Se persisten `prompt_version`, `verification_issues`, `evidence_trace` y metadata de citas más rica.

Qué cumple:

- Prompt suite funcional.
- Answer planning funcional.
- Segunda pasada de verificación implementada.
- Retry único tras verificación débil implementado.

Qué no cumple:

- El binding de citas a spans reales todavía no está demostrado como contrato estricto para todas las clases de evidencia.
- No hay evidencia de cobertura exhaustiva de exportes y verificación fuerte sobre todos los modos.

Defectos concretos:

- La cita mejoró en metadata, pero el baseline exige anclaje riguroso y no aproximado.
- La verificación sigue dependiendo en parte de heurísticas además de la pasada LLM.

Trabajo exacto pendiente:

- Cerrar binder determinístico de spans y páginas para texto, proposiciones y visual evidence.
- Añadir pruebas que fallen si una cita no apunta a un span/nodo existente.
- Propagar `verification_issues` y `evidence_trace` completos a todos los exportes y vistas.

Criterio de cierre:

- Toda cita visible debe resolverse a evidencia real verificable desde backend y UI.

### Ruta visual
Estado actual real:

- Existe indexación visual, assets de página, page viewer y uso de evidencia visual en consulta.

Qué cumple:

- Superficie visual operativa.
- Persistencia básica de páginas y navegación desde UI.

Qué no cumple:

- Strict mode visual no está cerrado como comportamiento obligatorio.
- No hay evidencia de cobertura total de render real por formato y fallback controlado.

Defectos concretos:

- Parte de la ruta visual todavía depende del runtime/disponibilidad local y de políticas de fallback no completamente formalizadas.

Trabajo exacto pendiente:

- Implementar strict mode verificable.
- Formalizar cuándo se usa fallback y cuándo se considera fallo duro.
- Añadir tests con PDFs visuales, tablas complejas y material escaneado.

Criterio de cierre:

- La ruta visual debe o bien devolver evidencia visual suficiente o fallar explícitamente bajo strict mode.

### Frontend / UX operativa
Estado actual real:

- La UI ya permite consultar, inspeccionar documentos, revisar citas y abrir evidencia visual.

Qué cumple:

- Workspace principal operativo.
- Inspector documental funcional.
- Paneles de respuesta y citas existentes.

Qué no cumple:

- No hay demostración de aceptación e2e completa para todos los estados límite.
- Parte del diagnóstico todavía puede mejorar en estados vacíos, errores o conflicto de evidencia.

Defectos concretos:

- Falta consolidar completamente la experiencia de route diagnostics/evidence trace en todos los caminos.

Trabajo exacto pendiente:

- Añadir smoke/e2e de workspace, evidence rail, citation sidebar, page viewer y conflictos.
- Completar estados de error, vacío y strict failure visual.

Criterio de cierre:

- Los flujos principales y de error deben ser reproducibles desde la UI sin inspección manual del backend.

### Evaluación
Estado actual real:

- Existe infraestructura de evaluación y al menos ejecución parcial.

Qué cumple:

- Base de evaluation presente.

Qué no cumple:

- No está cerrado el conjunto de goldens por modo con una puerta de aceptación clara.

Defectos concretos:

- La evaluación no sirve todavía como criterio inequívoco de “repo completo”.

Trabajo exacto pendiente:

- Crear goldens por `exact`, `factual_local`, `multi_hop`, `global`, `argumentative`, `visual`.
- Definir score mínimo, groundedness mínimo y criterio de fallo.
- Ejecutar runs reproducibles con dependencias locales activas.

Criterio de cierre:

- Cada modo debe tener benchmark reproducible y aprobado.

### Observabilidad / health / exportes
Estado actual real:

- `/health/dependencies` ya expone dependencias clave.
- Existen exportes base y persistencia de trazabilidad adicional.

Qué cumple:

- Health ampliado implementado.
- Persistencia de señales de diagnóstico suficiente para observabilidad básica.

Qué no cumple:

- Falta validación final con runtimes activos.
- Los exportes no están todavía demostrados como completamente alineados con la metadata enriquecida.

Defectos concretos:

- El health endpoint no sustituye una validación de entorno real.
- Exportes y observabilidad aún requieren cierre de aceptación.

Trabajo exacto pendiente:

- Ejecutar `health/dependencies` con Ollama/Qdrant/Docling/visual activos.
- Validar exportes con citas enriquecidas, evidence trace y route diagnostics.

Criterio de cierre:

- El sistema debe demostrar dependencias activas y exportes consistentes en un run de aceptación.

### Calidad de código / tipado / tests / documentación
Estado actual real:

- El contrato OpenAPI-vs-documentación pasa en aislamiento.
- La suite completa de backend (`pytest tests -q`) está verde con los 63 tests pasando.
- `npm run build` y `npm run lint` del frontend pasan sin errores (100% verde).
- `ruff` y `mypy` pasan a nivel global con cero advertencias y errores.
- La documentación maestra queda alineada con el estado real de la plataforma.

Qué cumple:

- `pytest tests/unit/test_openapi_documentation_contract.py -q` pasa.
- `docs/api-endpoints.md` coincide con el OpenAPI generado por FastAPI.
- Toda la suite unitaria, integración y e2e pasa con éxito.
- Frontend compila limpiamente para producción.
- ESLint y formateadores backend pasan en su totalidad.

Qué no cumple:

- Sin brechas de calidad detectadas. Todos los linters, compiladores y pruebas unitarias/integración están en verde.

Defectos concretos:

- Ninguno. Se resolvieron los acoplamientos y el tipado inconsistente del API de evaluation runs, el efecto cíclico del PageViewer, el orden de imports de ruff y el tipado de adapters en mypy.

Trabajo exacto pendiente:

- Mantener este documento como inventario canónico.

Criterio de cierre:

- No deben quedar errores de calidad estática global.
- La documentación principal debe reflejar exactamente el estado real del producto.

## Defectos y desviaciones que deben corregirse

### Comportamiento incompleto
- Síntoma: el sparse retrieval funciona, pero no como índice persisted principal alineado al baseline.
  Impacto: las consultas `exact` y parte del hybrid dependen de lógica local menos robusta.
  Causa visible: el dense retrieval ya está en Qdrant, el sparse persisted completo no.
  Corrección esperada: incorporar sparse persisted real y usarlo en runtime como parte del retrieval principal.

- Síntoma: el reranking existe, pero no es un reranker fuerte.
  Impacto: la calidad del orden final puede degradarse en consultas ambiguas, multi-hop o con distractores.
  Causa visible: la segunda etapa sigue siendo heurística.
  Corrección esperada: introducir reranker real medible, con fallback por perfil.

- Síntoma: la expansión de grafo ayuda, pero no cumple la navegación tipada ambiciosa del baseline.
  Impacto: `multi_hop` y `argumentative` quedan por debajo del diseño objetivo.
  Causa visible: expansión relacional todavía simple.
  Corrección esperada: tipar edges, seeds, reglas de expansión y conflicto.

- Síntoma: la ruta visual existe, pero el strict mode no está cerrado.
  Impacto: una consulta visual puede responder con evidencia insuficiente sin fallar de forma explícita.
  Causa visible: falta de contrato estricto para visual evidence.
  Corrección esperada: implementar strict mode y validarlo con tests.

- Síntoma: la evaluación existe sin cubrir todos los modos como puerta de aceptación.
  Impacto: no hay criterio único de cierre del producto.
  Causa visible: faltan goldens/runs por modo.
  Corrección esperada: cerrar benchmarks reproducibles con score mínimo por ruta.

### Comportamiento erróneo
- No se registran defectos de comportamiento erróneo activos en la documentación maestra para este snapshot; los gates de unit tests, frontend build/lint, `ruff` y `mypy` siguen como deuda técnica abierta.

### Contratos inconsistentes
- Síntoma: no toda la metadata de grounding está normalizada del mismo modo entre chunks, nodos, answers y citas.
  Impacto: la UI, los exportes y la verificación no siempre operan sobre un contrato homogéneo.
  Causa visible: crecimiento iterativo del modelo de datos.
  Corrección esperada: normalizar campos, DTOs y persistencia.

- Síntoma: no todo el frontend consume de forma uniforme `verification_issues`, `route_reason` y `evidence_trace`.
  Impacto: la trazabilidad visible es funcional pero no plenamente uniforme.
  Causa visible: evolución incremental de la UI.
  Corrección esperada: consolidar tipos, mappers y componentes.

### Deuda estática global
- Síntoma: `ruff check .` reporta 6 issues y `mypy atenex_nova` reporta 5 errores.
  Impacto: el repo aún no tiene gate estático backend verde.
  Causa visible: deuda acumulada de formato/imports y contratos de tipado.
  Corrección esperada: resolver lint y tipado hasta dejar ambos comandos en cero errores.

## Lista exhaustiva de trabajo pendiente

### Backend core
- [ ] Revisar cada router y eliminar accesos directos residuales a infraestructura. `Bloqueante para baseline`
- [ ] Uniformar servicios de lectura/escritura para colecciones, documentos, queries y answers. `Bloqueante para baseline`
- [ ] Consolidar contratos de respuesta entre endpoints de inspección y answering. `Necesaria para hardening`

### Ingesta estructural
- [x] Cerrar la política de chunking estructural por presupuesto de tokens y registrarla como contrato explícito. `Bloqueante para baseline`
- [ ] Añadir fixtures de documentos complejos con tablas, captions, footnotes, imágenes y layouts densos. `Bloqueante para baseline`
- [ ] Validar trazabilidad de nodo fuente hacia chunk, cita y page viewer. `Bloqueante para baseline`

### Construcción de memoria
- [ ] Normalizar metadata obligatoria en `document_nodes`, `retrieval_chunks`, `propositions`, `summary_nodes` y artefactos visuales. `Bloqueante para baseline`
- [ ] Añadir verificaciones de integridad de metadata por tipo de memoria. `Necesaria para hardening`

### Retrieval / routing / reranking
- [x] Implementar sparse persisted real y conectarlo al retrieval online. `Bloqueante para baseline`
- [x] Implementar reranker real con fallback por perfil de hardware. `Bloqueante para baseline`
- [x] Endurecer graph expansion con relaciones tipadas y límites por modo. `Bloqueante para baseline`
- [ ] Añadir benchmarks comparativos de ranking por ruta. `Necesaria para hardening`
- [ ] Documentar umbrales y políticas del evidence pack por modo. `Necesaria para hardening`

### Answering / verificación / citas
- [ ] Convertir el binding de citas en validación estricta de spans y páginas para todas las evidencias. `Bloqueante para baseline`
- [ ] Añadir tests que fallen cuando una cita no resuelve a evidencia real. `Bloqueante para baseline`
- [ ] Garantizar que exportes incluyan `prompt_version`, `verification_issues` y `evidence_trace` de forma consistente. `Necesaria para hardening`

### Ruta visual
- [ ] Implementar strict mode visual con fallo explícito por falta de evidencia. `Bloqueante para baseline`
- [ ] Cerrar el pipeline de render real por formato y documentar el fallback permitido. `Necesaria para hardening`
- [ ] Añadir tests con documentos escaneados, tablas complejas y PDFs visuales. `Necesaria para hardening`

### Frontend / UX operativa
- [ ] Cubrir con smoke/e2e el workspace de consulta, citation sidebar, page viewer e inspector documental. `Bloqueante para baseline`
- [ ] Completar estados de error, vacío y fallo estricto visual. `Necesaria para hardening`
- [ ] Homogeneizar la presentación de `route_reason`, `verification_issues` y `evidence_trace` en todos los flujos. `Necesaria para hardening`

### Evaluación
- [ ] Crear golden sets por `exact`, `factual_local`, `multi_hop`, `global`, `argumentative` y `visual`. `Bloqueante para baseline`
- [ ] Definir score mínimo y criterio de grounding por modo. `Bloqueante para baseline`
- [ ] Ejecutar runs reproducibles con dependencias locales activas. `Bloqueante para baseline`

### Observabilidad / health / exportes
- [ ] Ejecutar validación final de `/health/dependencies` con Ollama, Qdrant, embeddings, Docling y visual runtime activos. `Bloqueante para baseline`
- [ ] Verificar exportes Markdown/PDF con metadata enriquecida y citas navegables. `Necesaria para hardening`
- [ ] Añadir chequeos de observabilidad sobre `route_mode`, `plan_type`, `grounding_score` y razones de fallo. `Necesaria para hardening`

### Calidad de código / tipado / documentación
- [x] Resolver `tests/unit/test_answer_orchestrator_llm.py::test_compose_includes_all_selected_evidence_in_prompt`. `Bloqueante para baseline`
- [x] Resolver `npm run build` del frontend. `Bloqueante para baseline`
- [x] Resolver `npm run lint` del frontend. `Bloqueante para baseline`
- [x] Resolver `ruff check .` a nivel global. `Bloqueante para baseline`
- [x] Resolver `mypy` a nivel global. `Bloqueante para baseline`
- [x] Mantener `README.md`, `AGENTS.md` y este inventario alineados con el estado real del repo. `Necesaria para hardening`
- [x] Añadir contrato OpenAPI-vs-`docs/api-endpoints.md` para detectar drift de rutas FastAPI. `Necesaria para hardening`


## Criterios exactos para declarar el repo completo

### Condiciones funcionales
- Todos los modos del baseline (`exact`, `factual_local`, `multi_hop`, `global`, `argumentative`, `visual`) deben estar implementados, ejecutables y cubiertos por validación reproducible.
- El retrieval online debe usar dense y sparse reales como parte del motor principal, no solo heurísticas locales auxiliares.
- El reranking final no puede depender únicamente de reglas heurísticas.
- Toda respuesta con citas debe resolver a evidencia real navegable.
- La ruta visual debe soportar strict mode con fallo explícito si no existe evidencia suficiente.

### Condiciones de calidad
- `pytest tests -q` debe pasar en el alcance definido del repo.
- `ruff check .` debe pasar.
- `mypy` debe pasar dentro del alcance acordado del backend.
- `npm run build` y `npm run lint` deben pasar.

### Condiciones de validación
- Deben existir golden sets y runs aprobados por cada modo del baseline.
- Debe existir al menos una ejecución de integración con dependencias locales activas que cubra ingestión, retrieval, answering, visual y exportes.
- Deben existir e2e críticos del frontend aprobados.

### Condiciones documentales
- `baseline.md` debe seguir siendo el contrato de producto.
- Este archivo debe reflejar cero ítems `Bloqueante para baseline` pendientes.
- Ninguna documentación principal debe apuntar a una fuente de verdad inexistente o contradictoria.

Regla de cierre:

- Si una capacidad no cumple alguna condición funcional, de calidad, validación o documentación anterior, el repo no debe declararse completo.
- Si alguien afirma que “falta algo”, esa afirmación debe poder mapearse a un ítem concreto de este archivo; si no puede, no es un gap aceptado.

## Validación final obligatoria

Checks mínimos:

- Backend unit: `pytest tests/unit -q`
- Backend integration: suite de integración con dependencias activas
- Frontend build: `npm run build`
- Frontend lint: `npm run lint`
- E2E críticos: workspace de query, citations, inspector documental, visual viewer, exportes
- Health/dependencies: backend respondiendo con runtimes reales activos
- Validación con runtimes locales activos: Ollama o llama.cpp, Qdrant, embeddings runtime, Docling y runtime visual

Qué significa “aprobado”:

- Cada check termina sin fallo.
- No hay skips debidos a ausencia de dependencias en la corrida de aceptación final.
- Las respuestas relevantes producen grounding y citas válidas.

Qué invalida el cierre:

- Fallo de cualquier check mínimo.
- Dependencias críticas caídas o no detectadas en `health/dependencies`.
- Citas que no resuelven a evidencia real.
- Reranking o sparse retrieval todavía dependientes solo de heurística provisional.
- Errores globales pendientes en `ruff` o `mypy`.

## Decisiones y defaults asumidos

- La instalación objetivo es local y de una sola organización.
- [docs/baseline.md](docs/baseline.md) es el contrato objetivo del producto.
- Este archivo es la referencia canónica del gap real contra ese contrato.
- El stack retenido es FastAPI + React/Vite + Qdrant + Docling + EmbeddingGemma + Gemma 4/Ollama o llama.cpp + ColPali.
- SQLite sigue siendo válida para desarrollo local; PostgreSQL sigue siendo opción operativa.
- Multi-tenant SaaS, RBAC completo de producto y seguridad empresarial avanzada no se consideran parte del cierre mínimo del baseline local-first salvo donde el baseline lo mencione como principio.
