"""并发/性能评测模块 —— QPS · P50/P95 延迟 · 错误率

三种运行模式：
  1) offline（默认）：用 ScriptedChatModel + in-memory SQLite
     ✅ 零依赖（不需要 .env / PostgreSQL / 真实 API Key）
     ✅ 适合 CI、Demo、面试官现场跑
  2) inprocess：直接调真实 agent.stream()，需要 .env + PostgreSQL
  3) http：打真实 FastAPI /query/stream，需要先 `uvicorn agent.api:app`

并发阶梯：10 / 20 / 50 用户；每档至少 50 条查询。
结果写入 tests/benchmark_report.json + .md（运行产物 → 手动移到 other1）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 真实评测问题池（和 agent/eval_judge.py 种子同源，保证复用可复现）
# ---------------------------------------------------------------------------
_QUESTION_POOL: List[str] = [
    "张三的电话号码是多少？",
    "李四住在哪个城市？",
    "王五今年多大？",
    "安心健康保的保费是多少？",
    "终身寿险的保额是多少？",
    "张三有几份有效保单？",
    "李四有没有保单？",
    "王五的保单号和产品名分别是什么？",
    "数据库里一共有多少个客户？",
    "数据库里一共有多少份保单？",
    "目前有多少保单处于 active 状态？",
    "持有终身寿险的客户有几个？",
    "张三买的安心健康保有免赔额吗？",
    "综合意外险的保障期间是多少年？",
    "保单过期了的客户有哪些？",
]


def _pick_questions(n: int, seed: int = 42) -> List[str]:
    rng = random.Random(seed)
    return [rng.choice(_QUESTION_POOL) for _ in range(n)]


# ---------------------------------------------------------------------------
# In-process 压测（推荐，零网络）
# ---------------------------------------------------------------------------
async def _run_one_stream(agent, question: str, idx: int = 0) -> Dict[str, Any]:
    """直接调 agent.stream()，记录完整一次查询的耗时和结果。

    用 run_in_executor 把同步生成器放到线程池跑，不阻塞 asyncio 事件循环，
    这样多并发查询真的能并行，不会被同步 LLM 调用卡住。"""
    t0 = time.perf_counter()

    def _pull_all():
        tokens = 0
        events = 0
        try:
            for ev in agent.stream({"input": question, "messages": []}):
                events += 1
                if isinstance(ev, dict) and ev.get("type") == "token":
                    tokens += 1
            return True, tokens, events, None
        except Exception as exc:
            return False, 0, 0, f"{type(exc).__name__}: {exc}"

    try:
        ok, tokens, events, err = await asyncio.to_thread(_pull_all)
        lat_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "ok": ok,
            "latency_ms": lat_ms,
            "tokens": tokens,
            "events": events,
            "question": question[:30],
            "error": err,
        }
    except Exception as exc:
        lat_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "ok": False,
            "latency_ms": lat_ms,
            "tokens": 0, "events": 0,
            "question": question[:30],
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Offline 压测（默认，零依赖）—— ScriptedChatModel + in-memory SQLite
# ---------------------------------------------------------------------------
async def _bench_offline(
    concurrency: int,
    total_requests: int,
    seed: int = 42,
) -> Dict[str, Any]:
    """和 conftest.py 里的 fixture 完全同款，复用 ScriptedChatModel 模式。

    性能数字代表「去掉 LLM 延迟后的纯框架吞吐」——面试官看的是：
    当 LLM 不是瓶颈时，你的多 Agent + SQL 工具链能扛多少并发。
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.callbacks import CallbackManagerForLLMRun
    from sqlalchemy import create_engine, text
    from . import create_agent, create_enhanced_agent

    # ── 1. ScriptedChatModel：所有步骤返回 canned answer ──
    class _Scripted(BaseChatModel):
        responses: list
        @property
        def _llm_type(self) -> str: return "scripted"
        def bind_tools(self, tools, **kwargs): return self
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            resp = self.responses.pop(0) if self.responses else self.responses[-1]
            # 构造带 tool_calls 的 AIMessage 让 agent 正常走 SQL 工具链
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content=resp.get("content", "查询完成。"),
                tool_calls=resp.get("tool_calls", [])
            ))])

    # 预先生成足够长的 script：路由 + SQL 工具调用 + 最终回答 + FactCheck 通过
    # 关键：必须让 Supervisor、SQL Agent、FactCheck 全部正常跑完
    _ROUTE_RESP = {"content": '{"specialist": "customer"}'}
    _SQL_TOOL_CALLS = [
        {"name": "query_customers", "args": {"sql": "SELECT * FROM customers LIMIT 1"}},
    ]
    _SQL_TOOL_RESULT = {"content": '[{"name":"张三","phone":"13800138000"}]'}
    _FINAL = {"content": "张三的电话号码是 13800138000。"}
    _CHECK_PASS = {"content": '{"verified": true}'}

    # 每条查询需要：route → sql_call(s) → final → check → retry_check(pass)
    SCRIPT_PER_QUERY = [
        _ROUTE_RESP, _SQL_TOOL_RESULT, _FINAL, _CHECK_PASS,
    ]

    # 为每次并发独立创建 agent（避免 responses list 竞争）
    import logging as _logging

    def _build_agent():
        script = []
        for _ in range(total_requests + 10):  # 多塞几条防耗尽
            script.extend(SCRIPT_PER_QUERY)
        llm = _Scripted(responses=script)
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, city TEXT)"))
            conn.execute(text("CREATE TABLE policies (policy_no TEXT PRIMARY KEY, customer_id INTEGER, product TEXT, premium REAL, status TEXT)"))
            conn.execute(text("INSERT INTO customers VALUES (1, '张三', '13800138000', '北京朝阳')"))
            conn.execute(text("INSERT INTO policies VALUES ('P001', 1, '安心健康保', 3200.0, 'active')"))
        agent_logger = _logging.getLogger(f"bench-{id(engine)}")
        agent_logger.setLevel(_logging.WARNING)  # 压测时只打 warning+，避免日志刷屏
        agent_logger.addHandler(_logging.NullHandler())
        base = create_agent(llm, engine, agent_logger)
        return create_enhanced_agent(base, llm, agent_logger, db=engine)

    questions = _pick_questions(total_requests, seed)
    sem = asyncio.Semaphore(concurrency)

    async def _limited(q):
        agent = _build_agent()
        async with sem:
            return await _run_one_stream(agent, q, 0)

    t0 = time.perf_counter()
    tasks = [_limited(q) for q in questions]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    wall_s = time.perf_counter() - t0

    return _aggregate(results, wall_s, concurrency, total_requests, mode="offline(ScriptedChatModel+SQLite)")


async def _bench_in_process(
    concurrency: int,
    total_requests: int,
    seed: int = 42,
) -> Dict[str, Any]:
    from . import (load_environment, setup_logger, create_database_connection,
                   create_llm, create_agent, create_enhanced_agent)

    settings = load_environment()
    logger = setup_logger(settings=settings)
    llm = create_llm(settings, logger)
    engine = create_database_connection(settings, logger)
    base_agent = create_agent(llm, engine, logger)
    agent = create_enhanced_agent(base_agent, llm, logger, db=engine)

    questions = _pick_questions(total_requests, seed)
    sem = asyncio.Semaphore(concurrency)

    async def _limited(q, i):
        async with sem:
            return await _run_one_stream(agent, q, i)

    t0 = time.perf_counter()
    tasks = [_limited(q, i) for i, q in enumerate(questions)]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    wall_s = time.perf_counter() - t0

    return _aggregate(results, wall_s, concurrency, total_requests, mode="in-process")


# ---------------------------------------------------------------------------
# HTTP 压测（可选，需要启动 uvicorn）
# ---------------------------------------------------------------------------
async def _run_one_http(session, url: str, question: str) -> Dict[str, Any]:
    import aiohttp  # 懒加载，避免无 aiohttp 时 import 失败
    t0 = time.perf_counter()
    tokens = 0
    events = 0
    try:
        async with session.post(url, json={"input": question, "messages": []},
                                timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                return {
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "tokens": 0, "events": 0,
                    "question": question[:30],
                    "error": f"HTTP {resp.status}",
                }
            async for line in resp.content:
                text = line.decode("utf-8", errors="ignore").strip()
                if text.startswith("data: "):
                    events += 1
                    try:
                        obj = json.loads(text[6:])
                        if obj.get("type") == "token":
                            tokens += 1
                    except Exception:
                        pass
        lat_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": True, "latency_ms": lat_ms, "tokens": tokens, "events": events,
                "question": question[:30]}
    except Exception as exc:
        lat_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": False, "latency_ms": lat_ms, "tokens": 0, "events": 0,
                "question": question[:30], "error": f"{type(exc).__name__}: {exc}"}


async def _bench_http(
    concurrency: int,
    total_requests: int,
    url: str = "http://localhost:8080/query/stream",
    seed: int = 42,
) -> Dict[str, Any]:
    try:
        import aiohttp
    except ImportError:
        print("❌ 缺少 aiohttp，请 `pip install aiohttp` 或用 --mode inprocess")
        sys.exit(2)

    questions = _pick_questions(total_requests, seed)
    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=0)  # 不限连接数

    async with aiohttp.ClientSession(connector=connector) as session:
        async def _limited(q):
            async with sem:
                return await _run_one_http(session, url, q)

        t0 = time.perf_counter()
        tasks = [_limited(q) for q in questions]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        wall_s = time.perf_counter() - t0

    return _aggregate(results, wall_s, concurrency, total_requests,
                      mode=f"http@{url}")


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------
def _aggregate(results, wall_s, concurrency, total, mode) -> Dict[str, Any]:
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    lats = sorted(r["latency_ms"] for r in ok)

    p50 = round(lats[len(lats) // 2], 1) if lats else None
    p95 = round(lats[int(len(lats) * 0.95)], 1) if lats else None
    p99 = round(lats[int(len(lats) * 0.99)], 1) if lats else None
    avg = round(sum(lats) / len(lats), 1) if lats else None
    qps = round(len(ok) / wall_s, 2) if wall_s > 0 else 0
    error_rate = round(len(fail) / max(total, 1), 3)

    return {
        "mode": mode,
        "concurrency": concurrency,
        "total_requests": total,
        "wall_seconds": round(wall_s, 2),
        "ok": len(ok),
        "fail": len(fail),
        "error_rate": error_rate,
        "qps": qps,
        "latency_avg_ms": avg,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_p99_ms": p99,
        "results": results,  # 明细（可选，后续可以去掉减体积）
    }


# ---------------------------------------------------------------------------
# 主入口：跑多档并发，输出汇总
# ---------------------------------------------------------------------------
async def _run_bench_all(
    concurrencies: List[int],
    total_requests_per_tier: int,
    mode: str,
    url: str,
    seed: int,
) -> Dict[str, Any]:
    summary = {
        "mode": mode,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tiers": [],
    }
    for c in concurrencies:
        total = max(total_requests_per_tier, c * 5)  # 至少每用户 5 条
        print(f"⏳ 并发={c} · 共 {total} 条 · {mode} ...")
        if mode == "offline":
            tier = await _bench_offline(c, total, seed)
        elif mode == "inprocess":
            tier = await _bench_in_process(c, total, seed)
        else:
            tier = await _bench_http(c, total, url, seed)
        summary["tiers"].append(tier)
        _print_tier(tier)
    return summary


def _print_tier(tier: Dict[str, Any]):
    print(f"  ✅ concurrency={tier['concurrency']}  "
          f"QPS={tier['qps']}  "
          f"P50={tier['latency_p50_ms']}ms  "
          f"P95={tier['latency_p95_ms']}ms  "
          f"P99={tier['latency_p99_ms']}ms  "
          f"错误率={tier['error_rate']}  "
          f"(ok={tier['ok']} fail={tier['fail']} wall={tier['wall_seconds']}s)")


def _format_markdown(summary: Dict[str, Any]) -> str:
    lines = ["# 性能基准报告", "",
             f"**模式**: {summary['mode']}  |  **时间**: {summary['timestamp']}",
             "", "## 汇总表", "",
             "| 并发 | 总请求 | 墙钟(s) | QPS | P50(ms) | P95(ms) | P99(ms) | 错误率 | 成功/总 |",
             "|------|--------|---------|-----|---------|---------|---------|--------|---------|"]
    for t in summary["tiers"]:
        lines.append(
            f"| {t['concurrency']} | {t['total_requests']} | {t['wall_seconds']} | "
            f"{t['qps']} | {t['latency_p50_ms']} | {t['latency_p95_ms']} | "
            f"{t['latency_p99_ms']} | {t['error_rate']} | {t['ok']}/{t['total_requests']} |"
        )

    lines += ["", "## 关键结论（面试用）", ""]
    for t in summary["tiers"]:
        lines.append(
            f"- **{t['concurrency']} 并发**: QPS **{t['qps']}**, "
            f"P95 **{t['latency_p95_ms']}ms**, "
            f"错误率 **{t['error_rate']}**"
        )

    # 失败样本（最多 3 条）
    all_fails = []
    for t in summary["tiers"]:
        for r in t.get("results", []):
            if not r["ok"]:
                all_fails.append((t["concurrency"], r))
    if all_fails:
        lines += ["", "## 失败样本（前 3 条）", ""]
        for c, r in all_fails[:3]:
            lines.append(f"- 并发={c} / {r.get('question','?')}: {r.get('error','?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="并发/性能评测")
    parser.add_argument("--mode", choices=["offline", "inprocess", "http"], default="offline",
                        help="offline(默认,零依赖)/inprocess(需.env)/http(需先启动uvicorn)")
    parser.add_argument("--url", default="http://localhost:8080/query/stream",
                        help="HTTP 模式下的目标端点")
    parser.add_argument("--concurrency", default="10,20,50",
                        help="并发阶梯，逗号分隔（默认 10,20,50）")
    parser.add_argument("--total-per-tier", type=int, default=50,
                        help="每档并发的总请求数（默认 50）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    concurrencies = [int(x.strip()) for x in args.concurrency.split(",")]

    summary = asyncio.run(_run_bench_all(
        concurrencies=concurrencies,
        total_requests_per_tier=args.total_per_tier,
        mode=args.mode,
        url=args.url,
        seed=args.seed,
    ))

    out_dir = Path(__file__).parent.parent / "tests"
    out_dir.mkdir(parents=True, exist_ok=True)

    jpath = out_dir / "benchmark_report.json"
    # 明细太大的话先剥掉 results
    slim = {k: v for k, v in summary.items()}
    for t in slim.get("tiers", []):
        t.pop("results", None)
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 JSON: {jpath}")

    mdpath = out_dir / "benchmark_report.md"
    mdpath.write_text(_format_markdown(summary), encoding="utf-8")
    print(f"📄 MD: {mdpath}")


if __name__ == "__main__":
    main()
