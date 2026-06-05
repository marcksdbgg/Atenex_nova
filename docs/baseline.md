Mi propuesta sería una **Atenex Nova**: una segunda generación de Atenex pensada para 2026, con **Gemma 4 como modelo generativo principal, EmbeddingGemma como embedding local por defecto, parsing documental estructural moderno, retrieval híbrido de varias capas, routing de consultas, memoria proposicional para razonamiento complejo y verificación antes de responder**. No la plantearía como “otro chatbot con vectores”, sino como una **plataforma de memoria local con varios motores de consulta**. La razón es simple: hoy el mejor rendimiento no sale de un solo índice vectorial más un LLM pequeño, sino de combinar búsqueda densa y sparse, estructura documental, búsqueda de proposiciones, y modos distintos de recuperación según el tipo de pregunta. ([Google AI for Developers][1])

## Qué partes de Atenex cambiaría y con qué

Primero, **cambiaría Granite-3.2-2B como generador principal**. En 2026, Gemma 4 ya ofrece una base más moderna: es abierta, multimodal, soporta más de 140 idiomas, tiene variantes pequeñas y medianas, ventanas de contexto de hasta 256K y modos configurables de razonamiento. Para una laptop o mini-PC local, yo usaría **Gemma 4 12B** como perfil estándar y **Gemma 4 E2B** como perfil liviano. Si el dispositivo es todavía más ajustado, usaría **Gemma 3n** como perfil ultraligero para edge/NPU. ([Google AI for Developers][1])

Segundo, **cambiaría el embedding stack**. Aquí sí usaría Google de forma clara: **EmbeddingGemma** como embedding local por defecto. Tiene 308M parámetros, soporta más de 100 idiomas, permite salida flexible de 768 a 128 dimensiones mediante Matryoshka Representation Learning y Google indica que puede correr con menos de 200 MB de RAM cuando se cuantiza. Eso encaja perfecto con el objetivo original de Atenex de no disparar la memoria del sistema. Mi perfil recomendado sería:

* **256 dimensiones** para equipos de 8 GB,
* **384 dimensiones** para 16 GB,
* **768 dimensiones** solo cuando quieras priorizar recall/calidad sobre huella.
  ([Google AI for Developers][2])

Tercero, **reemplazaría FAISS/Chroma como núcleo del retrieval por Qdrant self-hosted/local**. No porque FAISS sea malo, sino porque Qdrant hoy ya soporta mejor una arquitectura híbrida moderna: dense + sparse + reranking/multi-vector en un mismo motor, además de despliegue self-hosted y modo local. Eso reduce fricción operativa y facilita que Atenex deje de ser un “vector store más BM25 pegado a mano” y pase a ser un motor de recuperación unificado. ([Qdrant][3])

Cuarto, **cambiaría el chunking semántico-estructural simple por un pipeline de parsing estructural + late/contextual chunking**. El propio PDF reconoce que los PDFs complejos y las tablas dañan la calidad de respuesta. Para eso, en 2026 yo pondría **Docling** como parser base: entiende PDF, DOCX, PPTX, XLSX, HTML, imágenes y OCR; además extrae layout, reading order, tablas, fórmulas y estructura. Sobre esa salida, no haría chunks “planos”; haría **chunks derivados del árbol documental**: sección, subsección, párrafo, tabla, caption, lista, nota al pie. Luego generaría embeddings con contexto estructural, no con texto aislado. Para páginas muy visuales o PDFs escaneados, añadiría una ruta opcional con **ColPali**, que recupera páginas como imágenes usando layout visual, tablas y gráficos, no solo texto extraído.  ([GitHub][4])

Quinto, **ya no dejaría que todo dependa de chunks planos**. Para preguntas complejas, de comparación o argumentativas, el estado del arte se movió hacia estructuras de memoria más ricas. Ahí reemplazaría el RAG “solo por pasajes” por una memoria de tres capas:

1. **memoria de pasajes** para recuperación local y factual,
2. **memoria proposicional** para claims, definiciones, premisas y relaciones entre ideas,
3. **memoria global/comunitaria** para responder preguntas holísticas del corpus.
   ToPG muestra muy bien por qué: los sistemas chunk-based funcionan razonablemente para preguntas simples, pero flojean en multi-hop, abstracción y composición. GraphRAG/DRIFT añade valor cuando necesitas síntesis global. HippoRAG 2 va en la línea de memoria no paramétrica más asociativa. ([arXiv][5])

Sexto, **quitaría Map-Reduce como estrategia central siempre activa**. El PDF ya deja claro que puede agregar latencia lineal y superar 90 segundos en consultas amplias. En lugar de eso, usaría un **router de consulta** que decida cuándo conviene:

* respuesta directa con hybrid RAG,
* recorrido de grafo proposicional,
* búsqueda global tipo DRIFT,
* o síntesis jerárquica tipo map-reduce solo si realmente hace falta.
  Eso está más alineado con Self-Route y con enfoques de retrieval consciente de distracciones como LDAR. En otras palabras: **Map-Reduce pasa de ser el motor por defecto a ser un modo de ejecución especializado**.  ([arXiv][6])

Séptimo, **cambiaría el módulo de privacidad**. En Atenex actual la privacidad de consulta descansa en perturbación/ofuscación de embeddings. Eso sirve como baseline, pero no debería ser la defensa principal en una arquitectura on-prem real. En Atenex Nova yo haría esto:

* privacidad base = **aislamiento por tenant, RBAC/ABAC, cifrado en reposo, cifrado por colección, auditoría y separación de claves**;
* perturbación de embeddings = **opcional**, no núcleo;
* si alguna vez el sistema usa recuperación remota o federada, recién ahí entran esquemas más fuertes tipo **RemoteRAG** o **ppRAG**.
  Eso es más serio desde ingeniería de producto y más correcto desde threat model.  ([ACL Anthology][7])

## Arquitectura propuesta: Atenex Nova

Ahora sí, la arquitectura completa.

### 1) Principios de diseño

Atenex Nova tendría seis principios:

**Local-first real.** Todo lo crítico corre local: parser, embeddings, índices, retrieval, generación, verificación. La nube solo sería opcional y desacoplada. Eso preserva la soberanía de datos que Atenex ya tenía como objetivo central.

**Multi-motor de recuperación.** No un único retriever, sino varios modos coordinados.

**Document understanding antes que vectorización rápida.** Primero entender el documento; después indexarlo.

**Routing antes que generación.** El error típico es dejar que el LLM “arregle” un retrieval flojo. Aquí primero se decide el modo de búsqueda.

**Verificación antes de mostrar la respuesta.** Toda respuesta debe salir con grounding y citas válidas.

**Escalado por perfiles de hardware.** La misma arquitectura debe correr en 8 GB, 16 GB o 32 GB cambiando perfil, no rediseñando el sistema.

### 2) Perfiles de despliegue

Yo definiría tres perfiles:

**Perfil A — 8 GB RAM**

* Generador: Gemma 4 E2B
* Embeddings: EmbeddingGemma 256d
* Qdrant local
* Sin índice visual permanente; ColPali bajo demanda
* Sin grafo global completo, solo proposiciones de documentos priorizados

**Perfil B — 16 GB RAM**

* Generador: Gemma 4 12B
* Embeddings: EmbeddingGemma 384d
* Qdrant self-hosted
* Índice visual opcional
* Grafo proposicional completo
* Resúmenes globales por colección

**Perfil C — 32 GB+ / workstation**

* Generador: Gemma 4 26B o 31B para síntesis pesada
* Embeddings: EmbeddingGemma 768d
* Índices dense+sparse+multi-vector completos
* Índice visual persistente
* DRIFT/global mode completo
  Las capacidades y tamaños de Gemma 4 permiten este escalado por familia de modelo sin abandonar el ecosistema. ([Google AI for Developers][1])

## 3) Plano de datos

Atenex Nova tendría estos stores:

**Blob store local**
Documentos originales, imágenes, PDFs, snapshots de parseo.

**Relational metadata store**
PostgreSQL o SQLite según perfil. Aquí viven usuarios, tenants, ACLs, documentos, versiones, logs, jobs, citas, spans, historial.

**Retrieval store**
Qdrant para dense vectors, sparse vectors y, cuando aplique, multi-vector/late interaction. ([Qdrant][3])

**Graph store lógico**
No hace falta meter un grafo separado si no quieres complejidad. Para un diseño robusto y simple, yo guardaría proposiciones, entidades, pasajes y edges en PostgreSQL, con tablas optimizadas y cachés de vecindad. Si el corpus crece mucho, recién migraría a un graph engine dedicado.

**Summary store**
Resúmenes por chunk, sección, documento, colección y comunidad temática.

**Citation store**
Cada evidencia debe quedar anclada a doc_id, página, bloque, offset y span. Esto es crítico para que la cita no sea “de documento”, sino “de fragmento”.

## 4) Pipeline de ingesta

Este pipeline es donde más mejoraría Atenex.

### Paso 4.1 — Recepción

El documento entra por upload, carpeta observada o API. Se genera un `document_id`, un `tenant_id`, hash del archivo, versión y metadatos básicos.

### Paso 4.2 — Parsing estructural

Se procesa con **Docling**. La salida no debe ser solo texto plano, sino una estructura tipo:

* páginas
* bloques
* encabezados
* párrafos
* listas
* tablas
* captions
* imágenes/figuras
* notas al pie
* orden de lectura
  Esto corrige directamente la debilidad que Atenex reconoce con PDFs complejos y tablas.  ([GitHub][4])

### Paso 4.3 — Normalización semántica

Aquí se hace:

* detección de idioma
* limpieza
* normalización de whitespace
* preservación de numerales, fechas, códigos, IDs
* enlazado de caption ↔ figura
* enlazado de celda ↔ tabla ↔ encabezado

### Paso 4.4 — Segmentación en capas

No un solo chunk, sino cuatro vistas del mismo documento:

**Vista A: spans estructurales**
Párrafos, secciones, celdas de tabla, captions.

**Vista B: chunks de recuperación**
Construidos sobre estructura y contexto cercano.

**Vista C: proposiciones/claims**
Afirmaciones atómicas extraídas de spans.

**Vista D: resúmenes jerárquicos**
Resumen de sección, documento y colección.

Esto permite que la consulta ataque distintas granularidades.

### Paso 4.5 — Embeddings

Cada unidad de la Vista B recibe embedding con **EmbeddingGemma**.
Cada proposición de la Vista C también recibe embedding propio.
Cada resumen jerárquico recibe embedding separado.
La ventaja de EmbeddingGemma es que puedes bajar dimensión sin cambiar el backbone, lo que simplifica perfiles de memoria. ([Google AI for Developers][2])

### Paso 4.6 — Índices

Se construyen cinco índices:

1. **Sparse index** para keywords, nombres exactos, códigos, fechas.
2. **Dense chunk index** para recuperación semántica clásica.
3. **Dense proposition index** para afirmaciones y definiciones.
4. **Summary index** para búsquedas globales y overview.
5. **Visual page index** opcional con ColPali para documentos visuales/tablas complejas. ([Qdrant][3])

### Paso 4.7 — Grafo proposicional

De cada documento salen nodos:

* entidad
* proposición
* pasaje
* documento
* concepto
  y edges:
* mentions
* defines
* supports
* contradicts
* elaborates
* appears_in
  No es ArgRAG completo, pero ya deja la base correcta para reasoning complejo y conflictivo. ToPG prueba precisamente el valor de pasar de chunk retrieval a recuperación guiada por proposiciones y relaciones. ([arXiv][5])

### Paso 4.8 — Resúmenes globales

Por cada colección o tenant se generan:

* resumen ejecutivo
* conceptos centrales
* comunidades temáticas
* glosario interno
  Esto habilita respuestas globales estilo GraphRAG/DRIFT sin tener que re-leer todo en tiempo de consulta. ([Microsoft GitHub][8])

## 5) Pipeline completo desde la pregunta hasta la respuesta

Ahora el flujo principal.

### Paso 5.1 — Entrada del usuario

El usuario envía la pregunta por UI o API.
Antes de tocar retrieval:

* se autentica,
* se resuelve tenant y permisos,
* se determina ámbito documental permitido,
* se registra traza.

### Paso 5.2 — Preprocesamiento de la consulta

Se hace:

* normalización
* detección de idioma
* corrección leve de typo
* expansión opcional de términos
* clasificación de intención:

  * factual local,
  * exacta/literal,
  * comparación,
  * resumen global,
  * multi-hop,
  * argumentativa/contradictoria,
  * multimodal/document-layout-heavy.

### Paso 5.3 — Query embedding

Se genera embedding con EmbeddingGemma en la dimensión del perfil activo.
Además se genera una versión sparse de la consulta.

### Paso 5.4 — Router

Este es el corazón nuevo de Atenex Nova. El router decide el modo:

**Modo 1: Exact match**
Para códigos, nombres propios, fechas, IDs.
Usa sparse dominante + dense auxiliar.

**Modo 2: Factual local**
Para preguntas puntuales sobre uno o pocos pasajes.
Usa dense+sparse híbrido y reranking.

**Modo 3: Multi-hop**
Para preguntas donde hay que conectar varias piezas.
Usa semillas híbridas y luego recorrido sobre grafo proposicional.

**Modo 4: Global**
Para preguntas como “qué postura general emerge del corpus sobre X”.
Usa summary index + comunidades temáticas + DRIFT/global retrieval.

**Modo 5: Argumentativo**
Para preguntas con conflicto o posiciones encontradas.
Usa recuperación híbrida + agrupación de evidencia + estructura support/attack.

**Modo 6: Visual/documental**
Para tablas, escaneos, layout complejo.
Usa ColPali/índice visual + spans de texto del parser.
Esto reemplaza el Map-Reduce genérico como primera respuesta a todo.  ([arXiv][6])

### Paso 5.5 — Recuperación primaria

Se obtienen candidatos desde:

* sparse index,
* dense chunk index,
* dense proposition index,
* summary index,
* visual page index si aplica.

### Paso 5.6 — Fusión y reranking

Aquí usaría dos etapas:

**Etapa A: Hybrid fusion**
Dense + sparse. Qdrant soporta bien este patrón. ([Qdrant][3])

**Etapa B: late reranking / interaction-aware reranking**
Ya no solo un cross-encoder clásico. Preferiría un reranker de interacción tardía estilo ColBERT-class cuando el hardware lo permita, porque maneja mejor matices finos y evidencia compleja. Si el equipo es ajustado, fallback a cross-encoder liviano.

### Paso 5.7 — Evidence pack builder

Esta pieza arma el contexto final para el generador.
Hace:

* deduplicación semántica,
* eliminación de pasajes distractores,
* agrupación por documento/tema,
* presupuesto de tokens,
* construcción de árbol de evidencia,
* anclaje de citas a spans reales.
  Aquí metería explícitamente una lógica distraction-aware inspirada en LDAR para no inundar a Gemma con pasajes irrelevantes. ([arXiv][9])

### Paso 5.8 — Selección del modo de síntesis

Aquí recién se decide cómo generar:

**Síntesis directa**
Cuando hay 3–8 evidencias limpias y una respuesta simple.

**Síntesis jerárquica**
Cuando hay muchos clusters, múltiples documentos o conflicto entre fuentes.

**Global synthesis**
Cuando la respuesta sale de resúmenes y comunidades temáticas.

**Argument synthesis**
Cuando hay soporte y ataque; la salida debe distinguir evidencia a favor, en contra y síntesis.

Map-Reduce sigue existiendo, pero como submodo de la síntesis jerárquica, no como arquitectura base.

### Paso 5.9 — Generación con Gemma 4

Gemma 4 recibe:

* consulta normalizada,
* evidencia ya curada,
* estructura de citas,
* instrucciones de estilo de respuesta,
* política de incertidumbre,
* esquema de salida.
  La respuesta debe producir:

1. respuesta principal,
2. evidencias clave,
3. contradicciones o límites,
4. citas.
   Gemma 4 es una buena pieza aquí porque combina contexto amplio, multilingüismo, multimodalidad y tamaños razonables para despliegue local. ([Google AI for Developers][1])

### Paso 5.10 — Verificación

Antes de mostrar la respuesta:

* se valida que cada cita apunte a un span existente,
* se calcula grounding score,
* se detecta contradicción no resuelta,
* se revisa si la respuesta sobreafirma.
  Si falla, el sistema hace una segunda pasada breve o responde con incertidumbre explícita.

### Paso 5.11 — Entrega al usuario

La UI devuelve:

* respuesta,
* citas inline,
* panel lateral de fuentes,
* nivel de confianza,
* “evidencia en conflicto” cuando exista,
* y la ruta usada: factual, multi-hop, global, argumentativa o visual.
  Aquí mantendría la buena idea de Atenex de interfaz con trazabilidad visible. La captura del PDF ya apunta a eso y vale la pena conservarlo. 

## 6) Seguridad y multi-tenant

Atenex actual tiene multi-tenancy lógico. Yo lo endurecería.

Cada tenant debe tener:

* namespace propio,
* claves propias,
* colecciones lógicas separadas,
* ACL por documento,
* política de borrado/versionado,
* logs auditables,
* caché separada.

No confiaría en perturbación de embeddings como frontera principal. Para entorno local, el control real es **aislamiento + cifrado + auditoría + mínimos privilegios**. La perturbación puede quedar solo como defensa adicional. Si el día de mañana hubiera recuperación externa, recién migraría a esquemas tipo RemoteRAG o ppRAG.  ([ACL Anthology][7])

## 7) Qué conservaría de Atenex

No todo hay que botarlo.

Yo sí conservaría:

* el foco en **hardware de consumo**,
* la idea de que **retrieval manda más que tamaño del LLM**,
* el uso de **búsqueda híbrida**,
* la **trazabilidad visible**,
* el despliegue **on-prem/local-first**.
  Eso está bien sustentado en el PDF y sigue siendo correcto. El propio experimento muestra que el reranking sube bastante la fidelidad y que el footprint bajo es valioso en equipos modestos.

## 8) Resumen ejecutivo: reemplazo componente por componente

Te lo dejo directo.

**Granite-3.2-2B → Gemma 4 12B / E2B**
Porque Gemma 4 es más reciente, más multilingüe, multimodal y con contexto más amplio. ([Google AI for Developers][1])

**Embeddings locales actuales → EmbeddingGemma**
Porque reduce mucho RAM, es multilingüe y permite bajar dimensión sin cambiar stack. ([Google AI for Developers][2])

**FAISS/Chroma + BM25 acoplado manualmente → Qdrant híbrido local**
Porque unifica dense, sparse y reranking/multi-vector con mejor operabilidad local. ([Qdrant][3])

**Parser textual estructural básico → Docling**
Porque entiende layout, tablas, OCR, fórmulas y reading order. ([GitHub][4])

**Chunking semántico plano → chunking estructural + contextual/late chunking**
Porque mejora recuperación real en documentos complejos. 

**RAG por chunks como memoria principal → memoria en capas: chunk + proposición + resumen global**
Porque ToPG, HippoRAG 2 y GraphRAG muestran que las tareas complejas requieren más estructura. ([arXiv][5])

**Map-Reduce por defecto → router + modos especializados**
Porque evita la latencia lineal que el propio Atenex reporta.  ([arXiv][6])

**Privacidad por perturbación como centro → seguridad de producto real + privacidad avanzada opcional**
Porque es más sólido para multi-tenant real. ([ACL Anthology][7])

**Texto-only retrieval para PDFs complejos → ruta visual con ColPali**
Porque rescata tablas, layout y páginas escaneadas. ([Hugging Face][10])

## Conclusión

Mi diseño para una mejor versión de Atenex sería este: **un RAG local de segunda generación, no monolítico en lógica aunque sí desplegable como un solo producto**, con **Gemma 4 como cerebro**, **EmbeddingGemma como memoria semántica barata**, **Docling como parser estructural**, **Qdrant como motor híbrido**, **grafo proposicional para preguntas complejas**, **routing para decidir el modo correcto de recuperación/síntesis** y **verificación obligatoria antes de responder**.

Eso corrige exactamente lo que hoy limita a Atenex:

* baja la dependencia del Map-Reduce secuencial,
* mejora mucho PDFs/tablas/layout,
* mejora multilingüismo,
* y hace que el sistema deje de ser “RAG clásico bien hecho” para convertirse en una **plataforma de memoria local moderna**.

[1]: https://ai.google.dev/gemma/docs/core/model_card_4 "Gemma 4 model card  |  Google AI for Developers"
[2]: https://ai.google.dev/gemma/docs/embeddinggemma "EmbeddingGemma model overview  |  Google AI for Developers"
[3]: https://qdrant.tech/documentation/tutorials-search-engineering/reranking-hybrid-search/ "Hybrid Search with Reranking - Qdrant"
[4]: https://github.com/docling-project/docling "GitHub - docling-project/docling: Get your documents ready for gen AI · GitHub"
[5]: https://arxiv.org/abs/2601.04859 "[2601.04859] A Navigational Approach for Comprehensive RAG via Traversal over Proposition Graphs"
[6]: https://arxiv.org/abs/2407.16833?utm_source=chatgpt.com "Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach"
[7]: https://aclanthology.org/2025.findings-acl.197/?utm_source=chatgpt.com "RemoteRAG: A Privacy-Preserving LLM Cloud RAG Service"
[8]: https://microsoft.github.io/graphrag/query/drift_search/ "DRIFT Search - GraphRAG"
[9]: https://arxiv.org/abs/2509.21865?utm_source=chatgpt.com "Beyond RAG vs. Long-Context: Learning Distraction-Aware ..."
[10]: https://huggingface.co/docs/transformers/en/model_doc/colpali "ColPali · Hugging Face"
