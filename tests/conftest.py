"""共享 fixture 与测试工具 + Eval 回归收集钩子"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.callbacks import CallbackManagerForLLMRun
from sqlalchemy import create_engine, text


# ============================================================
# Eval 回归收集：pytest 会话结束时自动统计链路通过率 + Rubric 评分 + 回归 diff
# ============================================================

# Rubric 权重（与 test_eval_suite.py docstring 对齐）
# 维度 A=准确性(35%) B=完整性(20%) C=事实校验(20%) D=多轮连贯(15%) E=安全合规(10%)
# 每条链路映射到对应的 Rubric 维度（pass 即该维度满分）
_LINK_RUBRIC = {
    "L1": {"A": 35, "B": 20, "C": 20, "D": 15, "E": 10},  # 单轮：覆盖 A/B/C
    "L2": {"A": 35, "B": 20, "C": 20, "D": 15, "E": 10},  # 多轮：重点 D
    "L3": {"A": 35, "B": 20, "C": 20, "D": 15, "E": 10},  # 校验：重点 C
    "L4": {"A": 35, "B": 20, "C": 20, "D": 15, "E": 10},  # 安全：重点 E
}

_EVAL_LINK_MAP = {
    "L1": "L1 单轮查询",
    "L2": "L2 多轮对话",
    "L3": "L3 事实校验",
    "L4": "L4 SQL 安全",
}

_EVAL_RESULTS: list[dict] = []  # {nodeid, link, name, outcome, duration_ms}
_BASELINE_PATH = Path(__file__).parent / "eval_baseline.json"
_REPORT_PATH = Path(__file__).parent / "eval_report.md"


def pytest_runtest_makereport(item, call):
    """每个用例执行后捕获 pass/fail 和耗时（仅收集 call 阶段，过滤 setup/teardown）"""
    if call.when != "call":
        return
    outcome = "pass" if call.excinfo is None else "fail"
    nodeid = item.nodeid
    import re
    m = re.search(r"test_(L\d+)_\d+", nodeid)
    link = m.group(1) if m else None
    _EVAL_RESULTS.append({
        "nodeid": nodeid,
        "link": link,
        "name": item.name,
        "outcome": outcome,
        "duration_ms": round((call.stop - call.start) * 1000, 1) if call.stop and call.start else 0,
    })


def _compute_rubric_score(link: str, passed_ratio: float) -> dict:
    """按 Rubric 权重计算链路加权分。
    passed_ratio=1.0 → 该链路每条用例的权重全拿；<1.0 则按比例扣分。
    """
    weights = _LINK_RUBRIC.get(link, {})
    # 简化：pass_ratio × 各维度权重
    dims = {dim: round(w * passed_ratio, 1) for dim, w in weights.items()}
    total = round(sum(dims.values()), 1)
    return {"dimensions": dims, "weighted_total": total}


def _diff_against_baseline(current_by_link: dict) -> list[dict]:
    """对比上一次 baseline，检测链路通过率退化"""
    if not _BASELINE_PATH.exists():
        return []  # 首次运行，无 baseline 可对比
    try:
        old = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    diffs = []
    old_by_link = old.get("by_link", {})
    for link, cur in current_by_link.items():
        prev = old_by_link.get(link, {"passed": cur["passed"], "total": cur["total"]})
        prev_rate = prev["passed"] / prev["total"] * 100 if prev.get("total", 0) else 0
        cur_rate = cur["passed"] / cur["total"] * 100 if cur.get("total", 0) else 0
        delta = round(cur_rate - prev_rate, 1)
        if delta != 0:
            diffs.append({
                "link": link,
                "prev_rate": prev_rate,
                "cur_rate": cur_rate,
                "delta": delta,
                "degraded": delta < 0,
            })
    return diffs


def pytest_sessionfinish(session, exitstatus):
    """会话结束时：Rubric 评分 + 回归 diff + baseline JSON + Markdown 报告"""
    eval_only = [r for r in _EVAL_RESULTS if r["link"] is not None]
    if not eval_only:
        return

    # --- 1. 按链路分组 + Rubric 评分 ---
    link_stats: dict[str, dict] = {}
    for r in eval_only:
        link = r["link"]
        if link not in link_stats:
            link_stats[link] = {"total": 0, "passed": 0, "failed": 0, "name": _EVAL_LINK_MAP.get(link, link)}
        link_stats[link]["total"] += 1
        if r["outcome"] == "pass":
            link_stats[link]["passed"] += 1
        else:
            link_stats[link]["failed"] += 1

    for link, s in link_stats.items():
        ratio = s["passed"] / s["total"] if s["total"] else 0
        s["pass_rate_pct"] = round(ratio * 100, 1)
        s["rubric"] = _compute_rubric_score(link, ratio)

    # --- 2. 回归 Diff ---
    diffs = _diff_against_baseline(link_stats)

    # --- 3. 写 baseline JSON ---
    total_pass = sum(s["passed"] for s in link_stats.values())
    total_all = sum(s["total"] for s in link_stats.values())
    baseline = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exitstatus": exitstatus,
        "summary": {
            "total": total_all,
            "passed": total_pass,
            "failed": total_all - total_pass,
            "pass_rate": f"{total_pass / total_all * 100:.1f}%" if total_all else "0%",
            "rubric_overall": round(sum(s["rubric"]["weighted_total"] for s in link_stats.values()) / len(link_stats), 1) if link_stats else 0,
        },
        "by_link": link_stats,
        "regression_diffs": diffs,
        "cases": eval_only,
    }
    _BASELINE_PATH.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 4. 写 Markdown 报告 ---
    _write_markdown_report(baseline, link_stats, diffs)

    # --- 5. 打印到 stdout ---
    _print_console_report(baseline, link_stats, diffs)


def _write_markdown_report(baseline: dict, link_stats: dict, diffs: list):
    """生成持久化的 eval_report.md"""
    lines = []
    lines.append("# Insurance Agent - Eval 回归基线报告\n")
    lines.append(f"**生成时间**: {baseline['generated_at']}  ")
    lines.append(f"**退出码**: {baseline['exitstatus']}  ")
    lines.append(f"**Rubric 综合分**: {baseline['summary']['rubric_overall']} / 100\n")

    lines.append("## 一、评分标准（Rubric）\n")
    lines.append("| 维度 | 权重 | 判定规则 |")
    lines.append("|------|------|----------|")
    lines.append("| [A] 准确性 | 35% | output 包含预期核心数据 |")
    lines.append("| [B] 完整性 | 20% | 回答覆盖用户所有问题点 |")
    lines.append("| [C] 事实校验 | 20% | 编造数据被拦截，真实数据通过 |")
    lines.append("| [D] 多轮连贯 | 15% | 历史消息正确传递、指代消解 |")
    lines.append("| [E] 安全合规 | 10% | SQL 注入被拦截，合法 SQL 通过 |")
    lines.append("")

    lines.append("## 二、整体结果\n")
    s = baseline["summary"]
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|----|")
    lines.append(f"| Eval 用例总数 | {s['total']} |")
    lines.append(f"| 通过 | {s['passed']} |")
    lines.append(f"| 失败 | {s['failed']} |")
    lines.append(f"| 通过率 | {s['pass_rate']} |")
    lines.append(f"| Rubric 综合分 | {s['rubric_overall']}/100 |")
    lines.append("")

    lines.append("## 三、链路明细\n")
    lines.append("| 链路 | 名称 | 通过/总数 | 通过率 | Rubric 加权分 | 判定 |")
    lines.append("|------|------|-----------|--------|---------------|------|")
    for link in sorted(link_stats.keys()):
        ls = link_stats[link]
        judge = "✅" if ls["pass_rate_pct"] >= 90 else "⚠️" if ls["pass_rate_pct"] >= 80 else "❌"
        lines.append(f"| {link} | {ls['name']} | {ls['passed']}/{ls['total']} | {ls['pass_rate_pct']}% | {ls['rubric']['weighted_total']}/100 | {judge} |")
    lines.append("")

    lines.append("### 各链路 Rubric 维度得分\n")
    lines.append("| 链路 | A准确性(35) | B完整性(20) | C事实校验(20) | D多轮连贯(15) | E安全合规(10)")
    lines.append("|------|------------|------------|--------------|--------------|------------|")
    for link in sorted(link_stats.keys()):
        d = link_stats[link]["rubric"]["dimensions"]
        lines.append(f"| {link} | {d['A']}/35 | {d['B']}/20 | {d['C']}/20 | {d['D']}/15 | {d['E']}/10 |")
    lines.append("")

    if diffs:
        lines.append("## 四、回归 Diff（对比上一次 baseline）\n")
        lines.append("| 链路 | 上次通过率 | 本次通过率 | Δ | 退化? |")
        lines.append("|------|-----------|-----------|---|-------|")
        for d in diffs:
            sign = "+" if d["delta"] > 0 else ""
            lines.append(f"| {d['link']} | {d['prev_rate']}% | {d['cur_rate']}% | {sign}{d['delta']}% | {'⚠️ 退化' if d['degraded'] else '📈 提升'} |")
        lines.append("")
    else:
        lines.append("## 四、回归 Diff\n")
        lines.append("无历史 baseline 可对比（首次运行），或与上一次结果完全一致。\n")

    _REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def _print_console_report(baseline: dict, link_stats: dict, diffs: list):
    """打印到 pytest stdout"""
    print("\n" + "=" * 60)
    print("📊 Insurance Agent - Eval 回归基线报告")
    print("=" * 60)
    print(f"生成时间: {baseline['generated_at']}")
    print(f"Rubric 综合分: {baseline['summary']['rubric_overall']}/100")
    print()
    print("### 链路明细")
    print("| 链路 | 名称 | 通过/总数 | 通过率 | Rubric | 判定 |")
    print("|------|------|-----------|--------|--------|------|")
    for link in sorted(link_stats.keys()):
        ls = link_stats[link]
        judge = "✅" if ls["pass_rate_pct"] >= 90 else "⚠️" if ls["pass_rate_pct"] >= 80 else "❌"
        print(f"| {link} | {ls['name']} | {ls['passed']}/{ls['total']} | {ls['pass_rate_pct']}% | {ls['rubric']['weighted_total']}/100 | {judge} |")

    if diffs:
        print()
        print("### 回归 Diff（vs 上次）")
        for d in diffs:
            sign = "+" if d["delta"] > 0 else ""
            flag = "⚠️ 退化!" if d["degraded"] else "📈 提升"
            print(f"  {d['link']}: {d['prev_rate']}% → {d['cur_rate']}% ({sign}{d['delta']}%) {flag}")
    else:
        print()
        print("📈 无回归退化（首次运行或与上次一致）")

    print()
    print(f"📁 Baseline: tests/eval_baseline.json")
    print(f"📄 Report:   tests/eval_report.md")
    print("=" * 60)



class ScriptedChatModel(BaseChatModel):
    """按脚本顺序返回消息的模型，bind_tools 直接返回自身（离线测试用，不调用真实 LLM）"""

    responses: List[dict]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs) -> Any:
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs: Any) -> ChatResult:
        resp = self.responses.pop(0) if self.responses else self.responses[-1]
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content=resp.get("content", ""), tool_calls=resp.get("tool_calls", []))
        )])


@pytest.fixture
def sqlite_engine():
    """内存 SQLite，schema 与 docker/init.sql（PostgreSQL）完全对齐。
    customers(id, name, phone, address, age)
    policies(id, policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date)
    3 行种子 + 297 批量客户 + ~350 批量保单。
    """
    import random
    random.seed(42)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                address TEXT,
                age INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE policies (
                id INTEGER PRIMARY KEY,
                policy_no TEXT UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                product TEXT,
                premium REAL,
                insured_amount REAL,
                status TEXT DEFAULT 'active',
                start_date TEXT,
                end_date TEXT
            )
        """))

        # 种子（与 init.sql 一致）
        seed_customers = [
            {"id": 1, "name": '张三', "phone": '13800138000', "addr": '北京市朝阳区', "age": 32},
            {"id": 2, "name": '李四', "phone": '13900139999', "addr": '上海市浦东新区', "age": 28},
            {"id": 3, "name": '王五', "phone": '13700137777', "addr": '广州市天河区', "age": 45},
        ]
        seed_policies = [
            {"id": 1, "pn": 'P20250405001', "cid": 1, "prod": '安心健康保', "prem": 3200.00, "ia": 500000.00, "st": 'active',  "sd": '2025-04-05', "ed": '2045-04-04'},
            {"id": 2, "pn": 'P20250405002', "cid": 1, "prod": '终身寿险',   "prem": 3000.00, "ia": 800000.00, "st": 'active',  "sd": '2024-01-15', "ed": '2074-01-14'},
            {"id": 3, "pn": 'P20250405003', "cid": 3, "prod": '综合意外险', "prem": 1800.00, "ia": 300000.00, "st": 'expired', "sd": '2023-06-01', "ed": '2024-05-31'},
        ]
        conn.execute(text("INSERT INTO customers (id, name, phone, address, age) VALUES (:id,:name,:phone,:addr,:age)"), seed_customers)
        conn.execute(text("INSERT INTO policies (id, policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date) VALUES (:id,:pn,:cid,:prod,:prem,:ia,:st,:sd,:ed)"), seed_policies)

        # 批量扩产
        families = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳")
        given_names = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "霞", "平", "刚", "桂英", "鑫", "雨桐", "梓涵", "浩然", "子轩", "一诺", "思远", "思琪"]
        cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "重庆", "西安", "苏州", "天津", "长沙", "青岛", "郑州"]
        products = ['安心健康保', '终身寿险', '综合意外险', '重疾无忧', '齿科医疗险']
        statuses = ['active', 'active', 'active', 'expired', 'pending']

        cust_batch = []
        pol_batch = []
        for i in range(4, 301):
            cust_batch.append({
                "id": i,
                "name": random.choice(families) + random.choice(given_names),
                "phone": f"1{random.choice(['3','5','7','8','9'])}{''.join(str(random.randint(0,9)) for _ in range(9))}",
                "addr": random.choice(cities) + "市某区",
                "age": 22 + (i % 50),
            })
            cid = i
            p = i - 3  # 保单编号
            pol_batch.append({
                "id": 3 + p,
                "pn": f"P2025{p:06d}",
                "cid": cid,
                "prod": random.choice(products),
                "prem": 1000 + ((i * 17) % 9000),
                "ia": 100000 + ((i * 31) % 900000),
                "st": random.choice(statuses),
                "sd": "2020-01-01",
                "ed": "2020-01-01",
            })

        conn.execute(text("INSERT INTO customers (id, name, phone, address, age) VALUES (:id,:name,:phone,:addr,:age)"), cust_batch)
        conn.execute(text("INSERT INTO policies (id, policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date) VALUES (:id,:pn,:cid,:prod,:prem,:ia,:st,:sd,:ed)"), pol_batch)
    yield engine
    engine.dispose()


@pytest.fixture
def logger():
    """测试专用 logger"""
    return logging.getLogger("test")


@pytest.fixture
def fake_engine():
    """只实现 dispose 的假 Engine，供 API 测试注入"""
    return type("FakeEngine", (), {"dispose": lambda self: None})()
