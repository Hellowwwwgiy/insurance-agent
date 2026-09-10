from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置：从 .env 或环境变量加载，类型安全、可注入、易测试"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    deepseek_api_key: str
    db_user: str
    db_password: str
    db_host: str
    db_port: int
    db_name: str
    log_level: str = "INFO"
    log_dir: str = "./logs"


def load_environment() -> Settings:
    """加载 .env 并返回校验后的配置对象（字段缺失时抛 ValidationError）"""
    return Settings()
