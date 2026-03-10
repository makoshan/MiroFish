# 本地 Graphiti + Neo4j 配置指南

本文档记录 MiroFish 在本地接通 `Neo4j + Graphiti` 的完整过程，以及当前仓库中的落地方式。

## 目标架构

- `MiroFish Frontend`: `http://127.0.0.1:3000`
- `MiroFish Backend`: `http://127.0.0.1:5001`
- `Local Graphiti Compat`: `http://127.0.0.1:8000`
- `Neo4j HTTP`: `http://127.0.0.1:7474`
- `Neo4j Bolt`: `neo4j://127.0.0.1:7687`

当前仓库没有直接内置官方 Graphiti Docker 编排，因此这里采用的是：

1. 本机安装 Neo4j
2. 仓库内启动一个 `local_graphiti` 兼容服务
3. 兼容服务对外暴露 MiroFish 需要的 `/v1/groups/...` 路由
4. 兼容服务底层调用 `graphiti-core + Neo4j`

## 一、Neo4j 本地安装与启动

### 1. 安装

```bash
brew install neo4j
```

这会同时安装：

- `neo4j`
- `openjdk@21`
- `cypher-shell`

### 2. 启动服务

```bash
brew services start neo4j
```

### 3. 验证端口

```bash
curl http://127.0.0.1:7474
/opt/homebrew/bin/cypher-shell -a neo4j://127.0.0.1:7687 -u neo4j -p '你的密码' 'RETURN 1 AS ok;'
```

### 4. 当前本地凭证

- 用户名：`neo4j`
- 密码：见本机实际配置

如果需要重置密码，可停服务后修改，或临时关闭认证后用 `cypher-shell` 执行：

```cypher
ALTER USER neo4j SET PASSWORD 'new_password' CHANGE NOT REQUIRED
```

## 二、Graphiti 兼容服务

### 1. 目录

兼容服务位于：

- `local_graphiti/`
- 入口文件：`local_graphiti/graphiti_compat/app.py`

### 2. 作用

这个服务不是官方 Graphiti server 的原样拷贝，而是一个与 MiroFish 当前客户端协议对齐的本地兼容层，主要暴露：

- `POST /v1/groups`
- `POST /v1/groups/{group_id}/ontology`
- `POST /v1/groups/{group_id}/episodes:batch`
- `GET /v1/groups/{group_id}/nodes`
- `GET /v1/groups/{group_id}/edges`
- `GET /v1/nodes/{node_uuid}`
- `GET /v1/nodes/{node_uuid}/edges`
- `GET /v1/edges/{edge_uuid}`
- `POST /v1/groups/{group_id}/search`
- `GET/POST/DELETE /v1/threads...`

### 3. 安装依赖

```bash
cd local_graphiti
uv sync --python 3.12
```

### 4. 环境变量

复制示例：

```bash
cp local_graphiti/.env.example local_graphiti/.env
```

#### 推荐配置：LLM 用 Kimi，Embedding 用 OpenAI 兼容 key

```env
GRAPHITI_API_KEY=local-graphiti
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password

LLM_API_STYLE=anthropic
LLM_API_KEY=your_kimi_key
LLM_BASE_URL=https://api.kimi.com/coding
LLM_MODEL_NAME=kimi-for-coding
LLM_SMALL_MODEL_NAME=

EMBEDDING_API_KEY=your_embedding_key
EMBEDDING_BASE_URL=
EMBEDDING_MODEL_NAME=text-embedding-3-small

HOST=127.0.0.1
PORT=8000
```

说明：

- `LLM_API_STYLE=anthropic` 时，兼容服务会使用 Anthropic SDK 风格调用模型，适配 Kimi Code 这类 Anthropic 兼容接口
- `LLM_BASE_URL` 对 Kimi 应填写根路径 `https://api.kimi.com/coding`，不要手动补 `/v1` 或 `/messages`
- `LLM_SMALL_MODEL_NAME` 可选，用于覆盖 Graphiti 内部较轻量的抽取步骤；留空时默认复用 `LLM_MODEL_NAME`
- `EMBEDDING_*` 独立于 `LLM_*`，用于向量化，不再和抽取用 LLM 共用一套 key
- 当前实现里，Embedding 仍要求 OpenAI 兼容接口

### 5. 启动

```bash
cd local_graphiti
uv run uvicorn graphiti_compat.app:app --host 127.0.0.1 --port 8000
```

### 6. 健康检查

```bash
curl http://127.0.0.1:8000/healthcheck
```

## 三、MiroFish 根目录配置

根目录 `.env` 中 Graphiti 相关配置应指向本地兼容服务：

```env
GRAPHITI_API_KEY=local-graphiti
GRAPHITI_BASE_URL=http://127.0.0.1:8000
GRAPHITI_TRUST_ENV=false
GRAPHITI_TIMEOUT_SECONDS=60
GRAPHITI_THREAD_API_ENABLED=true
```

如果 MiroFish 主业务 LLM 也使用 Kimi，可继续保留：

```env
LLM_API_STYLE=anthropic
ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
ANTHROPIC_API_KEY=your_kimi_key
ANTHROPIC_MODEL=kimi-for-coding
LLM_TRUST_ENV=false
```

## 四、完整启动顺序

### 1. 启动 Neo4j

```bash
brew services start neo4j
```

### 2. 启动 local_graphiti

```bash
cd local_graphiti
uv run uvicorn graphiti_compat.app:app --host 127.0.0.1 --port 8000
```

### 3. 启动 MiroFish 后端

```bash
cd backend
uv run python run.py
```

### 4. 启动前端

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 3000
```

## 五、当前已知边界

- Neo4j 和 Graphiti 兼容服务启动成功，不代表图谱构建一定成功
- 图谱写入依赖两类外部模型能力：
  - 抽取用 LLM
  - Embedding
- 如果 `LLM_API_KEY` 或 `EMBEDDING_API_KEY` 无效，`/v1/groups/{id}/episodes:batch` 会在写入时失败
- 如果 `GRAPHITI_BASE_URL` 不可达，MiroFish 会在 GraphRAG 构建阶段报 `Connection refused`

## 六、排障命令

### 检查 Neo4j

```bash
brew services list | rg '^neo4j'
curl http://127.0.0.1:7474
/opt/homebrew/bin/cypher-shell -a neo4j://127.0.0.1:7687 -u neo4j -p 'your_password' 'RETURN 1 AS ok;'
```

### 检查 local_graphiti

```bash
curl http://127.0.0.1:8000/healthcheck
curl -X POST http://127.0.0.1:8000/v1/groups \
  -H 'Authorization: Bearer local-graphiti' \
  -H 'Content-Type: application/json' \
  -d '{"group_id":"smoke","name":"Smoke","description":"test"}'
```

### 检查 MiroFish 后端

```bash
curl http://127.0.0.1:5001/health
```
