# Insurance Agent - 保险行业 Text-to-SQL 多 Agent 智能助手

基于 **LangChain 1.x + LangGraph + DeepSeek** 构建的保险行业自然语言转 SQL 智能助手。采用**两层 StateGraph 多 Agent 协作架构**（外层规则路由编排图 + 内层 LangChain Agent 执行图），覆盖客户/保单/理赔/核保/续保五大保险核心业务域，内置事实自检与重试闭环，提供 CLI 交互、Web API（SSE 流式）、Spider 公开 Benchmark 评测、三层可观测性与 Docker 一键部署。

---

## 📋 目录

- [🎯 核心特性](#-核心特性)
- [🏗️ 顶层架构设计](#️-顶层架构设计)
  - [两层 StateGraph 嵌套](#两层-stategraph-嵌套)
  - [状态定义与图结构](#状态定义与图结构)
  - [多 Agent 协作流程](#多-agent-协作流程)
- [🗄️ 数据库设计](#️-数据库设计)
- [🔒 安全机制](#-安全机制)
- [📈 可观测性](#-可观测性)
- [🛠️ 技术栈](#️-技术栈)
- [📁 项目结构](#-项目结构)
- [🚀 快速开始](#-快速开始)
- [🌐 Web API](#-web-api)
- [🧪 测试](#-测试)
- [🎯 公开 Benchmark 评测（Spider）](#-公开-benchmark-评测spider)
- [⚡ 性能基准测试](#-性能基准测试)
- [🐳 Docker 部署](#-docker-部署)
- [❓ 常见问题](#-常见问题)
- [📜 许可证](#-许可证)

---

## 🎯 核心特性

### 多 Agent 协作
- **规则路由 Supervisor**：基于关键词匹配（零 LLM 开销）将问题分发到对应领域专家
- **CustomerAgent**：客户基础数据查询（姓名、电话、地址、年龄等）
- **PolicyAgent**：保单/产品数据查询（保单号、保费、保额、状态等）
- **ClaimAgent**：理赔记录查询（理赔号、理赔类型、申请/核准金额、状态等）
- **UnderwriteAgent**：核保记录查询（健康评分、风险等级、核保结论、加费比例等）
- **RenewalAgent**：续保记录查询（续保日期、折扣率、续保状态等）
- **JoinAgent**：跨表 JOIN 复杂查询（客户 + 保单 + 理赔 + 核保 + 续保多表关联）
- **FactCheck Agent**：独立事实校验节点，自动拦截编造数据并触发重试（最多 2 次）

### 安全与可靠性
- **SQL 只读保护**：仅允许 `SELECT`/`WITH` 单条语句，拒绝多语句注入与写操作
- **事实校验闭环**：AI 回答与数据库原始结果交叉核验，不一致自动重写（最多重试 2 次）
- **多轮会话支持**：基于 session_id 的上下文记忆（最多 200 条消息）

### 工程能力
- **流式输出**：SSE 流式响应（route / agent_start / token / retry / done 事件）
- **三层可观测性**：结构化 JSON 日志 + 请求中间件 + LangChain Callback
- **Prometheus 指标**：`/metrics` 端点暴露请求总量、5xx 数、延迟 P50/P95、路由分布
- **离线测试**：57 条 pytest 全部零依赖运行（ScriptedChatModel + 内存 SQLite）

---

## 🏗️ 顶层架构设计

### 两层 StateGraph 嵌套

本项目的核心编排引擎是 **LangGraph StateGraph**，采用**两层嵌套**结构：

```
┌─────────────────────────────────────────────────────────────────┐
│  第一层：自定义 StateGraph（外层编排图）                          │
│  StateGraph(SelfCheckState)                                      │
│  START → supervisor → specialist_node → verify_node → retry/END  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼  specialist_node 内部调用
┌─────────────────────────────────────────────────────────────────┐
│  第二层：LangChain create_agent 生成的图（内层执行图）            │
│  model + tools → Agent 节点 → Tool 节点循环                      │
└─────────────────────────────────────────────────────────────────┘
```

- **第一层（外层）**：项目自行用 `StateGraph` 构建的编排图，负责路由、专家分发、事实校验、重试决策。节点签名统一为 `(state) -> dict`。
- **第二层（内层）**：由 `langchain.agents.create_agent` 生成，内部封装了 LLM 调用与 SQL 工具循环。每个专家 Agent 共享同一套 SQL 工具集，仅 system prompt 不同。
- **FactCheck 不是 StateGraph**：事实校验是一个普通类 `FactCheckAgent`，在 `verify_node` 中被同步调用，不构成第三层图。

### 状态定义与图结构

状态使用 `TypedDict`（`SelfCheckState`）在节点间传递：

```python
class SelfCheckState(TypedDict):
    input: str           # 用户问题
    messages: List[Any]  # 历史会话
    attempts: int        # 已尝试次数
    final_output: str    # 专家 Agent 输出
    db_data: str         # SQL 查询原始结果
    specialist: str      # 路由结果：customer/policy/claim/...
    verified: bool       # FactCheck 是否通过
    issues: List[str]    # 校验发现的问题
    suggestion: str      # 修正建议
```

图构建代码（[self_check_agent.py](file:///d:/agent/insurance-agent/agent/self_check_agent.py)）：

```python
graph = StateGraph(SelfCheckState)
graph.add_node("supervisor", self._supervisor_node)
graph.add_node("specialist_node", self._run_specialist)
graph.add_node("verify_node", self._verify_node)

graph.add_edge(START, "supervisor")
graph.add_edge("supervisor", "specialist_node")
graph.add_edge("specialist_node", "verify_node")
graph.add_conditional_edges(
    "verify_node",
    self._should_retry,                    # 条件边
    {"retry": "specialist_node", "end": END},
)
return graph.compile()
```

### 多 Agent 协作流程

```
用户问题
   │
   ▼
┌─────────────────────────────────────┐
│  Supervisor（关键词路由，零 LLM）    │
│  → customer / policy / claim /      │
│    underwriting / renewal / join    │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│  对应领域专家 Agent（LangChain 图）  │
│  list_tables → get_table_schema →   │
│  check_sql → execute_sql            │
└─────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────┐
│  FactCheck 节点                     │
│  对比 AI 回答 vs 数据库原始结果      │
└─────────────────────────────────────┘
   │
   ├── verified=True  → END
   └── verified=False →
        ├── attempts < 2 → 带回 issues 重试 specialist_node
        └── attempts ≥ 2 → 追加免责声明后 END
```

**路由规则**（`_supervisor_route`）：纯关键词匹配，不调用 LLM。若命中 JOIN 关键词或同时涉及多个业务域（domain_count ≥ 2），走 JoinAgent。

---

## 🗄️ 数据库设计

使用 `docker/init.sql` 初始化表结构和种子数据，覆盖保险业务**五张核心表**：

| 表 | 说明 | 关键字段 | 种子规模 |
|----|------|----------|----------|
| `customers` | 客户基础信息 | name, phone, address, age | 300 |
| `policies` | 保单/产品 | policy_no, customer_id, product, premium, insured_amount, status | 353 |
| `claims` | 理赔记录 | claim_no, policy_id, claim_type, claim_amount, approved_amount, status | 119 |
| `underwriting` | 核保记录 | policy_id, health_score, risk_level, decision, extra_premium_rate | 353 |
| `renewal` | 续保记录 | policy_id, renewal_date, new_end_date, premium, status, discount_rate | 72 |

**外键关系**：
- `policies.customer_id` → `customers.id`
- `claims.policy_id` → `policies.id`
- `underwriting.policy_id` → `policies.id`
- `renewal.policy_id` → `policies.id`

支持跨表 JOIN 与聚合查询（如"张三的理赔总金额"、"高风险客户的核保结论分布"等）。

> 💡 **SQLite 自动降级**：`database.py` 中 `create_database_connection` 优先连 PostgreSQL，失败时自动切换到内存 SQLite + 相同五张核心表种子数据（`StaticPool` 单连接池），任何机器一行命令就能跑。生产环境推荐 PostgreSQL。

---

## 🔒 安全机制

### 1. SQL 只读保护（`sql_tools.py`）

`_validate_readonly` 函数对所有执行的 SQL 做三层校验：
1. **非空校验**：拒绝空语句
2. **单语句校验**：拒绝包含 `;` 的多语句（防 `SELECT 1; DROP TABLE` 注入）
3. **关键字校验**：仅允许以 `SELECT` 或 `WITH` 开头

```python
_READONLY_KEYWORDS = ("SELECT", "WITH")

def _validate_readonly(query: str) -> str:
    stmt = query.strip().rstrip(";").strip()
    if ";" in stmt:
        raise ValueError("不允许执行多条语句")
    keyword = stmt.split()[0].upper()
    if keyword not in _READONLY_KEYWORDS:
        raise ValueError(f"只允许只读查询，当前以 {keyword} 开头")
    return stmt
```

### 2. 事实校验闭环（`self_check_agent.py`）

`FactCheckAgent` 将 AI 最终回答与数据库原始查询结果对比，判定是否存在编造/篡改核心业务数据（姓名、保单号、金额等）。格式美化（加粗、换行、单位补充）不视为错误。

校验未通过时：
- 若 `attempts < MAX_RETRIES(2)`：将 `issues` + `suggestion` 拼入问题，重新调用专家 Agent
- 若重试耗尽：在回答末尾追加免责声明

---

## 📈 可观测性

三层可观测性架构（**零额外依赖**，全部使用标准库 + 框架内置钩子）：

### Layer 1：结构化 JSON 日志（`StructuredFormatter`）
- 每条日志输出单行 JSON，携带 `trace_id` / `request_id` / `level` / `file` / `msg`
- 使用 `contextvars.ContextVar` 传递 trace_id，跨异步调用保持链路追踪
- 通过 `OBS_ENABLED=false` 环境变量关闭

### Layer 2：RequestMiddleware（FastAPI 中间件）
- 记录每个请求的方法、路径、状态码、耗时
- 计算延迟 P50/P95（滑动窗口 500 样本）
- SSE 流式响应额外统计事件数与 token 数
- 全局单例 `_global_metrics` 供 `/metrics` 端点读取

### Layer 3：LangGraphCallback（LangChain CallbackHandler）
- `on_llm_start` / `on_llm_end`：记录 LLM 延迟与 token 用量（prompt_tokens / completion_tokens / total_tokens）
- `on_tool_start` / `on_tool_end`：记录工具调用与结果预览
- `on_llm_error`：记录 LLM 异常

### /metrics 端点
自实现的极简 Prometheus 格式指标（不依赖 prometheus_client），示例输出：
```
insurance_request_total 128
insurance_status_5xx_total 0
insurance_latency_p50_ms 320.5
insurance_latency_p95_ms 1840.2
insurance_route_total{route="POST /query/stream"} 64
```

---

## 🛠️ 技术栈

| 类别 | 技术 | 版本 |
|------|------|------|
| LLM | DeepSeek API（OpenAI 兼容协议） | deepseek-chat |
| Agent 框架 | LangChain | ≥1.3,<2 |
| 编排引擎 | LangGraph StateGraph | ≥1.2,<2 |
| Web 框架 | FastAPI + Uvicorn | ≥0.115 / ≥0.30 |
| ORM | SQLAlchemy | ≥2.0 |
| 数据库 | PostgreSQL 16 / SQLite（降级） | 16-alpine |
| 配置 | pydantic-settings | ≥2.0 |
| 容器 | Docker（python:3.13-slim） | - |

---

## 📁 项目结构

```
insurance-agent/
├── agent/                     # 核心包
│   ├── __init__.py            # 统一导出（load_environment/setup_logger/create_*）
│   ├── api.py                 # FastAPI Web API（/health、/query、/query/stream、/metrics）
│   ├── cli.py                 # CLI 入口（测试用例 + 交互模式）
│   ├── config.py              # pydantic-settings 配置类
│   ├── database.py            # SQLAlchemy Engine + PostgreSQL/SQLite 降级 + 种子数据
│   ├── sql_tools.py           # 手写 SQL 工具（只读保护：SELECT/WITH 单条）
│   ├── llm_factory.py         # DeepSeek LLM 与 base_agent 创建
│   ├── self_check_agent.py    # 两层 StateGraph 多 Agent + FactCheck 核心逻辑
│   ├── observability.py       # 三层可观测性（JSON日志/中间件/Callback）
│   ├── logger.py              # 日志文件配置（按日期滚动写入 logs/）
│   ├── runner.py              # CLI 预设测试用例执行器
│   ├── eval_judge.py          # LLM-as-Judge 语义评测（独立于 pytest 运行）
│   ├── eval_spider.py         # Spider dev 集 Text-to-SQL 评测脚本
│   ├── benchmark.py           # 并发性能基准测试
│   └── static/                # 前端聊天界面（HTML + JS）
├── tests/                     # 57 条 pytest（零依赖运行）
├── docker/
│   └── init.sql               # PostgreSQL 种子数据（五张核心表）
├── main.py                    # CLI 启动入口
├── pyproject.toml             # 项目元数据与构建配置
├── Dockerfile                 # python:3.13-slim + HEALTHCHECK
├── docker-compose.yml         # app + postgres:16-alpine 编排
├── requirements.txt
└── readme.md
```

---

## 🚀 快速开始

### 1. 环境要求
- Python 3.13+
- DeepSeek API Key

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
创建 `.env` 文件（`.env.example` 为模板，真实密钥勿提交）：
```env
DEEPSEEK_API_KEY=sk-your-key-here
DB_USER=insurance
DB_PASSWORD=insurance_pass
DB_HOST=localhost
DB_PORT=5432
DB_NAME=insurance_db
```

### 4. 初始化数据库
使用 `docker/init.sql` 初始化 PostgreSQL 表结构和种子数据。或直接运行（自动降级 SQLite）。

### 5. 启动 Web API
**一键启动**（不需要 PostgreSQL，自动降级 SQLite）：
```bash
.\run.bat          # Windows
```

**手动启动**：
```bash
uvicorn agent.api:app --host 0.0.0.0 --port 8080
```

启动后访问：http://localhost:8080

### 6. 运行 CLI
```bash
python main.py
```

---

## 🌐 Web API

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端聊天界面 |
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 格式指标 |
| POST | `/query` | 非流式问答 |
| POST | `/query/stream` | SSE 流式问答 |

### 请求体
```json
{
  "question": "张三有几份有效保单？",
  "session_id": "可选，多轮会话ID"
}
```

### SSE 事件类型
- `route`：Supervisor 路由结果
- `agent_start`：专家 Agent 开始执行
- `token`：流式输出的文本片段
- `retry`：FactCheck 未通过，触发重试
- `done`：最终回答（含 verified、attempts）
- `session`：会话 ID

### Swagger 文档
启动后访问 http://localhost:8080/docs

---

## 🧪 测试

57 条 pytest，全部零依赖运行（ScriptedChatModel 模拟 LLM + 内存 SQLite）：

```bash
pytest
```

测试覆盖：
- `test_sql_tools.py`：SQL 只读保护、注入拦截
- `test_self_check.py`：多 Agent 路由、FactCheck 重试闭环
- `test_api.py`：FastAPI 端点、SSE 流式
- `test_eval_suite.py`：L1-L4 链路 Rubric 评分（L4 SQL 安全 100%）
- `test_agent_integration.py`：端到端 Agent 集成

运行后自动生成 `tests/eval_baseline.json` 和 `tests/eval_report.md`（Rubric 综合分 + 回归 diff）。

### LLM-as-Judge 语义评测（可选，需 API Key）

独立于 pytest 的语义质量评测，用同一 DeepSeek 模型做 Judge（temperature=0），4 维度评分（准确性/完整性/简洁性/安全性，每维 1-5 分）：

```bash
python -m agent.eval_judge
```

结果写入 `tests/eval_judge_report.json` 和 `tests/eval_judge_report.md`。

> ⚠️ 同模型自评存在局限性，报告中已注明。

---

## 🎯 公开 Benchmark 评测（Spider）

为验证 Text-to-SQL 能力的真实水平，在 **Spider dev 集**上跑了公开评测。

### 评测结果

| 指标 | 数值 |
|------|------|
| 数据集 | Spider dev |
| 样本数 | 99（20 个数据库均匀采样） |
| **EX (Execution Accuracy)** | **62.6%** (62/99) |
| Executable Rate | 72.7% (72/99) |
| 模型 | DeepSeek deepseek-chat |

> EX = 生成 SQL 与标准答案 SQL 在同一数据库上执行，结果集一致（忽略行/列顺序）。

### 评测方法

1. 从 Spider 官方 `tables.json` 重建 SQLite schema，填充假数据并保证外键关联
2. 用 DeepSeek 生成 SQL，与 gold SQL 在同一库上执行对比结果集
3. 脚本：`agent/eval_spider.py`，报告：`spider_eval_report.md`

```bash
python -m agent.eval_spider --limit 100
```

---

## ⚡ 性能基准测试

支持三种模式的并发性能评测：

| 模式 | 说明 | 依赖 |
|------|------|------|
| `offline` | ScriptedChatModel + 内存 SQLite | 零依赖（默认） |
| `inprocess` | 直接调用 agent.stream() | .env + PostgreSQL |
| `http` | 打真实 FastAPI 端点 | 需先启动 uvicorn |

```bash
# 离线模式（推荐，零依赖）
python -m agent.benchmark --mode offline

# 指定并发阶梯
python -m agent.benchmark --mode offline --concurrency 10,20,50 --total-per-tier 50
```

**离线测试结果**（参考）：
- 并发 10/20/50：错误率 0%，QPS 11.8-25.3

报告输出到 `tests/benchmark_report.json` 和 `tests/benchmark_report.md`。

---

## 🐳 Docker 部署

### 一键启动
```bash
docker-compose up -d
```

### 服务编排
- **app**：`python:3.13-slim` 镜像，含 HEALTHCHECK（30s 间隔，调用 `/health`）
- **db**：`postgres:16-alpine`，自动执行 `docker/init.sql` 种子数据
- `depends_on: condition: service_healthy` 确保数据库就绪后再启动 app

### 环境变量
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | - | 必填，DeepSeek API 密钥 |
| `DB_USER` | insurance | 数据库用户 |
| `DB_PASSWORD` | insurance_pass | 数据库密码 |
| `DB_NAME` | insurance_db | 数据库名 |
| `OBS_ENABLED` | true | 是否启用可观测性 |

---

## ❓ 常见问题

**Q: 没有 PostgreSQL 能跑吗？**
A: 能。`database.py` 自动检测 PostgreSQL 连接，失败时降级到内存 SQLite + 相同种子数据，零依赖直接运行。

**Q: 可观测性怎么关闭？**
A: 设置环境变量 `OBS_ENABLED=false`，三层可观测性全部禁用。

**Q: 为什么用规则路由而不是 LLM 路由？**
A: 规则路由零 LLM 开销、延迟低、确定性强。保险业务域边界清晰，关键词匹配足够覆盖，省下的 LLM 调用留给 FactCheck 和重试。

**Q: FactCheck 会不会误杀正常的格式美化？**
A: 不会。FactCheck 只判定核心业务数据（姓名、保单号、金额等）的编造/篡改，标题、加粗、换行、单位补充等格式美化不视为错误。

---

## 📜 许可证

MIT
