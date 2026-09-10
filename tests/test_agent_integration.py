"""离线集成测试：多 Agent 协同链路（规则路由 → 专家 Agent → 校验 → 重试）"""
from agent.llm_factory import create_agent
from agent.self_check_agent import create_enhanced_agent
from conftest import ScriptedChatModel


def test_agent_full_retry_loop(sqlite_engine, logger):
    """编造答案被校验拦下 -> 重试 -> 校验通过"""
    script = [
        # PolicyAgent 第 1 次：编造
        {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT name, premium FROM policies WHERE customer_id=1"}, "id": "tc1", "type": "tool_call"}]},
        {"content": "张三的保费是9999元"},
        # FactCheck 第 1 次：不通过
        {"content": '{"is_factually_correct": false, "issues": ["保费编造"], "suggestion": "使用数据库真实值"}'},
        # PolicyAgent 第 2 次：修正
        {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT name, premium FROM policies WHERE customer_id=1"}, "id": "tc2", "type": "tool_call"}]},
        {"content": "张三的保费是3200元"},
        # FactCheck 第 2 次：通过
        {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
    ]
    lm = ScriptedChatModel(responses=script)
    base = create_agent(lm, sqlite_engine, logger=None)
    enh = create_enhanced_agent(base, lm, logger, db=sqlite_engine)

    res = enh.invoke({"input": "张三保费多少"})
    assert res["output"] == "张三的保费是3200元"
    assert res["verified"] is True
    assert res["attempts"] == 2


def test_agent_passes_first_try(sqlite_engine, logger):
    """首次回答即通过校验"""
    script = [
        # PolicyAgent
        {"content": "", "tool_calls": [{"name": "execute_sql", "args": {"query": "SELECT premium FROM policies WHERE customer_id=1"}, "id": "tc1", "type": "tool_call"}]},
        {"content": "张三的保费是3200元"},
        # FactCheck 通过
        {"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'},
    ]
    lm = ScriptedChatModel(responses=script)
    base = create_agent(lm, sqlite_engine, logger=None)
    enh = create_enhanced_agent(base, lm, logger, db=sqlite_engine)

    res = enh.invoke({"input": "张三保费多少"})
    assert res["output"] == "张三的保费是3200元"
    assert res["verified"] is True
    assert res["attempts"] == 1


def test_agent_graph_structure(sqlite_engine, logger):
    """多 Agent 图结构：supervisor(规则路由) + specialist_node + verify_node"""
    lm = ScriptedChatModel(responses=[])
    base = create_agent(lm, sqlite_engine, logger=None)
    enh = create_enhanced_agent(base, lm, logger, db=sqlite_engine)
    base_nodes = list(base.get_graph().nodes.keys())
    enh_nodes = list(enh.graph.get_graph().nodes.keys())
    assert "model" in base_nodes and "tools" in base_nodes
    # 多 Agent 架构节点
    assert "supervisor" in enh_nodes          # 规则路由（不消耗 LLM）
    assert "specialist_node" in enh_nodes     # 三个 SQL 专家的统一入口
    assert "verify_node" in enh_nodes         # FactCheck
