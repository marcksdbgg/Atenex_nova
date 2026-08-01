# Frontend de Atenex Nova

Estado: **Implemented / Historical scope**.

Esta aplicación React 19 + TypeScript + Vite es la interfaz del RAG documental
existente. Incluye navegación de colecciones, chat, evidencia, citas, inspección de
documentos, observabilidad, evaluación y jobs. No es una interfaz para Repo Context
MCP y no se ampliará con esa finalidad durante v1.

## Desarrollo

```bash
npm install
npm run dev
```

El backend se espera en `http://127.0.0.1:8000` salvo configuración distinta.

## Verificación

```bash
npm run build
npm run lint
```

`npm run build` incluye la comprobación TypeScript.

## Estructura

- `src/App.tsx`: rutas.
- `src/pages/Pages.tsx`: páginas principales.
- `src/services/api.ts`: cliente HTTP y fallbacks.
- `src/components/`: chat, evidencia, citas, árbol documental y visor.
- `src/styles/`: tokens y estilos globales.

Para trabajo visual, leer primero
[`design-system/atenex-nova/MASTER.md`](../design-system/atenex-nova/MASTER.md) y el
override correspondiente bajo `design-system/atenex-nova/pages/`.

## Límites

- La API HTTP vigente está en [`docs/api-endpoints.md`](../docs/api-endpoints.md).
- El contrato Repo Context está en
  [`docs/baseline.md`](../docs/baseline.md).
- MCP y CLI son superficies independientes; el frontend no debe importarlas ni
  duplicar su lógica.
