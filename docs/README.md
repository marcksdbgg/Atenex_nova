# Documentación de Atenex Nova

Este índice separa autoridad, referencia técnica, evidencia, planes y archivo. El
código, las pruebas y la configuración actuales prevalecen sobre cualquier resumen.

## Estados permitidos

| Estado | Significado |
|---|---|
| **Implemented** | El artefacto o comportamiento existe en el checkout actual. |
| **Verified** | Una inspección, prueba o ejecución reproducible respalda el claim. |
| **Planned** | Es un objetivo aprobado todavía no entregado. |
| **Historical** | Registra un estado anterior y no describe el runtime vivo. |

`Planned` nunca prueba implementación y `Implemented` no implica por sí solo que una
capacidad haya sido revalidada.

## Autoridad vigente

| Documento | Rol |
|---|---|
| [README del repositorio](../README.md) | Snapshot operativo, quick start y últimas verificaciones. |
| [baseline.md](baseline.md) | Contrato de producto e invariantes. |
| [auditoria-completa.md](auditoria-completa.md) | Ledger breve de claim → estado → evidencia → gap. |
| [runbook-local.md](runbook-local.md) | Arranque y apagado exactos para esta estación Linux. |

## RAG documental

| Documento | Estado | Alcance |
|---|---|---|
| [architecture-backend.md](architecture-backend.md) | **Implemented** | Límites del backend y flujo documental. |
| [architecture-frontend.md](architecture-frontend.md) | **Implemented** | UI, contrato de confianza y gaps visibles. |
| [api-endpoints.md](api-endpoints.md) | **Implemented** | Contrato HTTP; OpenAPI vivo es la autoridad final. |
| [jobs-and-workers.md](jobs-and-workers.md) | **Implemented** | DAG y ejecución asíncrona. |
| [turboquant-integration.md](turboquant-integration.md) | **Implemented** | Cuantización e índices candidatos; aceleración opcional explícita. |
| [auditoría RAG 2026-08-02](auditoria-rag-respuestas-sota-2026-08-02.md) | **Verified** | Evidencia end-to-end, experimento Jesús G, tesis, EOS y contraste SOTA. |
| [ledger de síntesis de corpus](plan-rag-sintesis-corpus.md) | **Implemented** | Separa entregas verificadas en tests de las puertas G0–G6, que continúan **Planned** hasta validar un rebuild vivo y el benchmark. |

## Repo Context MCP

| Documento | Estado | Alcance |
|---|---|---|
| [architecture-repo-context.md](architecture-repo-context.md) | **Implemented** | Bounded context, puertos y composition root. |
| [indexing-and-storage.md](indexing-and-storage.md) | **Implemented** | Scanner, parsers, SQLite/FTS5 y generaciones atómicas. |
| [mcp-tools.md](mcp-tools.md) | **Implemented** | Contrato de las seis herramientas read-only. |
| [operations.md](operations.md) | **Implemented** | Instalación y operación portable. |
| [evaluation-repo-context.md](evaluation-repo-context.md) | **Verified** | Protocolo y evidencia de evaluación. |
| [plan-repo-context-mcp.md](plan-repo-context-mcp.md) | **Implemented** | Plan original y gates todavía abiertos. |

## Decisiones

Los ADR conservan por qué existen los límites actuales:

- [0001 — Repo Context como producto](decisions/0001-repository-context-product.md)
- [0002 — SQLite para el core](decisions/0002-sqlite-core-index.md)
- [0003 — Generaciones atómicas](decisions/0003-atomic-index-generations.md)
- [0004 — MCP read-only](decisions/0004-read-only-mcp-surface.md)
- [0005 — Autoridad del worktree](decisions/0005-source-worktree-authority.md)
- [0006 — Semántica opcional (Historical)](decisions/0006-optional-semantic-retrieval.md)
- [0007 — Semántica requerida](decisions/0007-required-semantic-retrieval.md)

## Archivo

[archive/README.md](archive/README.md) clasifica snapshots sustituidos. El plan
VecQuant anterior se conserva directamente en
[archive/rag-v0/plan-correccion-vecquant-operacional.md](archive/rag-v0/plan-correccion-vecquant-operacional.md),
sin un redirect adicional en la raíz.

## Precedencia y mantenimiento

1. `baseline.md` define el contrato.
2. `auditoria-completa.md` determina si cada claim está **Implemented**, **Verified**,
   **Planned** o es **Historical**.
3. El `README.md` raíz describe el estado operativo más reciente.
4. OpenAPI manda sobre `api-endpoints.md` para rutas HTTP; `mcp-tools.md` manda sobre
   resúmenes para la superficie MCP.
5. Los documentos especializados describen mecanismos; cifras de un runtime concreto
   pertenecen a una auditoría fechada.
6. Cuando cambie comportamiento, actualizar contrato, ledger, especialización y plan
   en el mismo cambio.
