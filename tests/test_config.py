"""配置层单元测试：Settings 映射与缺失校验"""
import pytest
from pydantic import ValidationError

from agent.config import Settings

ALL_FIELDS = {
    "DEEPSEEK_API_KEY": "sk-test-key",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_pass",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "insurance_db",
}


def test_settings_env_mapping(monkeypatch):
    for k, v in ALL_FIELDS.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)  # 跳过 .env 文件，仅用环境变量
    assert s.deepseek_api_key == "sk-test-key"
    assert s.db_user == "test_user"
    assert s.db_password == "test_pass"
    assert s.db_host == "localhost"
    assert s.db_port == 5432  # int 类型自动转换
    assert s.db_name == "insurance_db"


def test_settings_default_log_level(monkeypatch):
    for k, v in ALL_FIELDS.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.log_level == "INFO"


def test_settings_missing_field_raises(monkeypatch):
    for k in ALL_FIELDS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
