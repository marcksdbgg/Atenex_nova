#!/usr/bin/env bash
set -euo pipefail

# Dedicated EmbeddingGemma runtime for the local RTX 4060. Keeping generation
# in Ollama and embeddings in this llama.cpp process avoids Ollama's ingestion
# scheduler overhead while using the exact same BF16 model weights.
embedding_source_model="${ATENEX_EMBEDDING_SOURCE_MODEL:-embeddinggemma:bf16-stock}"
embedding_host="${ATENEX_EMBEDDING_HOST:-127.0.0.1}"
embedding_port="${ATENEX_EMBEDDING_PORT:-11435}"
ollama_lib_dir="${ATENEX_OLLAMA_LIB_DIR:-/usr/lib/ollama}"

model_path="$(ollama show "$embedding_source_model" --modelfile | awk '$1 == "FROM" { print $2; exit }')"
if [[ -z "$model_path" || ! -f "$model_path" ]]; then
  echo "Embedding model blob not found for $embedding_source_model" >&2
  echo "Create the stable source tag with: ollama cp embeddinggemma:latest embeddinggemma:bf16-stock" >&2
  exit 1
fi

cuda_backend="$ollama_lib_dir/cuda_v13/libggml-cuda.so"
llama_server="$ollama_lib_dir/llama-server"
if [[ ! -x "$llama_server" || ! -f "$cuda_backend" ]]; then
  echo "Ollama llama.cpp CUDA runtime not found under $ollama_lib_dir" >&2
  exit 1
fi

export GGML_BACKEND_PATH="$cuda_backend"
export LD_LIBRARY_PATH="$ollama_lib_dir:$ollama_lib_dir/cuda_v13${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$llama_server" \
  --model "$model_path" \
  --host "$embedding_host" \
  --port "$embedding_port" \
  --ctx-size 2048 \
  --batch-size 2048 \
  --ubatch-size 1024 \
  --parallel 1 \
  --embedding \
  --gpu-layers 99 \
  --flash-attn on \
  --log-verbosity 1
