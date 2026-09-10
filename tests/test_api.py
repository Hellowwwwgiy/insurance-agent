"""Web API 测试：/health 与 /query（注入假依赖，全程离线）"""
import pytest
from fastapi.testclient import TestClient

import agent.api as api
from agent.config import Settings
from conftest import ScriptedChatModel

FAKE_SETTINGS = Settings(
    deepseek_api_key="sk-test", db_user="u", db_password="p",
    db_host="localhost", db_port=5432, db_name="n",
)


class FakeEnhancedAgent:
    def invoke(self, inputs, **kwargs):
        return {"output": "张三的保费是3200元", "verified": True, "attempts": 1, "messages": []}

    def stream(self, inputs, **kwargs):
        yield {"type": "token", "content": "张三"}
        yield {"type": "token", "content": "的保费是3200元"}
        yield {"type": "done", "answer": "张三的保费是3200元", "verified": True, "attempts": 1, "messages": []}


@pytest.fixture
def offline_app(monkeypatch, fake_engine):
    """替换所有外部依赖，使 lifespan 全程离线"""
    monkeypatch.setattr(api, "load_environment", lambda: FAKE_SETTINGS)
    monkeypatch.setattr(api, "create_database_connection", lambda settings, logger=None: fake_engine)
    monkeypatch.setattr(api, "create_llm", lambda settings, logger=None: ScriptedChatModel(responses=[]))
    monkeypatch.setattr(api, "create_agent", lambda llm, db, logger=None: object())
    monkeypatch.setattr(api, "create_enhanced_agent", lambda base, llm, logger=None, db=None: FakeEnhancedAgent())
    return api.app


def test_health(offline_app):
    with TestClient(offline_app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_query(offline_app):
    with TestClient(offline_app) as client:
        resp = client.post("/query", json={"question": "张三保费多少"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "张三的保费是3200元"
        assert body["verified"] is True
        assert body["attempts"] == 1


def test_query_with_db_result(offline_app):
    with TestClient(offline_app) as client:
        resp = client.post("/query", json={"question": "张三保费多少", "db_result": "外部上下文"})
        assert resp.status_code == 200
        assert resp.json()["answer"] == "张三的保费是3200元"


def test_query_validation_error(offline_app):
    with TestClient(offline_app) as client:
        resp = client.post("/query", json={})
        assert resp.status_code == 422


def test_query_stream(offline_app):
    with TestClient(offline_app) as client:
        with client.stream("POST", "/query/stream", json={"question": "张三保费多少"}) as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes()).decode("utf-8")
        assert "张三" in body
        assert '"type": "done"' in body
        assert '"verified": true' in body
        assert '"type": "session"' in body
