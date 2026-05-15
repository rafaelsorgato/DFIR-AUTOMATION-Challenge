#!/bin/sh
set -e

MODEL="${OLLAMA_MODEL}"

echo "[ollama] Starting server..."
ollama serve &
SERVER_PID=$!

echo "[ollama] Waiting for server to be ready..."
until ollama list > /dev/null 2>&1; do
    sleep 2
done
echo "[ollama] Server is ready."

if ollama list | grep -q "^${MODEL}"; then
    echo "[ollama] Model ${MODEL} already present, skipping pull."
else
    echo "[ollama] Pulling model: ${MODEL} (this may take several minutes on first run)..."
    ollama pull "${MODEL}"
    echo "[ollama] Model ${MODEL} pulled successfully."
fi

# Signal that the model is ready for the healthcheck
touch /tmp/model-ready

echo "[ollama] Ready. Waiting for server process..."
wait $SERVER_PID
