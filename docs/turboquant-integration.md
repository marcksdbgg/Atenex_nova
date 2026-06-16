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

### Reemplazo de Persistencia y Carga de Embeddings
Antes de la integración de TurboQuant, el pipeline almacenaba los embeddings completos en formato de punto flotante de 32 bits (float32) directamente en memoria RAM o requería desplegar colecciones completas e intensivas de Qdrant en dispositivos con recursos limitados.

Con TurboQuant, el pipeline se optimiza mediante la persistencia híbrida:
1. **Ingesta**:
   * El documento se procesa (Docling), segmenta y se generan los embeddings vectoriales locales (`EmbeddingGemma`).
   * Los embeddings se normalizan, rotan ortogonalmente y se cuantizan a un formato binario comprimido mediante `TurboQuantprod`.
   * Los códigos cuantizados (blobs de índices de centroides y signos residuales) se guardan en la tabla SQL `quantized_vectors`.
   * Las representaciones compactas se agregan al índice en disco local `.tvim` (`turbovec.IdMapIndex`), manteniendo la RAM limpia.
2. **Decoplamiento de Citas (Citations)**:
   * Las citas y anclas de evidencia (spans, páginas, regiones visuales) no apuntan a los vectores cuantizados. Siguen apuntando a sus tablas relacionales específicas (`retrieval_chunks`, `propositions`, `summary_nodes`, `document_nodes`). Esto mantiene el motor de verificación determinístico y robusto frente a compresión.

### Optimización en Consulta (Candidate Generation Stage)
Para realizar una consulta, Atenex Nova no recupera directamente de Qdrant ni de fuerza bruta. El flujo se optimiza en tres etapas de búsqueda:
* **Stage 1 (Generación de Candidatos)**: Se realiza una búsqueda dense de bajo costo sobre el índice local cuantizado de `turbovec` recuperando los **top 200 candidatos**.
* **Stage 2 (Fusión e Hibridación)**: Se combinan los candidatos del Stage 1 con los resultados de `BM25` (búsqueda sparse local) mediante Reciprocal Rank Fusion (RRF).
* **Stage 3 (Reranking Exacto)**: Solo los candidatos supervivientes finalistas se cargan (o se decuantizan para aproximar el vector original) y se pasan al reranker neural para construir el `EvidencePack` definitivo.

---

## 3. Estructura Arquitectónica Hexagonal

La integración de TurboQuant respeta estrictamente la arquitectura hexagonal de Atenex Nova, asegurando que las reglas de negocio (Domain) no se acoplen con librerías específicas de cuantización:

```
Domain (domain/ports/)
  ├── VectorQuantizerPort (Define quantize/dequantize)
  └── CandidateIndexPort (Define add_vectors/search/remove_vectors/delete_collection_indexes)

Application (application/)
  ├── IngestionOrchestrator (Orquesta cuantización y guardado tras generación de embeddings)
  ├── RetrievalOrchestrator (Consulta el índice de candidatos antes de fusionar y reordenar)
  └── QuantizationPolicyService (Resuelve perfiles y configura el bit-width según hardware)

Infrastructure
  ├── vector_quantization/
  │     ├── TurboQuantAdapter (Implementa VectorQuantizerPort con Lloyd-Max + QJL)
  │     └── TurboQuantProfileRegistry (Contiene los centroides Lloyd-Max optimizados)
  └── indexes/
        ├── TurboQuantCandidateIndex (Implementa CandidateIndexPort con turbovec y archivos .tvim)
        └── QuantizedCodeStore (Capa de persistencia SQL de metadatos y blobs cuantizados)
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
