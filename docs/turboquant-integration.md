# Integración de TurboQuant en Atenex Nova

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

## 2. ¿Qué reemplaza y qué optimiza en el Pipeline?

### Una sola copia dense canónica (LITE/STANDARD)

En perfiles **LITE** y **STANDARD**, el dense ya **no** se duplica en Qdrant ni en archivos `.tvim` como fuente de verdad. La representación canónica es:

1. **Ingesta**:
   * Docling segmenta el documento; `EmbeddingGemma` genera embeddings float32 en memoria.
   * `TurboQuantAdapter` cuantiza cada vector (Lloyd-Max + QJL) y persiste los códigos en SQL (`quantized_vectors`).
   * Qdrant recibe **solo sparse** (BM25/SPLADE) en LITE/STANDARD; dense float32 en Qdrant queda reservado al perfil **MAX** (`dense_goes_to_qdrant`).
   * `turbovec` (extra opcional `[accel]`) puede acelerar la búsqueda de candidatos construyendo un índice `.tvim` a partir de los mismos códigos; si no está instalado, `PurePyTurboQuantCandidateIndex` puntúa directamente sobre SQL.

2. **Decoplamiento de citas**: las citas siguen apuntando a tablas relacionales (`retrieval_chunks`, proposiciones, resúmenes, nodos de documento), no a blobs cuantizados.

### Scoring por estimador de producto interno (H-3 cerrado)

La búsqueda dense **no reconstruye** vectores para rankear. `TurboQuantAdapter.estimate_inner_products` aplica el estimador insesgado de TurboQuantprod sobre los códigos Lloyd-Max+QJL. El stage de auditoría en retrieval es `dense_turbo_ip`.

### Flujo de consulta (Candidate Generation)

* **Stage 1 (candidatos dense)**: `CandidateIndexPort.search` — pure-python o turbovec — devuelve top-N usando el estimador IP.
* **Stage 2 (sparse + fusión)**: BM25/SPLADE en Qdrant o local; fusión RRF con candidatos dense.
* **Stage 3 (rerank)**: reranker neural sobre texto de los finalistas (una pasada final, no por capa).

### Selección de backend

| `ATENEX_CANDIDATE_BACKEND` | Comportamiento |
|---|---|
| `purepy` (default implícito sin turbovec) | Lee `quantized_vectors`, puntúa con estimador IP |
| `turbovec` | Requiere `pip install -e ".[accel]"`; acelera con `.tvim` |
| `auto` | turbovec si importable y perfil LITE/STANDARD; si no, purepy |

---

## 3. Estructura Arquitectónica Hexagonal

La integración de TurboQuant respeta estrictamente la arquitectura hexagonal de Atenex Nova, asegurando que las reglas de negocio (Domain) no se acoplen con librerías específicas de cuantización:

```
Domain (domain/ports/)
  ├── VectorQuantizerPort (quantize + estimate_inner_products)
  └── CandidateIndexPort (add_vectors/search/remove_vectors/delete_collection_indexes)

Application (application/)
  ├── IngestionOrchestrator (cuantiza → SQL; invalida caché del índice)
  ├── RetrievalOrchestrator (dense_turbo_ip + sparse + rerank final)
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

## 4. ¿Qué resta para la Implementación Completa? (Brechas Identificadas)

Aunque la topología de TurboQuant está completamente implementada, se identifican las siguientes brechas operativas para un cierre del 100%:

1. **Auto-Calibración del Codebook**:
   * *Estado actual*: El registro de perfiles (`TurboQuantProfileRegistry`) utiliza centroides precalculados para distribuciones normales estándar \(N(0,1)\) de Lloyd-Max.
   * *Pendiente*: Un mecanismo de ajuste dinámico de codebooks en caliente según la distribución real de embeddings de la colección para colecciones muy específicas (ej. dominios médicos o legales con vocabulario restringido).
2. **Compresión Adaptativa en Caliente**:
   * *Estado actual*: El bit-width (usualmente 4 bits) se configura globalmente mediante `ATENEX_TURBOVEC_BIT_WIDTH`.
   * *Pendiente*: Permitir que el sistema reduzca dinámicamente a 2 o 3 bits para ciertas capas (como resúmenes) y mantenga 4 bits para capas factuales críticas (proposiciones y chunks) de manera automática.
3. **Optimización de Reranking sobre Residuales**:
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
* **Comparativa de Rendimiento (Lite vs. Advanced)**:
  * **Lite (8 GB RAM)**: Debe usar 2-3 bits en perfiles y verificar que no hay picos de consumo de RAM superiores a 200 MB adicionales durante la carga del índice local de candidatos.
  * **Standard/Advanced**: Comparar latencia de búsqueda de candidatos (debe responder en < 5ms sobre el índice cuantizado local).
