from urllib.parse import quote_plus
from sqlalchemy import Engine, create_engine

from .config import Settings

def create_database_connection(settings: Settings, logger=None) -> Engine:
    """创建并返回 SQLAlchemy Engine 实例"""
    db_uri = (
        f"postgresql+psycopg2://{settings.db_user}:{quote_plus(settings.db_password)}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )

    if logger:
        logger.info(f"🔧 连接数据库: {settings.db_host}:{settings.db_port}/{settings.db_name}")
        logger.info("⏳ 正在连接数据库...")

    engine = create_engine(
        db_uri,
        pool_pre_ping=True,
        connect_args={
            "client_encoding": "UTF8",
            "options": "-c client_encoding=UTF8"
        }
    )

    if logger:
        logger.info(f"✅ 数据库连接成功！")

    return engine
