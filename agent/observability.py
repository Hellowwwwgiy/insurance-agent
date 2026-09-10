"""可观测性模块：结构化 JSON 日志 + RequestMiddleware + LangGraphCallback

三层可观测性（零额外依赖，全部用 Python 标准库 + FastAPI/LangChain 内置钩子）：

┌──────────────────────────────────────────────────────────────┐
│ Layer 1  StructuredLogger     结构化 JSON 日志               │
│   trace_id / request_id / level / msg / extra                │
├──────────────────────────────────────────────────────────────┤
│ Layer 2  RequestMiddleware    FastAPI middleware              │
│   请求耗时 / route 分布 / SSE 事件计数                        │
├──────────────────────────────────────────────────────────────┤
│ Layer 3  LangGraphCallback   LangChain callback handler       │
│   LLM 延迟 / token 用量 / retry 次数                         │
└──────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ─────────────────────────────────────────────────────────────
# Layer 1: trace_id / request_id context + JSON 日志格式
# ─────────────────────────────────────────────────────────────
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_trace_id() -> str:
    tid = uuid.uuid4().hex[:16]
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    return _trace_id_var.get()


def get_request_id() -> str:
    return _request_id_var.get()


class StructuredFormatter(logging.Formatter):
    """把每条日志格式化为单行 JSON，携带 trace_id / request_id"""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "file": f"{record.filename}:{record.lineno}",
            "trace_id": get_trace_id(),
            "request_id": get_request_id(),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 把 record 上额外的 dict 字段（log_extra）也打进去
        extra = getattr(record, "log_extra", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                payload.setdefault(k, v)
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps({k: str(v) for k, v in payload.items()}, ensure_ascii=False)


def install_structured_logging(logger: logging.Logger = None,
                                enable: bool = True) -> None:
    """把指定 logger（或根 logger）的 handler 替换为 JSON 格式。
    enable=False 时什么也不做，保留原有 handler（测试场景用）。"""
    if not enable:
        return
    target = logger or logging.getLogger()
    fmt = StructuredFormatter(datefmt="%Y-%m-%dT%H:%M:%S")
    # 替换已有 handler
    for h in list(target.handlers):
        h.setFormatter(fmt)
    if not target.handlers:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        target.addHandler(sh)
    target.propagate = False


# ─────────────────────────────────────────────────────────────
# Layer 2: FastAPI RequestMiddleware
# ─────────────────────────────────────────────────────────────
# ── 全局 metrics 单例（让 /metrics 端点能从模块级读到，不依赖 app 上的引用） ──
_global_metrics: Dict[str, Any] = {
    "request_total": 0,
    "request_by_route": {},
    "status_5xx": 0,
    "latency_p50_ms": None,
    "latency_p95_ms": None,
    "_samples_ms": [],
}


class RequestMiddleware(BaseHTTPMiddleware):
    """记录每个请求的耗时、状态码；SSE 流式时额外记录事件数。"""

    def __init__(self, app, logger: Optional[logging.Logger] = None):
        super().__init__(app)
        self.logger = logger or logging.getLogger("InsuranceAgent")

    @property
    def metrics(self) -> Dict[str, Any]:
        return _global_metrics

    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        _request_id_var.set(rid)
        _trace_id_var.set(request.headers.get("X-Trace-Id") or new_trace_id())

        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            lat_ms = (time.perf_counter() - t0) * 1000
            self._record(request, 500, lat_ms)
            self.logger.error("request_failed", extra={"log_extra": {
                "method": request.method, "path": request.url.path,
                "latency_ms": round(lat_ms, 1), "error": str(exc),
            }})
            raise

        lat_ms = (time.perf_counter() - t0) * 1000
        self._record(request, response.status_code, lat_ms)

        # SSE 特殊处理：遍历 StreamingResponse 时统计事件数
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            _log = self.logger
            lat_ms_final = lat_ms
            rid_final = rid

            class _SSEWrapper:
                def __init__(self, inner):
                    self._inner = inner
                    self.events = 0
                    self.tokens = 0

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    async for chunk in self._inner:
                        text = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
                        if text.startswith("data: "):
                            self.events += 1
                            try:
                                obj = json.loads(text[6:])
                                if obj.get("type") == "token":
                                    self.tokens += 1
                            except Exception:
                                pass
                        return chunk
                    raise StopAsyncIteration

            async def _record_sse_later():
                wrapper = None
                # 把 inner_body_iterator 包一下再塞回去
                body_iter = response.body_iterator

                # 重新构造：遍历一次，计数后 yield
                async def _counting_iter():
                    nonlocal wrapper
                    wrapper = _SSEWrapper(body_iter)
                    async for chunk in wrapper:
                        yield chunk
                    if wrapper is not None:
                        _log.info("sse_done", extra={"log_extra": {
                            "request_id": rid_final,
                            "events": wrapper.events,
                            "tokens": wrapper.tokens,
                            "latency_ms": round(lat_ms_final, 1),
                        }})

                response.body_iterator = _counting_iter()

            import asyncio
            asyncio.ensure_future(_record_sse_later())

        return response

    def _record(self, request: Request, status: int, lat_ms: float):
        m = self.metrics
        m["request_total"] += 1
        route_key = f"{request.method} {request.url.path}"
        m["request_by_route"][route_key] = m["request_by_route"].get(route_key, 0) + 1
        if 500 <= status < 600:
            m["status_5xx"] += 1
        m["_samples_ms"].append(lat_ms)
        # 简单百分位（最多留 500 个样本）
        samples = m["_samples_ms"][-500:]
        samples.sort()
        if samples:
            m["latency_p50_ms"] = round(samples[len(samples) // 2], 1)
            m["latency_p95_ms"] = round(samples[int(len(samples) * 0.95)], 1)

        self.logger.info("request_done", extra={"log_extra": {
            "method": request.method, "path": request.url.path,
            "status": status, "latency_ms": round(lat_ms, 1),
        }})


# ─────────────────────────────────────────────────────────────
# Layer 3: LangGraph / LangChain Callback Handler
# ─────────────────────────────────────────────────────────────
try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # 纯日志测试场景无 langchain
    BaseCallbackHandler = object  # type: ignore


class LangGraphCallback(BaseCallbackHandler):
    """捕获每次 LLM 调用的延迟 + token 用量；重试节点时额外打点。"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("InsuranceAgent")
        self._llm_start: Dict[str, float] = {}

    def on_llm_start(self, serialized, prompts, run_id=None, **kwargs):
        key = str(run_id) if run_id else id(prompts)
        self._llm_start[key] = time.perf_counter()

    def on_llm_end(self, response, run_id=None, **kwargs):
        key = str(run_id) if run_id else None
        t0 = self._llm_start.pop(key, None) if key else None
        lat_ms = round((time.perf_counter() - t0) * 1000, 1) if t0 else None

        # langchain 统计 token（不同 LLM provider 字段略不同，兼容多版本）
        usage = getattr(response, "llm_output", {}) or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        if total_tokens is None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0) or None

        self.logger.info("llm_call", extra={"log_extra": {
            "latency_ms": lat_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }})

    def on_llm_error(self, error, run_id=None, **kwargs):
        self.logger.error("llm_error", extra={"log_extra": {
            "error": f"{type(error).__name__}: {error}",
        }})

    def on_tool_start(self, serialized, input_str, run_id=None, **kwargs):
        self.logger.debug("tool_call", extra={"log_extra": {
            "tool": serialized.get("name") if isinstance(serialized, dict) else str(serialized),
            "input": input_str[:200] if input_str else None,
        }})

    def on_tool_end(self, output, run_id=None, **kwargs):
        self.logger.debug("tool_result", extra={"log_extra": {
            "output_preview": (str(output)[:200] if output is not None else None),
        }})


# ─────────────────────────────────────────────────────────────
# /metrics 助手（供 FastAPI 路由调用，文本暴露）
# ─────────────────────────────────────────────────────────────
def format_metrics_text() -> str:
    """极简 Prometheus-like 指标端点，零额外依赖，直接读全局单例。"""
    m = _global_metrics
    lines = [
        f"insurance_request_total {m['request_total']}",
        f"insurance_status_5xx_total {m['status_5xx']}",
    ]
    if m["latency_p50_ms"] is not None:
        lines.append(f"insurance_latency_p50_ms {m['latency_p50_ms']}")
        lines.append(f"insurance_latency_p95_ms {m['latency_p95_ms']}")
    for route, count in sorted(m["request_by_route"].items()):
        lines.append(f'insurance_route_total{{route="{route}"}} {count}')
    return "\n".join(lines) + "\n"
