# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the Flask API and simulation engine. Keep HTTP routes in `backend/app/api/`, domain logic in `backend/app/services/`, shared helpers in `backend/app/utils/`, and lightweight data models in `backend/app/models/`. Put backend tests in `backend/tests/`.

`frontend/` is a Vue 3 + Vite app. Page-level screens live in `frontend/src/views/`, reusable UI in `frontend/src/components/`, API wrappers in `frontend/src/api/`, router setup in `frontend/src/router/`, and simple state in `frontend/src/store/`.

`local_graphiti/` is the optional local Graphiti-compatible service. `docs/` holds setup notes, and `static/` contains repo images used by the READMEs. Avoid committing generated content from `backend/uploads/`, `backend/logs/`, or `frontend/dist/` unless a release task requires it.

## Build, Test, and Development Commands
Run commands from the repo root unless noted:

- `npm run setup:all` installs root/frontend Node dependencies and syncs the backend `uv` environment.
- `npm run dev` starts the Flask backend on `:5001` and the Vite frontend on `:3000`.
- `npm run build` creates the frontend production bundle in `frontend/dist/`.
- `cd backend && uv run pytest tests` runs the backend test suite.
- `cd local_graphiti && uv run uvicorn graphiti_compat.app:app --host 127.0.0.1 --port 8000` starts the local Graphiti shim used by some integrations.
- `docker compose up -d` runs the packaged stack with `.env` settings.

## Coding Style & Naming Conventions
Match the existing codebase: Python uses 4-space indentation, type hints on public functions, and `snake_case` for modules, functions, and variables. Vue and JavaScript files use 2-space indentation, `camelCase` for functions/state, and PascalCase component filenames such as `HistoryDatabase.vue`.

Keep API files focused on request handling and push orchestration into `services/`. Prefer small, single-purpose utility modules over large mixed helpers. No repo-wide formatter is committed, so keep changes consistent with surrounding files and imports grouped simply.

## Testing Guidelines
Add backend tests under `backend/tests/` and name them `test_*.py`. The current suite uses standalone contract-style tests for Graphiti client behavior; follow that pattern when touching API integrations or pagination logic. Run `cd backend && uv run pytest tests` before opening a PR.

## Commit & Pull Request Guidelines
Recent history uses short conventional prefixes such as `feat(...)`, `fix(...)`, `docs:`, `test:`, and `style(...)`. Keep commits scoped and imperative, for example `fix(report_agent): handle empty tool output`.

PRs should describe the user-visible change, list config or environment updates, and include screenshots for frontend work. Link related issues when applicable and call out any required `.env` or Graphiti setup changes explicitly.
