# Alert Analyzer

A system that submits logs from external source to a local LLM (via Ollama) and returns a structured risk assessment.

---

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
  - [Option A — Docker Compose (recommended)](#option-a--docker-compose-recommended)
  - [Option B — Local Python environment](#option-b--local-python-environment)
- [Usage](#usage)
  - [Web dashboard](#web-dashboard)
  - [REST API](#rest-api)
  - [API documentation (Swagger)](#api-documentation-swagger)
- [Running tests](#running-tests)
- [Environment variables](#environment-variables)
- [Design decisions](#design-decisions)
- [Architecture](#Architecture)
- [Project files](#project-files)
- [What I would improve given more time](#what-i-would-improve-given-more-time)

---

## Overview

When an alert is submitted the system:

1. Validates the payload (Pydantic) and rejects it if it contains sensitive data (credentials, private keys, tokens).
2. Persists the alert to SQLite with `PENDING` status.
3. A background worker picks it up, calls the local LLM (Ollama), and validates the structured JSON response against the expected schema.
4. If the LLM response is invalid or malformed it retries up to 3 times before marking the alert as `ERROR`.
5. The final analysis — risk level, summary, recommended actions, confidence — is stored and pushed to all connected browser clients via Server-Sent Events.

---

## Installation

### Option A — Docker Compose (recommended)

Requires [Docker](https://docs.docker.com/get-docker/) with Compose v2.

```bash
# Clone the repo
git clone <repo-url>
cd job_test_3

# Create your local config from the template
cp .env.example .env
# Edit .env if you want to change the model or other settings

# Start both services (Ollama + Flask app)
docker compose up --build
```

On first run the Ollama container downloads the default model (`qwen2.5:1.5b`, ~1 GB). The Flask app waits for the model to be ready before accepting traffic. This can take several minutes depending on your internet connection.

The model is stored in a Docker volume (`ollama_data`) and is **not** re-downloaded on subsequent starts.

```bash
# Use a different model
OLLAMA_MODEL=llama3.2:3b docker compose up --build

# Run in background
docker compose up 

```

The app is available at `http://localhost:5000`.

---

### Option B — Local Python environment

Requires Python 3.12+ and a running [Ollama](https://ollama.com) instance.

```bash
# 1. Create your local config from the template
cp .env.example .env
# Edit .env if you want to change the model or other settings

# 2. Install Ollama and pull the model defined in .env
ollama pull qwen2.5:1.5b

# 3. Create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. Start the app
python app.py
```

The app listens on `http://localhost:5000`.


### API documentation (Swagger)

Full interactive documentation at `http://localhost:5000/apidocs/`.


## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen2.5:1.5b` | Model to use for analysis |
| `OLLAMA_TIMEOUT` | `25` | Per-request timeout in seconds |
| `OLLAMA_RATE_LIMIT_PER_MINUTE` | `20` | Max LLM calls per 60-second window |
| `DATABASE_URL` | `sqlite:///alerts.db` | SQLAlchemy connection string |


## Design decisions

### Technology choices
I chose technologies I already knew well — Flask, Swagger, SQLite, LangChain — so that I could focus on the problem itself rather than learning new tools. Working with familiar tools also makes it easier to spot and fix issues quickly, and to make manual adjustments when needed.

For the LLM, I opted for a lightweight local model via Ollama (`qwen2.5:1.5b`). This removes the need to configure external API credentials to test the project — just pull the model and run. It also means no alert data ever leaves the machine.

### Background worker thread, not async
Flask's default WSGI server is synchronous. A single daemon thread with a `queue.Queue` decouples alert submission from LLM processing without the complexity of migrating the whole application to asyncio or adding a broker. At this scale the tradeoff is correct.

### Schema validation on every LLM response
Small quantised models frequently emit JSON with wrong field values — e.g., `"risk_assessment": "CRITICAL"` or a `confidence` above 1.0. The Pydantic `AnalysisResult` model is run against every parsed response inside `_attempt_analysis()`. A validation failure raises `ValueError`, which feeds directly into the existing 3-attempt retry loop. This ensures the caller always receives either a fully conformant response or a clearly marked `ERROR`.

### JSON extraction pipeline
Models often wrap their output in prose or Markdown fences regardless of instructions. `_normalize_response` uses a greedy `{.*}` regex (DOTALL) to extract the JSON object from surrounding text. `_parse_json_safe` then attempts standard parsing and falls back to replacing single quotes with double quotes — a frequent model error. Only after both steps fail is an exception raised and a retry triggered.

### Sensitive-data scanning at the API boundary
Credentials, private keys, and API tokens must never reach the LLM context or the database. The scan (`security.py`) runs against the raw payload before the alert is written to SQLite, so a rejection is immediate and nothing is persisted.

### SSE over WebSockets
Status updates are unidirectional (server → browser). SSE is simpler to implement, works over plain HTTP without a protocol upgrade, and requires no additional infrastructure. A per-subscriber `queue.Queue` with `maxsize=32` prevents a slow client from blocking the publisher.

### Subprocess isolation for `/health/run`
Running pytest in-process would let test fixtures — which rebind `SessionLocal` and mock `generate_analysis` — corrupt the live application's globals for the duration of the suite. A subprocess runs in its own interpreter so the production state is never touched.

### SQLite with write retry
SQLite is sufficient for the expected load and avoids a Postgres dependency. `commit_with_retry` handles the `SQLITE_BUSY` race that occurs when the background thread and an HTTP handler both try to write simultaneously, retrying up to 3 times with a short backoff.

---

## Architecture

The entire project runs inside Docker Compose with two services:

```
┌─────────────────────────────────────────────────┐
│                  Docker Compose                  │
│                                                  │
│  ┌──────────────────┐   ┌──────────────────────┐ │
│  │   ollama service │   │     app service       │ │
│  │                  │   │                       │ │
│  │  Ollama server   │◄──│  Flask API            │ │
│  │  (LLM model)     │   │  Background worker    │ │
│  │                  │   │  SQLite database      │ │
│  │  Volume:         │   │                       │ │
│  │  ollama_data     │   │  Volume:              │ │
│  │  (model files)   │   │  app_data (alerts.db) │ │
│  └──────────────────┘   └──────────────────────┘ │
│                                                  │
└─────────────────────────────────────────────────┘
              │
        localhost:5000
```

- The **ollama service** runs the LLM locally. The model is downloaded on first start and kept in a Docker volume so it survives container restarts.
- The **app service** runs the Flask API. It connects to Ollama via the internal Docker network, processes alerts through a background worker thread, and persists everything to a SQLite database stored in a separate volume.
- The app service only starts after the Ollama healthcheck passes (model fully downloaded and ready).
- All configuration (model name, timeouts, database URL) is read from the `.env` file.

---

## Project files

### Root

**`app.py`**
Flask server. Defines all REST API routes (`/analyze`, `/analysis/<id>`, `/alerts`, `/alerts/retry-errors`, `/alerts/<id>/retry`, `/schema/alert`, `/schema/analysis`, `/stream`, `/health`, `/health/run`). Also contains the background worker that consumes the pending alert queue and the SSE publisher for real-time browser updates.

**`config.py`**
Single point of environment variable access. Loads `.env` via python-dotenv and exposes all settings as typed constants: `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`, `OLLAMA_RATE_LIMIT`, `MAX_RETRIES`, `DATABASE_URL`. All other modules import from here — none call `os.getenv()` directly.

**`llm_service.py`**
LLM integration via LangChain + Ollama. Contains the system prompt (SOC/DFIR analyst role), the JSON extraction and normalisation pipeline, Pydantic schema validation of the model response, and the retry loop (up to `MAX_RETRIES` attempts). Exports `generate_analysis()`, called by the worker in `app.py`.

**`db.py`**
Database setup via SQLAlchemy. Defines the `Alert` model (table `alerts`) with all columns (id, source, severity, description, artifacts, status, analysis_result, timestamps) and `init_db()` which creates the tables on first run.

**`models.py`**
Pydantic schemas for input and output validation: `AlertCreate` validates the `POST /analyze` body; `AnalysisResult` validates the LLM response (risk_assessment, summary, recommended_actions, confidence); `AlertResponse` is the full alert return schema for the API.

**`security.py`**
Regex-based sensitive data scanner. Detects credentials (`password=`, `token=`, `api_key=`...), PEM private keys, AWS access keys, GitHub/Google/Slack tokens, connection strings with embedded credentials, and `Authorization` headers. Called before persisting any alert to ensure secrets never reach the database or the LLM context.

**`tests_runner.py`**
Subprocess pytest runner used by the `/health/run` endpoint. Runs the test suite in isolation (without touching the live application's globals) and writes the result to a temporary JSON file, which the endpoint reads and returns as the response.

**`requirements.txt`**
Python dependencies with pinned versions: Flask, Flasgger (Swagger), SQLAlchemy, Pydantic, LangChain (core + Ollama), python-dotenv, pytest.

**`.env.example`**
Template for the `.env` file, committed to git as a reference for new developers. Copy to `.env` and adjust the values.

### Docker

**`Dockerfile`**
Docker image for the Flask application. Based on `python:3.12-slim`, installs dependencies from `requirements.txt`, copies the source code, and exposes port 5000.

**`ollama.Dockerfile`**
Docker image for the Ollama server. Extends the official `ollama/ollama` image and adds the custom entrypoint script.

**`ollama-entrypoint.sh`**
Ollama container startup script. Starts the Ollama server in the background, waits for it to be ready, pulls the model defined in `OLLAMA_MODEL` (if not already in the volume), and signals readiness by creating `/tmp/model-ready` (used by the Docker Compose healthcheck).

**`docker-compose.yml`**
Orchestrates both services: `ollama` (model server) and `app` (Flask). The `app` service only starts after the `ollama` healthcheck passes. Volumes persist the database and downloaded models across container restarts. Reads all configuration from the `.env` file automatically.

### Tests

**`tests/test_app.py`**
Integration tests for the Flask routes. Uses a temporary in-memory SQLite database and mocks the worker and LLM to test payload validation, alert creation, unique IDs, filters, schema endpoints, invalid field rejection, and the `/health/run` endpoint (including timeout and error cases).

**`tests/test_llm_service.py`**
Unit tests for the LLM service. Covers `_build_user_message`, `_normalize_response`, `_parse_json_safe`, `_attempt_analysis` (with ChatOllama mocked) and `generate_analysis` (retry, fallback, recovery after transient failure). Includes a real connectivity test against the local Ollama instance and rate limiter tests.

**`tests/test_security.py`**
Unit tests for the sensitive data scanner. Organised by category: credential key=value pairs, PEM private keys, AWS access keys, connection strings, GitHub/Google/Slack tokens, Authorization headers. Also covers cases that should **not** be flagged (keyword mention without an assignment, value too short, etc.).

---

## What I would improve given more time

### Authentication and authorisation
Every endpoint is open. At minimum, API key authentication checked in a `before_request` hook and a basic read-only vs. submit role model are required before any real deployment.

### Improve the analysis prompt
The current prompt already meets some demands, but it would need significant refinement to function more perfectly.

### Improve the code as a whole
Simplify the entire code structure, making it easier to understand and simpler to solve future problems.

### Implement more consistent tests and lifechecks
Adjust the lifechecks so that they are not unit tests and more clearly show when something is not working.

