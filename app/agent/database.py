"""
数据库管理模块
"""
import logging
from typing import List, Optional, Dict, Any
from langchain_community.utilities import SQLDatabase

logger = logging.getLogger(__name__)

class DatabaseManager:
    """数据库连接和管理类"""
    
    def __init__(self, db_uri: str, sample_rows: int = 3):
        """
        初始化数据库管理器
        
        Args:
            db_uri: 数据库连接 URI
            sample_rows: 表信息中包含的示例行数
        """
        self.db_uri = db_uri
        self.sample_rows = sample_rows
        self.db: Optional[SQLDatabase] = None
        
    def connect(self) -> bool:
        """连接数据库"""
        try:
            logger.info("⏳ 正在连接数据库...")
            
            self.db = SQLDatabase.from_uri(
                self.db_uri,
                sample_rows_in_table_info=self.sample_rows,
                engine_args={
                    "connect_args": {
                        "client_encoding": "UTF8",
                        "options": "-c client_encoding=UTF8"
                    }
                }
            )
            
            logger.info("✅ 数据库连接成功！")
            logger.info(f"📊 可用表: {self.get_table_names()}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 数据库连接失败: {e}", exc_info=True)
            return False
    
    def get_table_names(self) -> List[str]:
        """获取所有可用表名"""
        if self.db:
            return self.db.get_usable_table_names()
        return []
    
    def get_table_info(self, table_name: str) -> str:
        """获取表的详细信息"""
        if self.db:
            return self.db.get_table_info([table_name])
        return ""
    
    def execute_query(self, query: str) -> Any:
        """执行 SQL 查询"""
        if self.db:
            return self.db.run(query)
        return None
    
    def close(self):
        """关闭数据库连接"""
        if self.db:
            logger.info("🔌 正在关闭数据库连接...")
            # SQLAlchemy 会自动管理连接池，无需手动关闭
            logger.info("✅ 数据库连接已关闭")
    
    def __enter__(self):
        """上下文管理器支持"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时关闭连接"""
        self.close()
