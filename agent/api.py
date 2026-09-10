"""FastAPI Web API：SQL 智能助手 + 多 Agent + 可观测性"""
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    load_environment,
    setup_logger,
    create_database_connection,
    create_llm,
    create_agent,
    create_enhanced_agent,
)
from .observability import (
    install_structured_logging,
    RequestMiddleware,
    LangGraphCallback,
    format_metrics_text,
)


class QueryRequest(BaseModel):
    question: str
    db_result: Optional[str] = None
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    verified: bool
    attempts: int
    session_id: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化引擎 + Agent + 可观测性中间件"""
    settings = load_environment()
    logger = setup_logger(settings=settings)

    enable_obs = os.environ.get("OBS_ENABLED", "true").lower() in ("1", "true", "yes")
    install_structured_logging(logger, enable=enable_obs)

    engine = create_database_connection(settings, logger)
    llm = create_llm(settings, logger)
    base_agent = create_agent(llm, engine, logger)
    app.state.agent = create_enhanced_agent(base_agent, llm, logger, db=engine)
    app.state.logger = logger
    app.state.sessions: dict = {}
    app.state.callback_handler = LangGraphCallback(logger) if enable_obs else None
    yield
    engine.dispose()
    logger.info("db_closed", extra={"log_extra": {"msg": "数据库连接已关闭"}} if enable_obs else None)


STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Insurance Agent Web",
    description="保险行业 SQL 智能助手（自然语言转 SQL 查询 + 前端聊天界面 + 可观测性）",
    version="0.2.0",
    lifespan=lifespan,
)

# ── 可观测性中间件 ──
_enable_obs = os.environ.get("OBS_ENABLED", "true").lower() in ("1", "true", "yes")
if _enable_obs:
    app.add_middleware(RequestMiddleware)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── 系统端点 ──
@app.get("/", tags=["system"])
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/metrics", tags=["observability"])
def metrics():
    """极简 Prometheus-like 指标端点（零额外依赖）"""
    text = format_metrics_text()
    return PlainTextResponse(text, media_type="text/plain")


# ── Agent 端点 ──
@app.post("/query", response_model=QueryResponse, tags=["agent"])
def query(req: QueryRequest):
    """自然语言问答（非流式，支持多轮会话）"""
    agent = app.state.agent
    cb = app.state.callback_handler
    sid, history = _get_session(req.session_id)
    inputs: dict = {"input": req.question, "messages": history}
    if req.db_result:
        inputs["db_result"] = req.db_result

    invoke_kwargs: dict = {}
    if cb is not None:
        invoke_kwargs["config"] = {"callbacks": [cb]}

    result = agent.invoke(inputs, **invoke_kwargs)
    _save_session(sid, result.get("messages", []))
    return QueryResponse(
        answer=result.get("output", ""),
        verified=bool(result.get("verified")),
        attempts=int(result.get("attempts", 0)),
        session_id=sid,
    )


@app.post("/query/stream", tags=["agent"])
async def query_stream(req: QueryRequest):
    """流式问答（SSE），事件类型：route / agent_start / token / retry / done / session"""
    agent = app.state.agent
    sid, history = _get_session(req.session_id)
    inputs: dict = {"input": req.question, "messages": history}
    if req.db_result:
        inputs["db_result"] = req.db_result

    # ⚠️ 必须用普通 sync generator（不是 async def），否则会阻塞 asyncio 事件循环
    # 导致 Uvicorn 无法 flush chunked 响应 → 浏览器收 network error
    def event_gen():
        last_messages = history
        try:
            for ev in agent.stream(inputs):
                if ev.get("type") == "done":
                    last_messages = ev.get("messages", history)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            _save_session(sid, last_messages)
            yield f"data: {json.dumps({'type': 'session', 'session_id': sid}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── 会话辅助 ──
def _get_session(sid: Optional[str]) -> tuple:
    sessions = app.state.sessions
    if not sid:
        sid = uuid.uuid4().hex
    return sid, sessions.get(sid, [])


def _save_session(sid: str, history: list):
    sessions = app.state.sessions
    sessions[sid] = history[-200:] if len(history) > 200 else history
