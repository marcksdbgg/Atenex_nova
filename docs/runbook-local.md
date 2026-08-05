# Runbook local de esta PC

Estado: **Implemented / Verified**. El 2026-07-31 se verificaron rutas, gestores,
procesos, puertos, conexión Claude MCP y apagado completo en esta estación Linux. El
2026-08-04 se revalidó el arranque Repo Context desde `client-romero` con el cliente
MCP oficial, Ollama y Qdrant; no se repitió por ello el arranque integral del RAG
documental.

Este runbook separa dos productos que comparten el repositorio:

- **Repo Context MCP**: el mapa de repositorios para Claude, Codex y Cursor. Su core
  offline solo necesita Python y SQLite, pero el contrato MCP vigente requiere
  además Ollama, Qdrant y una proyección semántica compatible. No necesita API ni
  frontend.
- **RAG documental heredado**: API FastAPI, worker, frontend React, Ollama y Qdrant.
  Se levanta únicamente cuando se desea usar o probar la aplicación documental.

## Estado limpio registrado

Al cerrar la sesión de trabajo del 2026-07-31 se detuvieron de forma ordenada:

- API/Uvicorn y sus hijos de recarga;
- frontend Vite y su terminal;
- tres procesos MCP ligados a `client-romero` y un worktree de Claude;
- el servicio systemd `ollama.service`;
- el contenedor `atenex-qdrant`, conservando el volumen
  `atenex_nova_qdrant_storage`.

Se confirmó que no quedaban procesos Atenex/MCP y que los puertos `5173`, `6333`,
`6334`, `8000` y `11434` estaban libres. No se borró ningún índice, modelo, volumen,
base de datos ni archivo fuente.

## Rutas y runtime de esta estación

```text
INSTALL_ROOT=/mnt/ssd/Atenex/Atenex_nova
PYTHON=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python
PYTHON_LIB=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib
MCP_LAUNCHER=/mnt/ssd/Atenex/Atenex_nova/backend/scripts/serve_repo_context_mcp.sh
TREE_SITTER_CACHE=/mnt/ssd/Atenex/Atenex_nova/.atenex/context/tree-sitter
```

El runtime portable Python 3.11 es la instalación que fue ejercitada en esta PC. El
contrato canónico del proyecto sigue siendo Python 3.12. No recrear estos entornos si
los ejecutables anteriores existen; consultar [operations.md](operations.md) para una
instalación desde cero.

## Arranque mínimo: solo Repo Context MCP

Repo Context requiere Ollama con `embeddinggemma` y Qdrant vivos. Verificarlos y, si
Qdrant está detenido, iniciar solo ese servicio:

```bash
systemctl is-active ollama.service
ollama list
sg docker -c 'docker compose up -d qdrant'
curl --fail --silent --show-error http://127.0.0.1:6333/collections
```

Claude consume `.mcp.json` y Cursor consume `.cursor/mcp.json`; ambos archivos ya
apuntan al launcher. Al abrir una conversación local en uno de esos clientes:

1. seleccionar el repositorio o worktree correcto;
2. el cliente ejecuta `serve_repo_context_mcp.sh . CHECKOUT_PRINCIPAL`;
3. el launcher comprueba que `.` pertenece al mismo repositorio Git y refresca
   incrementalmente el índice ligado a ese root;
4. el launcher completa o reutiliza la proyección semántica de esa generación;
5. el mismo proceso publica las seis herramientas por `stdio` solo si el sentinel
   semántico es compatible;
6. el proceso termina al cerrar la conversación o desconectar el servidor.

Si dos conversaciones arrancan sobre el mismo checkout al mismo tiempo, un lock
advisory en `<data-dir>/writer.lock` serializa la publicación SQLite y semántica. El
segundo launcher espera y después reutiliza el resultado compatible; no borrar el
archivo para “desbloquearlo”, porque la propiedad real pertenece al proceso vivo.

Verificación desde una terminal:

```bash
cd /mnt/ssd/Atenex/Atenex_nova
claude mcp list
```

Debe aparecer `repo-context` como `Connected`. El MCP no abre un puerto TCP. La
primera indexación de un repositorio o worktree nuevo puede tardar más; un snapshot
sin cambios usa el no-op incremental.

No debe existir otro `repo-context` con alcance de usuario. Claude Desktop puede
mantener ese proceso global con el `cwd` de otro proyecto y resolver el nombre
duplicado de forma inesperada. Para retirarlo y usar solo `.mcp.json`:

```bash
claude mcp remove --scope user repo-context
claude mcp list
```

Codex mantiene sus MCP en la configuración del usuario, no en `.mcp.json`. Registrar
Repo Context una sola vez con root relativo para que el proceso herede la carpeta de
cada sesión:

```bash
cd /mnt/ssd/Atenex/Atenex_nova
codex mcp add repo-context -- \
  /usr/bin/bash \
  /mnt/ssd/Atenex/Atenex_nova/backend/scripts/serve_repo_context_mcp.sh \
  .
codex mcp list
```

El launcher exige que `.` sea un checkout Git y deriva un sidecar independiente por
root. Los archivos MCP de proyecto pueden añadir el checkout principal esperado para
restringir el mismo launcher a ese repositorio y sus worktrees. Si ya existe un
registro con ese nombre, inspeccionarlo antes de reemplazarlo.

La primera ingesta semántica de un repositorio grande puede tardar varios minutos.
El registro local verificado añade en `~/.codex/config.toml`:

```toml
[mcp_servers.repo-context]
startup_timeout_sec = 900
```

El bloque conserva también `command` y `args`; no duplicarlo. Reiniciar MCP o abrir
una conversación nueva después de cambiar el registro.

Diagnóstico directo del índice de Atenex:

```bash
cd /mnt/ssd/Atenex/Atenex_nova
env \
  LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend \
  ATENEX_TREE_SITTER_CACHE_DIR=/mnt/ssd/Atenex/Atenex_nova/.atenex/context/tree-sitter \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python \
  -m atenex_nova.repo_context.presentation.cli \
  doctor --repo /mnt/ssd/Atenex/Atenex_nova --json
```

Para otro repositorio, su `.mcp.json` debe conservar el launcher absoluto anterior,
usar `.` como segundo argumento y la ruta absoluta de su checkout principal como
tercero. Cada root recibe un sidecar independiente bajo
`.atenex/context/repositories/`. El launcher rechaza un `cwd` de otra familia Git con
`repository binding mismatch`.

## Arranque completo del RAG documental

### 1. Servicios locales

Desde el root:

```bash
cd /mnt/ssd/Atenex/Atenex_nova
sudo systemctl start ollama.service
sudo docker compose up -d qdrant
```

Esto reutiliza:

- la unidad `/usr/lib/systemd/system/ollama.service`, modelos en
  `/var/lib/ollama` y puerto `127.0.0.1:11434`;
- el contenedor `atenex-qdrant`, imagen `qdrant/qdrant:latest`, puertos
  `6333/6334` y volumen persistente `atenex_nova_qdrant_storage`.

Comprobarlos antes de iniciar la aplicación:

```bash
systemctl is-active ollama.service
sudo docker compose ps qdrant
curl --fail --silent --show-error http://127.0.0.1:11434/api/tags
curl --fail --silent --show-error http://127.0.0.1:6333/collections
```

Los modelos configurados actualmente son `gemma4:12b` para generación y
`embeddinggemma` para embeddings. `ollama list` permite confirmar su presencia. Solo
si faltan y se acepta una descarga explícita:

```bash
ollama pull gemma4:12b
ollama pull embeddinggemma
```

### 2. API

En una terminal:

```bash
cd /mnt/ssd/Atenex/Atenex_nova/backend
env \
  LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python \
  -m uvicorn atenex_nova.main:app \
  --host 127.0.0.1 --port 8000 --reload
```

Verificar:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/health/dependencies
```

El perfil dev usa por defecto `backend/atenex_nova.db`. PostgreSQL no forma parte del
arranque local normal; levantarlo con `docker compose --profile prod up -d` cambia el
alcance operativo y requiere configurar explícitamente `ATENEX_DATABASE_URL`.

La configuración local ignorada por Git en `backend/.env` fija en esta estación el
reranker descargado, batch de embeddings 256, `debug=false` y guards estrictos para
LLM, embeddings, Qdrant y reranker. Conservar `require_visual=false` y
`require_ocr=false` para el corpus TXT; no copiar estas rutas absolutas a otra PC.

### 3. Worker documental

En otra terminal, usando el mismo entorno:

```bash
cd /mnt/ssd/Atenex/Atenex_nova/backend
env \
  LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python \
  -m atenex_nova.workers.main
```

Solo debe existir un worker sobre la SQLite local; el proceso aplica un lock para
impedir consumidores duplicados.

### 4. Frontend

En una tercera terminal:

```bash
cd /mnt/ssd/Atenex/Atenex_nova/frontend
npm run dev -- --host 127.0.0.1
```

Abrir `http://127.0.0.1:5173`. El cliente usa la API en
`http://localhost:8000` por defecto. Definir `VITE_API_URL` antes de arrancar solo si
la API se encuentra en otro endpoint.

## Arranque persistente para una ingesta larga

Para dejar API, worker y frontend activos sin terminales abiertas durante un rebuild,
esta estación puede usar unidades transitorias del gestor systemd de usuario. No son
unidades habilitadas para el próximo reinicio; conservan logs en el journal y aplican
`Restart=on-failure` mientras dure la sesión del usuario.

```bash
systemd-run --user --unit=atenex-nova-api \
  --description='Atenex Nova API' \
  --working-directory=/mnt/ssd/Atenex/Atenex_nova/backend \
  --setenv=LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  --setenv=PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend \
  --property=Restart=on-failure --property=RestartSec=5s \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python \
  -m uvicorn atenex_nova.main:app --host 127.0.0.1 --port 8000

systemd-run --user --unit=atenex-nova-worker \
  --description='Atenex Nova Worker' \
  --working-directory=/mnt/ssd/Atenex/Atenex_nova/backend \
  --setenv=LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  --setenv=PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend \
  --property=Restart=on-failure --property=RestartSec=5s \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python \
  -m atenex_nova.workers.main

systemd-run --user --unit=atenex-nova-frontend \
  --description='Atenex Nova Frontend' \
  --working-directory=/mnt/ssd/Atenex/Atenex_nova/frontend \
  --property=Restart=on-failure --property=RestartSec=5s \
  /usr/bin/npm run dev -- --host 127.0.0.1
```

Verificación y logs:

```bash
systemctl --user is-active atenex-nova-api atenex-nova-worker atenex-nova-frontend
journalctl --user -u atenex-nova-worker -f
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

Detener solo estas unidades, sin tocar Ollama, Qdrant ni datos:

```bash
systemctl --user stop atenex-nova-frontend atenex-nova-worker atenex-nova-api
```

## Sincronización de la fuente Jesús G. Maestro

La fuente canónica es externa al blob store derivado:
`/mnt/ssd/Mark/Codes/transcriptex/output/Jesús G. Maestro`. No borrar esa ruta al
limpiar una colección. El 2026-08-02 se verificaron 2.071 vídeos indexados, 1.933 con
transcripción única, 91 piezas sin voz y 47 privadas/eliminadas. No quedó ningún
vídeo público con voz en estado `no_subtitles`.

Actualizar subtítulos y auditar:

```bash
cd /mnt/ssd/Mark/Codes/transcriptex
env LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/transcriptex \
  run 'https://www.youtube.com/@JesusGMaestro' \
  -o /mnt/ssd/Mark/Codes/transcriptex/output --lang-priority es,en --retries 3

env LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib \
  /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/transcriptex \
  audit '/mnt/ssd/Mark/Codes/transcriptex/output/Jesús G. Maestro' --json
```

`transcriptex asr` solo debe procesar `no_subtitles`; no usar `--include-failed` sin
cookies autorizadas por el propietario. Los vídeos musicales pueden terminar como
`no_speech`, que es un estado completo y no un fallo de corpus.

## Arranque rápido con ventanas Kitty

Después de iniciar Ollama y Qdrant, este bloque abre API, worker y frontend en
ventanas separadas. Cada ventana permanece visible para inspeccionar logs y se cierra
con `Ctrl+C` seguido de `exit`.

```bash
kitty --title "Atenex Nova · API" \
  --directory /mnt/ssd/Atenex/Atenex_nova/backend \
  bash -lc 'env LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python -m uvicorn atenex_nova.main:app --host 127.0.0.1 --port 8000 --reload; exec bash' &

kitty --title "Atenex Nova · Worker" \
  --directory /mnt/ssd/Atenex/Atenex_nova/backend \
  bash -lc 'env LD_LIBRARY_PATH=/mnt/ssd/Atenex/Atenex_nova/backend/.venv-context-runtime/usr/lib PYTHONPATH=/mnt/ssd/Atenex/Atenex_nova/backend /mnt/ssd/Atenex/Atenex_nova/backend/.venv-context/bin/python -m atenex_nova.workers.main; exec bash' &

kitty --title "Atenex Nova · Frontend" \
  --directory /mnt/ssd/Atenex/Atenex_nova/frontend \
  bash -lc 'npm run dev -- --host 127.0.0.1; exec bash' &
```

## Apagado ordenado

1. Detener frontend, worker y API con `Ctrl+C` en ese orden.
2. Cerrar las conversaciones o desconectar `repo-context`; los procesos MCP `stdio`
   deben terminar con sus clientes.
3. Detener proveedores, conservando datos:

```bash
cd /mnt/ssd/Atenex/Atenex_nova
sudo docker compose stop qdrant
sudo systemctl stop ollama.service
```

No usar `docker compose down -v`: `-v` elimina el volumen vectorial. No borrar
`.atenex/context`, `backend/atenex_nova.db`, `backend/storage` ni `/var/lib/ollama`
para un apagado normal.

Comprobación final:

```bash
pgrep -af 'atenex_nova|serve_repo_context_mcp|uvicorn|vite|npm run|ollama|qdrant'
ss -ltnp
systemctl is-active ollama.service
```

El primer comando debe quedar sin resultados y Ollama debe informar `inactive`. En
`ss` no deben aparecer los puertos `5173`, `6333`, `6334`, `8000` ni `11434`.

Si un MCP queda huérfano, inspeccionar primero su PID y comando completo; enviar
`kill -TERM PID` únicamente al PID confirmado. No usar un `pkill` amplio porque puede
cerrar otros agentes o runtimes Python.

## Problemas frecuentes

### `repo-context` aparece desconectado

```bash
cd /mnt/ssd/Atenex/Atenex_nova
claude mcp list
test -x backend/.venv-context/bin/python
test -x backend/scripts/serve_repo_context_mcp.sh
```

Ejecutar después el comando `doctor` de este runbook. Confirmar que el cliente usa
ambiente **Local**, abrió el root correcto y aprobó el servidor MCP del proyecto. Si
el warning menciona cierre durante `initialize`, revisar Ollama/Qdrant y ejecutar
`doctor`; los arranques concurrentes deben esperar el lock, no producir errores de
I/O de SQLite.

### Puerto ocupado

```bash
ss -ltnp
```

No cambiar puertos a ciegas. Identificar el PID, comprobar su comando y detener solo
el proceso propietario.

### Qdrant no inicia

```bash
cd /mnt/ssd/Atenex/Atenex_nova
sudo docker compose ps qdrant
sudo docker compose logs --tail=100 qdrant
```

No recrear ni eliminar el volumen como primera medida.

### Ollama responde pero falta un modelo

```bash
ollama list
```

La descarga de modelos requiere red y debe ser explícita. El Repo Context core sigue
funcionando aunque Ollama y Qdrant estén detenidos.

### Worker no procesa

Comprobar que API y worker usan el mismo `ATENEX_DATABASE_URL` y que no hay otro
worker conservando el lock. El archivo `backend/storage/worker.lock` puede persistir
tras un crash: el lock real es advisory y pertenece al proceso vivo, por lo que no se
debe borrar la SQLite ni ese archivo para intentar desbloquearlo. Revisar el PID, el
estado de la unidad y el journal antes de intervenir.

## Datos persistentes que deben preservarse

```text
backend/atenex_nova.db                 SQLite documental dev
backend/storage/                       uploads, páginas e índices locales
.atenex/context/                       sidecars Repo Context
Docker volume atenex_nova_qdrant_storage
/var/lib/ollama                        modelos Ollama administrados por systemd
```

El código, las pruebas y la configuración actual prevalecen sobre este snapshot si
alguna ruta o entry point cambia.
