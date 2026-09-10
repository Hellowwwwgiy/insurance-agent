"""手写 SQL 工具集：基于 SQLAlchemy 直接访问数据库，替代弃用的 langchain-community SQLDatabaseToolkit"""
from typing import List
from langchain_core.tools import tool, StructuredTool
from sqlalchemy import Engine, text

# 只读 SQL 允许的首关键字
_READONLY_KEYWORDS = ("SELECT", "WITH")
_MAX_SCHEMA_ROWS = 5


def _validate_readonly(query: str) -> str:
    """校验 SQL 是否只读，返回规范化后的语句；不合法时抛 ValueError"""
    stmt = query.strip().rstrip(";").strip()
    if not stmt:
        raise ValueError("SQL 语句为空")

    # 拒绝多语句（防 SELECT 1; DROP TABLE 注入）
    if ";" in stmt:
        raise ValueError("不允许执行多条语句，每次只能执行一条只读 SQL")

    keyword = stmt.split()[0].upper()
    if keyword not in _READONLY_KEYWORDS:
        raise ValueError(f"只允许执行只读查询（{', '.join(_READONLY_KEYWORDS)}），当前语句以 {keyword} 开头")
    return stmt


def make_sql_tools(engine: Engine) -> List[StructuredTool]:
    """从 SQLAlchemy Engine 构建 SQL 工具列表"""

    @tool
    def list_tables() -> str:
        """列出数据库中的所有表名，返回以逗号分隔的表名列表。"""
        from sqlalchemy import inspect
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            return f"可用表: {', '.join(tables) if tables else '无'}"
        except Exception as e:
            return f"获取表列表失败: {type(e).__name__}: {e}"

    @tool
    def get_table_schema(table_name: str) -> str:
        """获取指定表的列名、类型、主键，并附最多 5 行示例数据，帮助理解表内容。"""
        from sqlalchemy import inspect
        try:
            inspector = inspect(engine)
            columns = inspector.get_columns(table_name)
            pk = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
            lines = [f"表: {table_name}"]
            for col in columns:
                pk_flag = " [主键]" if col["name"] in pk else ""
                lines.append(f"  - {col['name']} ({col['type']}){pk_flag}")
            # 示例数据
            try:
                with engine.connect() as conn:
                    rows = conn.execute(text(f"SELECT * FROM {table_name} LIMIT {_MAX_SCHEMA_ROWS}")).fetchall()
                if rows:
                    lines.append(f"示例数据（最多 {_MAX_SCHEMA_ROWS} 行）:")
                    for row in rows:
                        lines.append(f"  {tuple(row)}")
            except Exception as e:
                lines.append(f"（示例数据获取失败: {type(e).__name__}）")
            return "\n".join(lines)
        except Exception as e:
            return f"获取表结构失败: {type(e).__name__}: {e}"

    @tool
    def check_sql(query: str) -> str:
        """校验 SQL 是否只读（SELECT/WITH 开头、单条语句）且语法可执行，返回校验结果，不执行查询。"""
        try:
            stmt = _validate_readonly(query)
            with engine.connect() as conn:
                conn.execute(text(f"EXPLAIN {stmt}")).fetchall()
            return "校验通过：该 SQL 为只读查询且可执行"
        except Exception as e:
            return f"校验失败: {type(e).__name__}: {e}"

    @tool
    def execute_sql(query: str) -> str:
        """执行只读 SQL 查询（仅允许 SELECT/WITH 单条语句），返回查询结果，每行一条记录。"""
        try:
            stmt = _validate_readonly(query)
            with engine.connect() as conn:
                rows = conn.execute(text(stmt)).fetchall()
            if not rows:
                return "查询完成，无结果返回"
            return "\n".join(str(tuple(row)) for row in rows)
        except Exception as e:
            return f"执行失败: {type(e).__name__}: {e}"

    return [list_tables, get_table_schema, check_sql, execute_sql]
