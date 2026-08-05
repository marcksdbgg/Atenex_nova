# Integración de TurboQuant en Atenex Nova

Estado: **Historical** como diseño original de VecQuant y **Implemented / Verified**
para el fallback acotado descrito aquí. Dense Qdrant es ahora el camino primario del
RAG documental; la aceleración TurboVec viva y calibrada sigue **Planned**.

Este documento describe una optimización del bounded context RAG documental.
TurboQuant no está en la ruta crítica de Repo Context v1: el core determinista usa
SQLite FTS5 e índices estructurales; la recuperación semántica opcional usa Qdrant.

Contraste vivo del 2026-08-02 (**Historical** respecto del checkout actual): la
cuantización y el estimador existían, pero la aceleración no estaba **Verified**. El runtime no tenía
TurboVec ni archivos `.tvim`; `candidate_backend=auto` seleccionó PurePy. PurePy
escanea todos los códigos y materializa matrices `N × 384`: con la capa viva de
propositions, `score_propositions` tardó 48–69 s y presentó un riesgo de varios GiB
por consulta. El reranker neural también estaba degradado porque `torch` no estaba
instalado. Véase
[auditoria-rag-respuestas-sota-2026-08-02.md](auditoria-rag-respuestas-sota-2026-08-02.md).

Este documento describe la especificación técnica, el diseño de arquitectura y el estado de la integración de **TurboQuant / VecQuant** en la plataforma local de memoria documental **Atenex Nova**.

---

## 1. ¿Qué es TurboQuant y la variante TurboQuantprod?

**TurboQuant** es un framework de cuantización vectorial diseñado para reducir el tamaño de almacenamiento y la huella en memoria (RAM) de embeddings de alta dimensionalidad (como los generados por `EmbeddingGemma`), manteniendo al mismo tiempo una alta precisión en la estimación de similitud.

### Razón de la variante TurboQuantprod
En Atenex Nova, la similitud de embeddings se calcula principalmente mediante **similitud de coseno (cosine similarity)** o **producto interno (inner product)** sobre vectores normalizados. 
* **TurboQuantmse**: Minimiza el error de reconstrucción cuadrático medio (MSE), pero tiende a introducir sesgos en la estimación del producto interno.
* **TurboQuantprod (Variante Estándar)**: Corrige este sesgo mediante un esquema de cuantización en dos etapas:
  1. Aplica cuantización de Lloyd-Max (TurboQuantmse) con \(b - 1\) bits sobre el vector rotado ortogonalmente.
  2. Calcula el vector residual (el error entre el vector original y la reconstrucción de Lloyd-Max).
  3. Aplica proyección de Johnson-Lindenstrauss (QJL) de 1 bit al residual, guardando los signos y conservando de manera explícita la norma del residual y la norma del vector original.

Esto permite que la estimación de producto interno entre el vector de consulta (query) y el vector cuantizado sea altamente precisa, superando la distorsión semántica de esquemas de cuantización tradicionales.

---

## 2. Papel actual en el pipeline

### Qdrant dense primario; cuantización como representación derivada

En todos los perfiles, si Qdrant está habilitado y disponible, el camino online
primario usa el vector dense nombrado `dense` y la señal sparse nombrada `sparse`.
La cuantización SQL se conserva como representación derivada y fallback explícito:

1. **Ingesta**:
   * Docling y el chunker producen unidades con hard cap; `EmbeddingGemma` aplica el
     prefijo de documento y genera embeddings float32 en memoria.
   * `TurboQuantAdapter` cuantiza cada vector y persiste códigos en
     `quantized_vectors` con un perfil cuyo `codebook_version` incluye el fingerprint
     de compatibilidad `emb-v2`.
   * Qdrant recibe dense+sparse. Antes de usar una colección existente, el adapter
     valida nombre, dimensión y schema; una incompatibilidad exige rebuild.
   * `turbovec` puede construir un `.tvim` opcional. PurePy solo actúa cuando Qdrant
     dense no está disponible y la capa no excede el límite seguro configurado.

2. **Desacoplamiento de citas**: las citas siguen apuntando a tablas relacionales
   (`retrieval_chunks`, propositions, summaries y nodos), no a blobs cuantizados.

### Scoring por estimador de producto interno (H-3 cerrado)

La búsqueda dense **no reconstruye** vectores para rankear. `TurboQuantAdapter.estimate_inner_products` aplica el estimador insesgado de TurboQuantprod sobre los códigos Lloyd-Max+QJL. El stage de auditoría en retrieval es `dense_turbo_ip`.

### Flujo de consulta (Candidate Generation)

* **Stage 1 (candidatos dense)**: Qdrant devuelve top-N cuando su dense está listo.
  `CandidateIndexPort.search` es el fallback PurePy/TurboVec. PurePy puntúa
  exhaustivamente solo capas bajo el límite configurado; por encima degrada de forma
  visible en vez de materializar una matriz sin cota.
* **Stage 2 (sparse + fusión)**: BM25/SPLADE en Qdrant o local; fusión RRF con candidatos dense.
* **Stage 3 (rerank)**: el contrato admite reranker sobre los finalistas. En el runtime auditado, el adapter no pudo cargar `torch` y degradó a una heurística; reranking neural vivo sigue **Planned**.

### Selección de backend

| `ATENEX_CANDIDATE_BACKEND` | Comportamiento |
|---|---|
| `purepy` (default implícito sin turbovec) | Fallback: lee perfiles `emb-v2` compatibles y puntúa solo capas bajo el límite seguro |
| `turbovec` | Requiere `pip install -e ".[accel]"`; acelera con `.tvim` |
| `auto` | selecciona siempre PurePy en la implementación actual; no activa TurboVec solo por ser importable |

---

## 3. Estructura Arquitectónica Hexagonal

La integración de TurboQuant respeta estrictamente la arquitectura hexagonal de Atenex Nova, asegurando que las reglas de negocio (Domain) no se acoplen con librerías específicas de cuantización:

```
Domain (domain/ports/)
  ├── VectorQuantizerPort (quantize + estimate_inner_products)
  └── CandidateIndexPort (add_vectors/search/remove_vectors/delete_collection_indexes)

Application (application/)
  ├── IngestionOrchestrator (cuantiza → SQL; invalida caché del índice)
  ├── RetrievalOrchestrator (Qdrant dense+sparse; fallback dense_turbo_ip; RRF)
  └── QuantizationPolicyService (perfiles y bit-width)

Infrastructure
  ├── vector_quantization/
  │     └── TurboQuantAdapter (Lloyd-Max + QJL + estimador IP)
  └── indexes/
        ├── PurePyTurboQuantCandidateIndex (canónico sin turbovec)
        ├── TurboQuantCandidateIndex (acelerador opcional .tvim)
        ├── candidate_index_factory.py (auto | purepy | turbovec)
        └── QuantizedCodeStore (persistencia SQL)
```

### Detalle de Base de Datos (SQLModel)
* **`quantization_profiles`**: Guarda los parámetros del cuantizador (algoritmo, dimensiones, seeds de rotación y proyección, bit-width).
* **`quantized_vectors`**: Almacena los códigos binarios serializados (`idx_blob`, `qjl_blob`) junto a las normas de soporte (`residual_norm`, `vector_norm`), asociados a su UUID de nodo correspondiente en SQLite o PostgreSQL.

---

## 4. ¿Qué resta para la implementación completa? (brechas vigentes)

La topología de puertos y la cuantización están implementadas, pero el índice operativo
no está cerrado para escala de corpus. Antes de optimizaciones de codebook se requieren:

1. **Candidate generation sublineal o acotada**:
   * *Estado actual*: Qdrant dense es primario y el fallback PurePy tiene un límite
     estricto de cardinalidad; perfiles legados incompatibles se omiten.
   * *Pendiente*: TurboVec vivo verificado o una segunda ANN local para operar sin
     Qdrant a gran escala, con métricas y degradación explícitas.
2. **Readiness y paridad por generación**:
   * *Estado actual*: schema guard, fingerprint `emb-v2` y barrera temporal de
     readiness están **Implemented / Verified** en pruebas focalizadas.
   * *Pendiente*: `generation_id`, manifest, cardinalidad, checksums y activación
     atómica definitiva por capa; rebuild limpio vivo.
3. **Reranking real**:
   * *Estado actual*: el contrato y el fallback existen.
   * *Pendiente*: adapter multilingüe vivo calibrado, health explícito y ablación de
     calidad.
4. **Validación a escala**:
   * *Estado actual*: los unit tests prueban precisión del estimador, no RAM/latencia
     sobre cientos de miles de vectores.
   * *Pendiente*: p50/p95/p99, RAM pico, concurrencia y degradación por cardinalidad.

Mejoras posteriores:

5. **Auto-Calibración del Codebook**:
   * *Estado actual*: El registro de perfiles (`TurboQuantProfileRegistry`) utiliza centroides precalculados para distribuciones normales estándar \(N(0,1)\) de Lloyd-Max.
   * *Pendiente*: Un mecanismo de ajuste dinámico de codebooks en caliente según la distribución real de embeddings de la colección para colecciones muy específicas (ej. dominios médicos o legales con vocabulario restringido).
6. **Compresión Adaptativa en Caliente**:
   * *Estado actual*: El bit-width (usualmente 4 bits) se configura globalmente mediante `ATENEX_TURBOVEC_BIT_WIDTH`.
   * *Pendiente*: Permitir que el sistema reduzca dinámicamente a 2 o 3 bits para ciertas capas (como resúmenes) y mantenga 4 bits para capas factuales críticas (proposiciones y chunks) de manera automática.
7. **Optimización de Reranking sobre Residuales**:
   * *Estado actual*: El Stage 2 y Rerank neural operan sobre texto reconstruido o re-embedding exacto.
   * *Pendiente*: Implementar scoring por late-interaction (estilo ColPali) utilizando de manera directa el residual cuantizado para evitar pasadas secundarias al modelo de embeddings.

---

## 5. Estrategia de Validación y Benchmarks

Para validar que la integración funciona correctamente y mejora el pipeline previo, se dispone de las siguientes pruebas:

### Validación de Precisión de Cuantización (Unit Tests)
La precisión se mide a través del test unitario de estimación de similitud:
```powershell
backend/.venv312/Scripts/python.exe -m pytest tests/unit/test_turboquant.py -v
```
* **Métrica de éxito**:
  * La similitud de coseno entre un vector original y su versión de-cuantizada debe ser **superior a 0.75**.
  * El error de estimación de producto interno entre dos vectores normalizados aleatorios cuantizados a 4 bits debe ser **menor a 0.20**.

### Validación del Pipeline Completo (Tests de Integración)
* Verificar que el cargado, indexado y búsqueda no fallan en modo estricto:
```powershell
backend/.venv312/Scripts/python.exe -m pytest tests -q
```
* **Comparativa de rendimiento (objetivo Planned, no evidencia viva)**:
  * **Lite (8 GB RAM)**: Debe usar 2-3 bits en perfiles y verificar que no hay picos de consumo de RAM superiores a 200 MB adicionales durante la carga del índice local de candidatos.
  * **Standard/Advanced**: definir y medir un SLO de candidate search. El objetivo
    histórico `< 5 ms` no fue validado y contradice la latencia de decenas de segundos
    del backend PurePy vivo.
