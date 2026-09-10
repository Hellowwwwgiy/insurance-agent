# Insurance Agent - 保险智能助手

基于 **LangChain + LangGraph + DeepSeek** 构建的保险行业 SQL 智能助手。采用**多 Agent 协作架构**（规则路由 Supervisor + 领域专家 Agent + 事实校验），支持自然语言转 SQL 并执行数据库查询，内置事实自检与重试机制，提供 CLI 交互、Web API（含流式 SSE）、LLM-as-Judge 语义评测、并发性能基准测试与 Docker 一键部署。

---

## 📋 目录

- [🎯 核心特性](#-核心特性)
- [🏗️ 架构设计](#️-架构设计)
- [🛠️ 技术栈](#️-技术栈)
- [📁 项目结构](#-项目结构)
- [🚀 快速开始](#-快速开始)
- [🧪 测试](#-测试)
- [🌐 Web API](#-web-api)
- [📊 语义评测](#-llm-as-judge-语义评测)
- [⚡ 性能基准](#-性能基准测试)
- [📈 可观测性](#-可观测性)
- [🐳 Docker 部署](#-docker-部署)
- [❓ 常见问题](#-常见问题)
- [📜 许可证](#-许可证)

---

## 🎯 核心特性

### 多 Agent 协作
- **规则路由 Supervisor**：基于关键词匹配（零 LLM 开销）将问题分发到对应领域专家
- **CustomerAgent**：客户基础数据查询（姓名、电话、地址、年龄等）
- **PolicyAgent**：保单/产品数据查询（保单号、保费、保额、状态等）
- **JoinAgent**：跨表 JOIN 复杂查询（客户 + 保单关联）
- **FactCheck Agent**：独立事实校验节点，自动拦截编造数据并触发重试（最多 2 次）

### 安全与可靠性
- **SQL 只读保护**：仅允许 `SELECT`/`WITH` 单条语句，拒绝多语句注入与写操作
- **事实校验闭环**：AI 回答与数据库原始结果交叉核验，不一致自动重写
- **多轮会话支持**：基于 session_id 的上下文记忆（最多 200 条消息）

### 工程能力
- **流式输出**：SSE 流式响应（route / agent_start / token / retry / done 事件）
- **三层可观测性**：结构化 JSON 日志 + 请求中间件 + LangChain Callback
- **Prometheus 指标**：`/metrics` 端点暴露 QPS、延迟 P50/P95、路由分布
- **离线测试**：57 条 pytest 全部零依赖运行（ScriptedChatModel + 内存 SQLite）

---

## 🏗️ 架构设计

```
用户问题
   │
   ▼
┌─────────────────────────────────────────────────┐
│           Supervisor（规则路由，零 LLM）          │
│  关键词匹配 → customer / policy / join           │
└─────────────────────────────────────────────────┘
   │
   ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Customer │  │  Policy  │  │   Join   │
│  Agent   │  │  Agent   │  │  Agent   │
└──────────┘  └──────────┘  └──────────┘
   │               │               │
   └───────────────┼───────────────┘
                   ▼
         ┌───────────────────┐
         │   SQL 工具集      │
         │ list_tables       │
         │ get_table_schema  │
         │ check_sql         │
         │ execute_sql(只读) │
         └───────────────────┘
                   │
                   ▼
         ┌───────────────────┐
         │  FactCheck Agent  │
         │  核验核心数据真实性 │
         └───────────────────┘
                   │
            ┌──────┴──────┐
            │  校验通过？  │
            └──────┬──────┘
              通过 │  未通过(≤2次)
                   ▼
              最终回答
```

**设计决策**：
- Supervisor 采用**纯规则路由**而非 LLM 路由，消除额外 LLM 调用延迟与费用
- 三个专家 Agent 共享同一套 SQL 工具，仅 system prompt 不同，实现业务域解耦
- FactCheck 独立于专家 Agent，形成「生成 → 校验 → 重试」闭环

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| LLM 框架 | LangChain 1.x（create_agent）· LangGraph |
| 大模型 | DeepSeek（OpenAI 兼容协议） |
| 数据库 | PostgreSQL 16 · SQLAlchemy 2.0 |
| Web 框架 | FastAPI · Uvicorn |
| 配置管理 | pydantic-settings · python-dotenv |
| 测试 | pytest · httpx |
| 部署 | Docker · Docker Compose |
| 可观测性 | 标准库 logging · Starlette Middleware · LangChain Callback |

---

## 📁 项目结构

```
insurance-agent/
├── main.py                # 程序入口（薄壳，逻辑见 agent/cli.py）
├── pyproject.toml         # 打包配置 + 依赖 + pytest 配置
├── requirements.txt       # 运行时依赖
├── .env.example           # 环境变量示例（不含密钥）
├── .dockerignore          # Docker 构建排除规则
├── Dockerfile             # Web API 镜像（python:3.13-slim + HEALTHCHECK）
├── docker-compose.yml     # app + postgres:16-alpine 编排
├── docker/
│   └── init.sql           # PostgreSQL 种子数据（297 客户 + 350 保单）
├── agent/                 # 核心包
│   ├── __init__.py        # 统一导出
│   ├── cli.py             # CLI 入口（测试用例 + 交互模式）
│   ├── api.py             # FastAPI Web API（/health、/query、/query/stream、/metrics）
│   ├── config.py          # pydantic-settings 配置类
│   ├── database.py        # SQLAlchemy Engine 创建
│   ├── sql_tools.py       # 手写 SQL 工具（只读保护：SELECT/WITH 单条）
│   ├── llm_factory.py     # DeepSeek LLM 与 Agent 创建
│   ├── self_check_agent.py# 多 Agent 工作流（Supervisor + 专家 + FactCheck）
│   ├── runner.py          # 测试用例执行 + 交互问答
│   ├── logger.py          # 日志系统
│   ├── observability.py   # 三层可观测性（日志 + 中间件 + Callback）
│   ├── eval_judge.py      # LLM-as-Judge 语义评测（200 条用例）
│   ├── benchmark.py       # 并发性能基准（offline/inprocess/http）
│   └── static/
│       └── index.html     # 前端聊天界面
└── tests/                 # pytest 测试（57 条，全离线）
    ├── conftest.py
    ├── test_agent_integration.py
    ├── test_api.py
    ├── test_config.py
    ├── test_eval_suite.py
    ├── test_self_check.py
    └── test_sql_tools.py
```

---

## 🚀 快速开始

### 1. 环境要求

- Python ≥ 3.11
- PostgreSQL ≥ 14（或使用 Docker Compose 自动启动）

### 2. 安装依赖

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -e ".[dev]"
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入以下配置：

| 变量 | 说明 | 示例 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-xxxxxxxx` |
| `DB_HOST` | 数据库主机 | `localhost` |
| `DB_PORT` | 数据库端口 | `5432` |
| `DB_NAME` | 数据库名 | `insurance_db` |
| `DB_USER` | 数据库用户 | `insurance` |
| `DB_PASSWORD` | 数据库密码 | `insurance_pass` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_DIR` | 日志目录 | `./logs` |

> ⚠️ API 密钥请勿提交到版本库，`.env` 已在 `.gitignore` 中排除。

### 4. 初始化数据库

使用 `docker/init.sql` 初始化表结构和种子数据（297 客户 + 350 保单）。

### 5. 运行 CLI

```bash
python main.py
# 或使用安装后的命令
insurance-agent
```

启动后自动执行预设测试用例，然后进入交互模式（输入 `quit`/`exit`/`q` 退出）。

---

## 🧪 测试

```bash
pytest -q
```

**全部测试离线运行**（ScriptedChatModel + 内存 SQLite），不消耗 API 额度，不依赖外部数据库。

**测试覆盖**：
- SQL 工具只读保护（拒绝 DROP/DELETE/UPDATE/多语句注入）
- 配置加载与校验
- 多 Agent 路由逻辑（customer/policy/join）
- FactCheck 校验与重试闭环
- Web API 端点（/health、/query、/query/stream）

---

## 🌐 Web API

### 启动服务

```bash
uvicorn agent.api:app --host 0.0.0.0 --port 8080
```

### 前端界面

访问 `http://localhost:8080/` 打开聊天界面，支持流式响应与多轮对话。

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 前端聊天界面 |
| `GET` | `/health` | 健康检查 |
| `GET` | `/metrics` | Prometheus 格式指标 |
| `POST` | `/query` | 非流式问答 |
| `POST` | `/query/stream` | 流式问答（SSE） |

#### POST /query

**请求**：
```json
{
  "question": "张三的电话号码是多少？",
  "session_id": "可选，用于多轮会话"
}
```

**响应**：
```json
{
  "answer": "张三的电话号码是 13800138000。",
  "verified": true,
  "attempts": 1,
  "session_id": "a1b2c3d4..."
}
```

#### POST /query/stream（SSE）

事件类型：
- `route`：Supervisor 路由结果
- `agent_start`：专家 Agent 开始执行
- `token`：流式 token
- `retry`：FactCheck 未通过，触发重试
- `done`：完成，返回最终答案与校验结果
- `session`：返回 session_id

**curl 示例**：
```bash
curl -N -X POST http://localhost:8080/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "张三有几份有效保单？"}'
```

### Swagger 文档

访问 `http://localhost:8080/docs` 查看交互式 API 文档。

---

## 📊 LLM-as-Judge 语义评测

使用同模型（DeepSeek, temperature=0）作为 Judge，从 4 个维度对 Agent 输出打分（每维 1-5 分，总分 20，通过线 ≥14）：

| 维度 | 说明 |
|------|------|
| Accuracy | 数据与数据库查询结果一致性 |
| Completeness | 是否完整回答所有子问题 |
| Conciseness | 有无冗余表述 |
| Safety | 有无泄露敏感信息 |

### 运行评测

```bash
# 默认 200 条用例，seed=42 可复现
python -m agent.eval_judge --limit 200 --seed 42
```

**评测结果**（参考）：
- 平均分：17.14/20（通过线 ≥14）
- 路由准确率：84.5%
- 安全评分：4.89/5
- P95 延迟：12.2s

**分 Agent 表现**：
| Agent | 用例数 | 平均分 | 通过率 |
|-------|--------|--------|--------|
| CustomerAgent | 74 | 17.49 | 94.6% |
| JoinAgent | 67 | 17.06 | 97.0% |
| PolicyAgent | 59 | 16.78 | 100% |

报告输出到 `tests/eval_judge_report.json` 和 `tests/eval_judge_report.md`。

> ⚠️ 同模型自评存在偏差，生产环境建议使用独立 Judge 模型。

---

## ⚡ 性能基准测试

支持三种模式的并发性能评测：

| 模式 | 说明 | 依赖 |
|------|------|------|
| `offline` | ScriptedChatModel + 内存 SQLite | 零依赖（默认） |
| `inprocess` | 直接调用 agent.stream() | .env + PostgreSQL |
| `http` | 打真实 FastAPI 端点 | 需先启动 uvicorn |

### 运行基准测试

```bash
# 离线模式（推荐，零依赖）
python -m agent.benchmark --mode offline

# 指定并发阶梯
python -m agent.benchmark --mode offline --concurrency 10,20,50 --total-per-tier 50
```

**离线测试结果**（参考）：
- 并发 10/20/50：错误率 0%，QPS 12-26

报告输出到 `tests/benchmark_report.json` 和 `tests/benchmark_report.md`。

---

## 📈 可观测性

三层可观测性架构（零额外依赖，全部使用标准库 + 框架内置钩子）：

### Layer 1：结构化 JSON 日志
- 每条日志携带 `trace_id` / `request_id` / `level` / `file`
- 通过 `OBS_ENABLED=false` 环境变量关闭

### Layer 2：RequestMiddleware
- 记录每个请求的耗时、状态码、路由分布
- SSE 流式响应额外统计事件数与 token 数
- 计算延迟 P50/P95（滑动窗口 500 样本）

### Layer 3：LangGraphCallback
- 捕获每次 LLM 调用的延迟与 token 用量
- 记录工具调用的输入输出

### Prometheus 指标

访问 `http://localhost:8080/metrics` 获取以下指标：
```
insurance_request_total 42
insurance_status_5xx_total 0
insurance_latency_p50_ms 125.3
insurance_latency_p95_ms 342.1
insurance_route_total{route="POST /query"} 42
```

---

## 🐳 Docker 部署

### 一键启动

```bash
docker compose up --build
```

启动后访问：
- 前端界面：http://localhost:8080
- API 文档：http://localhost:8080/docs
- 指标端点：http://localhost:8080/metrics

### 服务编排

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| app | 自定义构建 | 8080 | FastAPI 应用 |
| db | postgres:16-alpine | 5432 | PostgreSQL 数据库 |

**特性**：
- `python:3.13-slim` 基础镜像，含 HEALTHCHECK
- 生产镜像排除测试依赖
- app 依赖 db 的 `service_healthy` 条件启动
- `docker/init.sql` 自动初始化种子数据
- 日志与数据库数据通过 volume 持久化

### 环境变量

Docker Compose 从 `.env` 读取以下变量：
- `DEEPSEEK_API_KEY`（必填）
- `DB_USER`（默认 `insurance`）
- `DB_PASSWORD`（默认 `insurance_pass`）
- `DB_NAME`（默认 `insurance_db`）
- `LOG_LEVEL`（默认 `INFO`）
- `OBS_ENABLED`（默认 `true`）

---

## ❓ 常见问题

1. **数据库连接失败**
   - 检查 PostgreSQL 服务是否运行
   - 核对 `.env` 中 `DB_*` 配置是否正确

2. **LLM 初始化失败**
   - 确认 `DEEPSEEK_API_KEY` 有效
   - 检查网络连通性与代理设置

3. **查询无结果**
   - 查看日志，校验生成的 SQL 与库内数据是否匹配
   - 使用 `check_sql` 工具先验证 SQL 语法

4. **只读保护拒绝执行**
   - Agent 生成的 SQL 必须以 `SELECT` 或 `WITH` 开头
   - 仅允许单条语句，禁止 `;` 分隔的多语句

5. **测试失败**
   - 测试使用离线模式，不需要 API Key 和数据库
   - 确保已安装开发依赖：`pip install -e ".[dev]"`

---

## 扩展开发

- **更换数据源**：修改 `agent/database.py` 的连接 URI 与驱动
- **切换大模型**：修改 `agent/llm_factory.py` 中 `ChatOpenAI` 的 `model`/`base_url`
- **新增专家 Agent**：在 `self_check_agent.py` 中添加新的 system prompt 与路由规则
- **批量查询**：循环调用 `agent.invoke({"input": q, "messages": []})`

---

## 📜 许可证

本项目采用 MIT License 许可。
