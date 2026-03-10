# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup
```bash
npm run setup:all        # Install all frontend + backend dependencies
npm run setup            # Frontend only
npm run setup:backend    # Backend only (uses uv)
```

### Development
```bash
npm run dev              # Start both frontend (port 3000) and backend (port 5001)
npm run frontend         # Frontend only
npm run backend          # Backend only: cd backend && uv run python run.py
npm run build            # Production build
```

### Testing
```bash
cd backend && uv run pytest tests/
uv run pytest tests/test_graphiti_client_contract_standalone.py  # Contract tests (no external deps)
```

### Local Graphiti + Neo4j
```bash
# Required for graph memory features in local dev:
cd local_graphiti && uv run uvicorn graphiti_compat.app:app --host 127.0.0.1 --port 8000
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

### `local_graphiti/`
A local FastAPI compatibility service that implements the Graphiti/Zep HTTP protocol backed by Neo4j. Use when running without a managed Graphiti service.

## Configuration

Copy `.env.example` to `.env` at the repo root. Key variables:

```env
LLM_API_KEY=...
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# For Anthropic-style APIs (Kimi, Claude, etc.):
# LLM_API_STYLE=anthropic
# ANTHROPIC_BASE_URL=...
# ANTHROPIC_API_KEY=...
# ANTHROPIC_MODEL=...

GRAPHITI_API_KEY=local-graphiti
GRAPHITI_BASE_URL=http://127.0.0.1:8000
GRAPHITI_THREAD_API_ENABLED=true

# Optional boost LLM (omit entirely if unused — do not leave placeholder values):
# LLM_BOOST_API_KEY=...
# LLM_BOOST_BASE_URL=...
# LLM_BOOST_MODEL_NAME=...
```

> If `LLM_BOOST_*` keys are present but contain placeholder values, backend startup will fail. Either fill them in or remove those lines entirely.
