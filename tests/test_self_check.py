"""自检模块单元测试：消息流提取与校验节点路由"""
from langchain_core.messages import AIMessage, ToolMessage

from agent.self_check_agent import EnhancedAgentWithSelfCheck
from conftest import ScriptedChatModel


def _make_agent(responses=None, logger=None):
    lm = ScriptedChatModel(responses=responses or [])
    return EnhancedAgentWithSelfCheck(base_agent=None, llm=lm, logger=logger)


def _messages_with_sql_result(answer="张三的保费是3200元"):
    return {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "execute_sql", "args": {}, "id": "tc1", "type": "tool_call"}]),
            ToolMessage(content="('张三', 3200.0)", tool_call_id="tc1"),
            AIMessage(content=answer),
        ]
    }


def test_extract_answer_and_db_data(logger):
    agent = _make_agent(logger=logger)
    out, db_data = agent._extract_answer_and_db_data(_messages_with_sql_result())
    assert out == "张三的保费是3200元"
    assert "张三" in db_data


def test_extract_ignores_non_sql_tool(logger):
    agent = _make_agent(logger=logger)
    msgs = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "other_tool", "args": {}, "id": "tc1", "type": "tool_call"}]),
            ToolMessage(content="xxx", tool_call_id="tc1"),
            AIMessage(content="回答"),
        ]
    }
    out, db_data = agent._extract_answer_and_db_data(msgs)
    assert out == "回答"
    assert db_data == ""


def test_should_retry_routes():
    agent = _make_agent()
    assert agent._should_retry({"verified": True, "attempts": 1}) == "end"
    assert agent._should_retry({"verified": False, "attempts": 1}) == "retry"
    assert agent._should_retry({"verified": False, "attempts": 2}) == "end"  # 重试耗尽


def test_verify_node_passes(logger):
    # checker 返回通过
    lm = ScriptedChatModel(responses=[{"content": '{"is_factually_correct": true, "issues": [], "suggestion": ""}'}])
    agent = EnhancedAgentWithSelfCheck(base_agent=None, llm=lm, logger=logger)
    state = {"final_output": "张三的保费是3200元", "db_data": "('张三', 3200.0)", "outer_db": "", "attempts": 1}
    update = agent._verify_node(state)
    assert update["verified"] is True


def test_verify_node_exhausted_adds_disclaimer(logger):
    lm = ScriptedChatModel(responses=[{"content": '{"is_factually_correct": false, "issues": ["保费编造"], "suggestion": "用真实值"}'}])
    agent = EnhancedAgentWithSelfCheck(base_agent=None, llm=lm, logger=logger)
    state = {"final_output": "张三的保费是9999元", "db_data": "('张三', 3200.0)", "outer_db": "", "attempts": 2}
    update = agent._verify_node(state)
    assert update["verified"] is False
    assert "仅供参考" in update["final_output"]
