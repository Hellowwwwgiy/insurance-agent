"""
配置管理模块
"""
import os
from typing import Optional
from urllib.parse import quote_plus

class Config:
    """应用配置类"""
    
    # ========== 数据库配置 ==========
    DB_USER: str = os.getenv("DB_USER", "agent_user")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "agent_secret")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "insurance_db")
    
    @property
    def db_uri(self) -> str:
        """生成数据库连接 URI"""
        encoded_password = quote_plus(self.DB_PASSWORD)
        return f"postgresql://{self.DB_USER}:{encoded_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # ========== LLM 配置 ==========
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    LLM_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "sk-")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0"))
    
    # ========== 日志配置 ==========
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # ========== Agent 配置 ==========
    AGENT_TYPE: str = os.getenv("AGENT_TYPE", "openai-tools")
    AGENT_MAX_ITERATIONS: int = int(os.getenv("AGENT_MAX_ITERATIONS", "3"))
    AGENT_VERBOSE: bool = os.getenv("AGENT_VERBOSE", "true").lower() == "true"
    
    # ========== 其他配置 ==========
    SAMPLE_ROWS_IN_TABLE_INFO: int = 3
    
    @classmethod
    def validate(cls) -> bool:
        """验证必要配置是否存在"""
        required = [
            ("DB_USER", cls.DB_USER),
            ("DB_PASSWORD", cls.DB_PASSWORD),
            ("DB_HOST", cls.DB_HOST),
            ("DB_NAME", cls.DB_NAME),
            ("LLM_API_KEY", cls.LLM_API_KEY),
        ]
        
        missing = [name for name, value in required if not value]
        if missing:
            raise ValueError(f"❌ 缺少必要配置: {', '.join(missing)}")
        
        return True
    
    def __repr__(self) -> str:
        """友好的配置展示"""
        return (
            f"Config(DB={self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}, "
            f"LLM={self.LLM_MODEL}, LogDir={self.LOG_DIR})"
        )
