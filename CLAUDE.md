# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup
```bash
npm run setup:all        # Install all dependencies (frontend + backend + graphiti-zep)
npm run setup            # Frontend only
npm run setup:backend    # Backend only (uses uv)
npm run setup:graphiti   # graphiti-zep only (uses uv)
```

### Development
```bash
npm run dev              # Start ALL services: Neo4j + pi-proxy + graphiti-zep + backend + frontend
npm run dev:app          # Start only frontend (port 3000) and backend (port 5001)
npm run frontend         # Frontend only
npm run backend          # Backend only: cd backend && uv run python run.py
npm run build            # Production build
```

### Testing
```bash
cd backend && uv run pytest tests/
uv run pytest tests/test_graphiti_client_contract_standalone.py  # Contract tests (no external deps)
```

### Graphiti-Zep (Knowledge Graph API)
```bash
# Start pi proxy first (routes LLM calls through pi CLI → Kimi Coding API):
cd graphiti-zep && uv run python pi_proxy.py &

# Then start graphiti-zep:
cd graphiti-zep && uv run graphiti-zep
```

## Architecture

MiroFish is a multi-agent swarm simulation engine. Users upload seed documents, define a prediction scenario, and the system builds a knowledge graph, generates agent personas, runs a social simulation (via CAMEL-AI OASIS), and produces analysis reports.

### Three-Phase Workflow
1. **Graph Build**: Documents → LLM entity/ontology extraction → Graphiti knowledge graph
2. **Env Setup**: Graph entities → Agent persona generation → Simulation config
3. **Simulation**: OASIS multi-agent execution → Report generation + agent interview

### Backend (`backend/app/`)
- **`api/`**: Flask blueprints — `graph` (`/api/graph/`), `simulation` (`/api/simulation/`), `report` (`/api/report/`)
- **`services/`**: Core logic — `graph_builder.py`, `simulation_runner.py`, `simulation_manager.py`, `oasis_profile_generator.py`, `report_agent.py`, Graphiti/Zep wrappers
- **`config.py`**: Centralized env loading; supports OpenAI SDK format or Anthropic-compatible APIs (`LLM_API_STYLE=anthropic`)
- Long-running ops (graph build, profile generation) run in background threads and expose task-status polling endpoints

### Frontend (`frontend/src/`)
- Vue 3 + Vite; multi-step wizard (`Step1`–`Step5` components) orchestrated in `MainView.vue`
- **`api/`**: Axios clients for graph/simulation/report with 5-minute timeout and retry logic
- `GraphPanel.vue`: D3.js interactive knowledge graph visualization

### `graphiti-zep/`
Standalone Zep-compatible knowledge graph API backed by Graphiti + Neo4j. Separate open-source project ([GitHub](https://github.com/makoshan/graphiti-zep)).

## Configuration

**Single source of truth**: Copy `.env.example` to `.env` at the repo root. LLM config (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`) is shared by both backend and graphiti-zep — only edit it in the root `.env`.

```env
LLM_API_STYLE=openai
LLM_API_KEY=...
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

GRAPHITI_API_KEY=local-graphiti
GRAPHITI_BASE_URL=http://127.0.0.1:8000
GRAPHITI_THREAD_API_ENABLED=true
```

graphiti-zep has its own `graphiti-zep/.env` for Neo4j and embedding config only. LLM keys fall through to `../.env` automatically.

> If `LLM_BOOST_*` keys are present but contain placeholder values, backend startup will fail. Either fill them in or remove those lines entirely.
