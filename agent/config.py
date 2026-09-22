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
    db_user: str = "insurance"
    db_password: str = "insurance_pass"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "insurance_db"
    log_level: str = "INFO"
    log_dir: str = "./logs"


def load_environment() -> Settings:
    """加载 .env 并返回校验后的配置对象（字段缺失时抛 ValidationError）"""
    return Settings()
