---
type: "note"
---
简洁通用的群体智能引擎，预测万物

## ⚡ 项目概述

**MiroFish** 是一款基于多智能体技术的新一代 AI 预测引擎。通过提取现实世界的种子信息（如突发新闻、政策草案、金融信号），自动构建出高保真的平行数字世界。在此空间内，成千上万个具备独立人格、长期记忆与行为逻辑的智能体进行自由交互与社会演化。你可透过「上帝视角」动态注入变量，精准推演未来走向——**让未来在数字沙盘中预演，助决策在百战模拟后胜出**。

> 你只需：上传种子材料（数据分析报告或者有趣的小说故事），并用自然语言描述预测需求\
> MiroFish 将返回：一份详尽的预测报告，以及一个可深度交互的高保真数字世界

### 我们的愿景

MiroFish 致力于打造映射现实的群体智能镜像，通过捕捉个体互动引发的群体涌现，突破传统预测的局限：

* **于宏观**：我们是决策者的预演实验室，让政策与公关在零风险中试错

* **于微观**：我们是个人用户的创意沙盘，无论是推演小说结局还是探索脑洞，皆可有趣、好玩、触手可及

从严肃预测到趣味仿真，我们让每一个如果都能看见结果，让预测万物成为可能。

⠀

## 🔄 工作流程

1. **图谱构建**：现实种子提取 & 个体与群体记忆注入 & GraphRAG构建

2. **环境搭建**：实体关系抽取 & 人设生成 & 环境配置Agent注入仿真参数

3. **开始模拟**：双平台并行模拟 & 自动解析预测需求 & 动态更新时序记忆

4. **报告生成**：ReportAgent拥有丰富的工具集与模拟后环境进行深度交互

5. **深度互动**：与模拟世界中的任意一位进行对话 & 与ReportAgent进行对话

## 🚀 快速开始

### 一、源码部署（推荐）

#### 前置要求

| 工具          | 版本要求         | 说明            | 安装检查               |
| ----------- | ------------ | ------------- | ------------------ |
| **Node.js** | 18+          | 前端运行环境，包含 npm | `node -v`          |
| **Python**  | ≥3.11, ≤3.12 | 后端运行环境        | `python --version` |
| **uv**      | 最新版          | Python 包管理器   | `uv --version`     |

#### 1. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入必要的 API 密钥
```

**必需的环境变量：**

```env
# LLM API配置（支持 OpenAI SDK 格式的任意 LLM API）
# 推荐使用阿里百炼平台qwen-plus模型：https://bailian.console.aliyun.com/
# 注意消耗较大，可先进行小于40轮的模拟尝试
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Graphiti 配置（自托管或托管服务）
# 每月免费额度即可支撑简单使用：Graphiti 服务地址（示例）
GRAPHITI_API_KEY=your_graphiti_api_key
GRAPHITI_BASE_URL=http://localhost:8000
# 可选：启用 Thread API 兼容层（用于未来 AI 记忆会话管理）
GRAPHITI_THREAD_API_ENABLED=true
```

> Neo4j 为 Graphiti 部署层可选项：\
> \
> 你可以直接使用托管/已有 Graphiti 服务（仅配置 `GRAPHITI_API_KEY` + `GRAPHITI_BASE_URL`）\
> 若自建 Graphiti 且选择 Neo4j，再在 Graphiti 服务侧配置 Neo4j 连接即可（本仓库不提供 Docker 编排）

#### 本地化方案：Graphiti-Zep（替代 Zep Cloud）

MiroFish 提供完全本地化的知识图谱方案，使用 [Graphiti-Zep](https://github.com/makoshan/graphiti-zep) + Neo4j 替代 Zep Cloud，无需依赖任何云服务：

```bash
# 1. 安装并启动 Neo4j（Docker 或本地安装）
cd graphiti-zep && docker-compose up -d

# 2. 配置 graphiti-zep/.env（LLM、Embedding、Neo4j 连接信息）
cp graphiti-zep/.env.example graphiti-zep/.env

# 3. 启动 Graphiti-Zep 服务
cd graphiti-zep && uv sync && uv run graphiti-zep
```

Graphiti-Zep 是 Zep Cloud 知识图谱 API 的本地替代，支持：

* **Zep 兼容 REST API** — 与 Zep Cloud 相同的接口，MiroFish 无缝切换

* **任意 LLM** — Kimi、Claude（Anthropic 兼容）、Qwen、Moonshot（OpenAI 兼容）等

* **完全自托管** — 数据全部存储在本地 Neo4j，无需外部云服务

* **自动重试** — 速率限制和超时自动退避重试

详细配置参考：[本地 Graphiti + Neo4j 配置指南](./docs/local-graphiti-neo4j.md) | [Graphiti-Zep 项目文档](https://github.com/makoshan/graphiti-zep)

#### 2. 安装依赖

```bash
# 一键安装所有依赖（根目录 + 前端 + 后端）
npm run setup:all
```

或者分步安装：

```bash
# 安装 Node 依赖（根目录 + 前端）
npm run setup

# 安装 Python 依赖（后端，自动创建虚拟环境）
npm run setup:backend
```

#### 3. 启动服务

```bash
# 同时启动前后端（在项目根目录执行）
npm run dev
```

**服务地址：**

* 前端：`http://localhost:3000`

* 后端 API：`http://localhost:5001`

**单独启动：**

```bash
npm run backend   # 仅启动后端
npm run frontend  # 仅启动前端
```

### 二、Docker 部署

```bash
# 1. 配置环境变量（同源码部署）
cp .env.example .env

# 2. 拉取镜像并启动
docker compose up -d
```

默认会读取根目录下的 `.env`，并映射端口 `3000（前端）/5001（后端）`

> 在 `docker-compose.yml` 中已通过注释提供加速镜像地址，可按需替换

⠀

## 📄 致谢

MiroFish 的仿真引擎由 **[OASIS](https://github.com/camel-ai/oasis)** 驱动，我们衷心感谢 CAMEL-AI 团队的开源贡献！

##

⠀