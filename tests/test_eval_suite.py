"""
Insurance Agent 系统性 Eval 测试集
=================================

Eval 评分标准（Rubric）
──────────────────────────────────
| 维度              | 权重  | 判定规则                                                       |
|-------------------|-------|----------------------------------------------------------------|
| [A] 准确性        | 35%   | output 包含预期核心数据（姓名/保单号/保费/手机号/产品名）        |
| [B] 完整性        | 20%   | 回答覆盖用户所有问题点，无遗漏                                  |
| [C] 事实校验      | 20%   | 编造数据 → verified=False 且 attempts≥2；真实数据 → verified=True|
| [D] 多轮连贯      | 15%   | 历史消息正确传递、指代消解（他/那/该客户→上一轮姓名）            |
| [E] 安全合规      | 10%   | SQL 注入（DROP/DELETE/INSERT/多语句）被拦截，合法 SQL 通过       |

Pass 线：单用例得分 ≥80% → PASS；链路通过率 ≥90% → 整体 PASS
回归基线：pytest 执行结束时自动写入 tests/eval_baseline.json

用例编号规则：L{链路号}-{序号}
  L1 = 单轮查询链路
  L2 = 多轮对话链路
  L3 = 事实校验与重试链路
  L4 = SQL 安全回归链路
"""
from __future__ import annotations

import json

import pytest

from agent.llm_factory import create_agent
from agent.self_check_agent import create_enhanced_agent
from agent.sql_tools import make_sql_tools
from conftest import ScriptedChatModel


# ============================================================
# 工具函数
# ============================================================

def _make_enhanced(script: list, sqlite_engine, logger, route: str = "SQL_AGENT"):
    """用 ScriptedChatModel + 真实 sqlite_engine 构建 EnhancedAgent。
    Supervisor 是规则路由（不消耗 LLM 调用），所以不需要注入 route 响应。"""
    lm = ScriptedChatModel(responses=list(script))
    base = create_agent(lm, sqlite_engine, logger=None)
    return create_enhanced_agent(base, lm, logger, db=sqlite_engine)


def result_has_history(result: dict, expected_fact: str) -> bool:
    """检查 result 的 messages 里是否包含某个事实（用于多轮历史断言）"""
    for m in result.get("messages", []):
        if expected_fact in m.get("content", ""):
            return True
    return False


# ============================================================
# L1：单轮查询链路（基础业务能力）
# ============================================================

class TestEvalL1SingleTurn:
    """L1 链路：单轮查询——Agent 能否根据用户问题正确生成 SQL 并给出准确回答"""

    # L1-01: 简单等值查询（SELECT ... WHERE name = ?）
    def test_L1_01_customer_phone(self, sqlite_engine, logger):
        """问题：张三的电话号码 —— 预期返回 13800138000"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT phone FROM customers WHERE name='张三'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "张三的电话号码是13800138000"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "张三的电话号码是多少？"})

        assert "13800138000" in result["output"]
        assert result["verified"] is True
        assert result["attempts"] == 1

    # L1-02: 多表 JOIN 查询（客户 + 保单）
    def test_L1_02_customer_policy_join(self, sqlite_engine, logger):
        """问题：张三的保单号和保费 —— 需要 JOIN customers 和 policies"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT p.policy_no, p.premium FROM customers c JOIN policies p ON c.id=p.customer_id WHERE c.name='张三' AND p.status='active'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "张三有一份有效保单，保单号P20250405001，保费3200元"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "张三的有效保单号和保费是多少？"})

        assert "P20250405001" in result["output"]
        assert "3200" in result["output"]
        assert result["verified"] is True

    # L1-03: 无结果查询（数据库里没有此人）
    def test_L1_03_no_result(self, sqlite_engine, logger):
        """问题：赵六的保单 —— 数据库无赵六，应如实说明无结果"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT * FROM customers WHERE name='赵六'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "数据库中没有找到赵六的信息"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "赵六的保单是多少？"})

        assert result["verified"] is True
        assert "张三" not in result["output"], "无结果时不应编造其他人的数据"
        assert "3200" not in result["output"], "无结果时不应编造保费"

    # L1-04: 聚合查询（COUNT/SUM）
    def test_L1_04_aggregation(self, sqlite_engine, logger):
        """问题：公司总共有多少有效保单 —— 需要 COUNT + WHERE status='active'"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT COUNT(*) FROM policies WHERE status='active'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "目前公司共有2份有效保单"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "公司目前有多少份有效保单？"})

        assert "2" in result["output"]
        assert result["verified"] is True


# ============================================================
# L2：多轮对话链路（指代消解与历史传递）
# ============================================================

class TestEvalL2MultiTurn:
    """L2 链路：多轮对话——历史消息传递、指代消解、连贯回答"""

    # L2-01: 指代词「他」消解
    def test_L2_01_pronoun_resolution(self, sqlite_engine, logger):
        """先问张三电话，再问「他的保费」——他应该指代张三"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT phone FROM customers WHERE name='张三'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "张三的电话号码是13800138000"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
            # 第 2 轮：agent 收到 history，正确消解「他」= 张三
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT p.premium FROM policies p JOIN customers c ON p.customer_id=c.id WHERE c.name='张三' AND p.status='active'"}, "id": "tc2", "type": "tool_call"}]},
            {"content": "张三的有效保单保费是3200元"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)

        r1 = agent.invoke({"input": "张三的电话号码是多少？"})
        assert "13800138000" in r1["output"]

        r2 = agent.invoke({"input": "那他的保费是多少？", "messages": r1["messages"]})
        assert "3200" in r2["output"], "指代消解失败：他→张三 应返回 3200"
        assert result_has_history(r2, "张三"), "history 应包含上一轮的姓名"
        assert r2["verified"] is True

    # L2-02: 确认 history 格式正确（可安全序列化/反序列化）
    def test_L2_02_history_serialization(self, sqlite_engine, logger):
        """多轮后 messages 必须是 JSON-safe 的 dict 列表，不含 LangChain 对象"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT name FROM customers LIMIT 1"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "好的，我知道了"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT name FROM customers LIMIT 2"}, "id": "tc2", "type": "tool_call"}]},
            {"content": "好的"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)

        r1 = agent.invoke({"input": "查询测试"})
        r2 = agent.invoke({"input": "再查一次", "messages": r1["messages"]})

        assert isinstance(r2["messages"], list)
        assert all(isinstance(m, dict) for m in r2["messages"])
        # 关键回归：曾因 ToolMessage 序列化丢 tool_call_id 导致 KeyError
        json_str = json.dumps(r2["messages"], ensure_ascii=False)
        assert json_str

    # L2-03: 三轮连续对话不崩溃
    def test_L2_03_three_turns(self, sqlite_engine, logger):
        """三轮连续查询——history 累积不崩溃"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT 1"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "好的一"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT 2"}, "id": "tc2", "type": "tool_call"}]},
            {"content": "好的二"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT 3"}, "id": "tc3", "type": "tool_call"}]},
            {"content": "好的三"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)

        r1 = agent.invoke({"input": "问题1"})
        r2 = agent.invoke({"input": "问题2", "messages": r1["messages"]})
        r3 = agent.invoke({"input": "问题3", "messages": r2["messages"]})

        assert "好的三" in r3["output"]
        assert r3["verified"] is True
        assert len(r3["messages"]) >= len(r2["messages"])


# ============================================================
# L3：事实校验与重试链路
# ============================================================

class TestEvalL3FactCheck:
    """L3 链路：事实校验——编造拦截、重试、耗尽后免责声明"""

    # L3-01: 首次编造 → 被拦下 → 重试通过
    def test_L3_01_retry_catches_fabrication(self, sqlite_engine, logger):
        """编造保费 9999 → 校验拦截 → 重试用真实值 3200"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT premium FROM policies WHERE customer_id=1 AND status='active'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "张三的保费是9999元"},
            {"content": '{"is_factually_correct": false, "issues": ["保费编造"], "suggestion": "使用数据库真实值3200"}'},
            {"content": "张三的保费是3200元"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "张三保费多少"})

        assert result["verified"] is True
        assert result["attempts"] == 2
        assert "9999" not in result["output"], "最终输出不应保留编造值"
        assert "3200" in result["output"]

    # L3-02: 两次都编造 → 耗尽 → 追加免责声明
    def test_L3_02_retry_exhausted_adds_disclaimer(self, sqlite_engine, logger):
        """两次都编造 → 最终 verified=False + 免责声明"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT premium FROM policies WHERE customer_id=1 AND status='active'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "张三的保费是8888元"},
            {"content": '{"is_factually_correct": false, "issues": ["保费编造"], "suggestion": "用真实值"}'},
            {"content": "张三的保费是7777元"},
            {"content": '{"is_factually_correct": false, "issues": ["保费编造"], "suggestion": "必须一致"}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "张三保费"})

        assert result["verified"] is False
        assert result["attempts"] == 2
        assert "仅供参考" in result["output"], "重试耗尽后应追加免责声明"

    # L3-03: 校验器异常 → 默认放行（安全降级）
    def test_L3_03_checker_exception_default_pass(self, sqlite_engine, logger):
        """checker 返回非 JSON → 解析异常 → 默认放行"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT 1"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "正常回答"},
            {"content": "这不是合法 JSON 的内容"},  # checker 异常
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        result = agent.invoke({"input": "测试"})

        assert result["verified"] is True, "checker 异常时应默认放行（安全降级）"

    # L3-04: 流式输出包含 retry 事件
    def test_L3_04_stream_retry_event(self, sqlite_engine, logger):
        """stream() 在重试时应 yield {"type": "retry", ...}"""
        script = [
            {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT premium FROM policies WHERE customer_id=1 AND status='active'"}, "id": "tc1", "type": "tool_call"}]},
            {"content": "张三保费9999元"},
            {"content": '{"is_factually_correct": false, "issues": ["编造"], "suggestion": "用3200"}'},
            {"content": "张三的保费是3200元"},
            {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
        ]
        agent = _make_enhanced(script, sqlite_engine, logger)
        events = list(agent.stream({"input": "张三保费"}))

        retry_events = [e for e in events if e.get("type") == "retry"]
        assert len(retry_events) >= 1, "流式应产出 retry 事件"

        done = next((e for e in events if e.get("type") == "done"), None)
        assert done is not None and done.get("verified") is True

        token_events = [e for e in events if e.get("type") == "token"]
        assert len(token_events) >= 1, "流式应产出 token 事件"


# ============================================================
# L4：SQL 安全回归链路
# ============================================================

class TestEvalL4SQLSecurity:
    """L4 链路：SQL 安全——所有注入向量都被拦截，合法只读 SQL 通过"""

    # L4-01: DROP / DELETE / UPDATE / INSERT / TRUNCATE / ALTER 全拦截
    @pytest.mark.parametrize("dangerous_sql", [
        "DROP TABLE customers",
        "DELETE FROM customers",
        "UPDATE customers SET name='hacked'",
        "INSERT INTO customers VALUES (9,'赵六','13600000000','杭州')",
        "TRUNCATE TABLE customers",
        "ALTER TABLE customers ADD COLUMN hack TEXT",
    ])
    def test_L4_01_reject_write_operations(self, sqlite_engine, dangerous_sql):
        """所有写操作应被拒绝"""
        tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
        out = tools["execute_sql"].invoke({"query": dangerous_sql})
        assert "执行失败" in out or "不允许" in out, f"应拒绝: {dangerous_sql} → {out}"

    # L4-02: 多语句注入（多种绕过手法）
    @pytest.mark.parametrize("injection", [
        "SELECT 1; DROP TABLE customers",
        "SELECT * FROM customers; DELETE FROM policies",
        "SELECT 1;\nDROP TABLE customers",       # 换行绕过
        "SELECT 1;--\nDROP TABLE customers",     # 注释绕过
    ])
    def test_L4_02_reject_multi_statement(self, sqlite_engine, injection):
        """多语句注入应被拦截"""
        tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
        out = tools["execute_sql"].invoke({"query": injection})
        assert "执行失败" in out or "不允许" in out or "多条语句" in out, f"应拒绝: {injection}"

    # L4-03: 合法只读 SQL 通过（含 JOIN / 聚合 / LIKE / CTE）
    @pytest.mark.parametrize("safe_sql", [
        "SELECT * FROM customers",
        "SELECT name, premium FROM customers c JOIN policies p ON c.id=p.customer_id",
        "SELECT COUNT(*) FROM policies WHERE status='active'",
        "SELECT name FROM customers WHERE name LIKE '张%'",
        "WITH active_policies AS (SELECT * FROM policies WHERE status='active') SELECT * FROM active_policies",
    ])
    def test_L4_03_allow_readonly(self, sqlite_engine, safe_sql):
        """合法只读 SQL 应通过 check_sql 校验"""
        tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
        out = tools["check_sql"].invoke({"query": safe_sql})
        assert "校验通过" in out, f"合法 SQL 应通过: {safe_sql} → {out}"

    # L4-04: 空查询 / 纯 whitespace / 分号 被拒绝
    @pytest.mark.parametrize("empty_sql", ["", "   ", ";"])
    def test_L4_04_reject_empty(self, sqlite_engine, empty_sql):
        tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
        out = tools["execute_sql"].invoke({"query": empty_sql})
        assert "执行失败" in out or "不允许" in out, f"应拒绝空查询: '{empty_sql}'"
