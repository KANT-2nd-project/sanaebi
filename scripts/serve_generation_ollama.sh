#!/usr/bin/env bash
# Opt-in local experiment runtime; leaves the system Ollama service unchanged.
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
    echo 'ollama executable not found' >&2
    exit 1
fi

# Reuse installed model files; do not download or prune shared models.
export OLLAMA_MODELS="${OLLAMA_MODELS:-/usr/share/ollama/.ollama/models}"
if [[ ! -d "$OLLAMA_MODELS/manifests" ]]; then
    echo "No installed Ollama model manifests at: $OLLAMA_MODELS" >&2
    exit 1
fi
export OLLAMA_HOST=127.0.0.1:11435
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q4_0
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NO_CLOUD=1
export OLLAMA_NOPRUNE=1
# Installed Ollama 0.33.3 llama backend: reserve 256 MiB for automatic fitting.
# Actual GPU placement must be checked again after hardware/runtime changes.
export LLAMA_ARG_FIT_TARGET=256
exec ollama serve
