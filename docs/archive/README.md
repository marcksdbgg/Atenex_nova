# Archivo documental

Estado: **Historical**.

Este directorio conserva contratos, auditorías y planes reemplazados. Ningún archivo
de aquí describe por sí solo el estado vivo de Atenex Nova. Para el contrato actual,
volver a [baseline.md](../baseline.md); para el estado claim→implementación, consultar
[auditoria-completa.md](../auditoria-completa.md).

## Colecciones archivadas

| Directorio | Fecha de corte | Sustituto vigente | Motivo de conservación |
|---|---:|---|---|
| [rag-v0/](rag-v0/) | 2026-06-16 | [auditoría RAG 2026-08-02](../auditoria-rag-respuestas-sota-2026-08-02.md) y [plan de síntesis](../plan-rag-sintesis-corpus.md) | Evidencia del RAG/VecQuant anterior al pivote y decisiones que explican el diseño heredado. |

Los enlaces relativos internos de los snapshots pueden apuntar a su antigua ubicación
en el root de `docs/`. Se conservan como evidencia histórica y no se reescriben como
si fueran documentación vigente.

## Política

- Archivar un documento solo cuando exista un sustituto explícito.
- Conservar fecha, estado y contexto del snapshot.
- No usar resultados históricos como verificación viva.
- No guardar boilerplate upstream, artefactos de build ni redirects sin contenido.
