"""SQL 工具单元测试：只读保护与工具行为"""
from agent.sql_tools import make_sql_tools


def test_tool_names(sqlite_engine):
    tools = make_sql_tools(sqlite_engine)
    assert [t.name for t in tools] == ["list_tables", "get_table_schema", "check_sql", "execute_sql"]


def test_list_tables(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["list_tables"].invoke({})
    assert "customers" in out


def test_get_table_schema(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["get_table_schema"].invoke({"table_name": "customers"})
    assert "name" in out and "phone" in out and "示例数据" in out


def test_get_table_schema_missing_table(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["get_table_schema"].invoke({"table_name": "not_exists"})
    assert "失败" in out


def test_check_sql_ok(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["check_sql"].invoke({"query": "SELECT name FROM customers"})
    assert "校验通过" in out


def test_check_sql_bad(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["check_sql"].invoke({"query": "DELETE FROM customers"})
    assert "校验失败" in out


def test_execute_sql_ok(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["execute_sql"].invoke({
        "query": "SELECT c.name, p.premium FROM customers c JOIN policies p ON c.id = p.customer_id WHERE c.id=1 AND p.status='active'"
    })
    assert "张三" in out and "3200" in out


def test_execute_sql_empty_result(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["execute_sql"].invoke({"query": "SELECT * FROM customers WHERE id=999"})
    assert "无结果" in out


# ---- 只读保护 ----

def test_execute_sql_rejects_drop(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["execute_sql"].invoke({"query": "DROP TABLE customers"})
    assert "执行失败" in out


def test_execute_sql_rejects_insert(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["execute_sql"].invoke({"query": "INSERT INTO customers VALUES (9,'赵六','13600000000','杭州')"})
    assert "执行失败" in out


def test_execute_sql_rejects_multi_statement(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["execute_sql"].invoke({"query": "SELECT 1; DROP TABLE customers"})
    assert "执行失败" in out


def test_execute_sql_rejects_empty(sqlite_engine):
    tools = {t.name: t for t in make_sql_tools(sqlite_engine)}
    out = tools["execute_sql"].invoke({"query": "   "})
    assert "执行失败" in out
