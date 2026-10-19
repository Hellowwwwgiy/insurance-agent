"""Spider dev 集 Text-to-SQL 评测脚本
独立于保险业务 Agent，用通用 schema + question 让 DeepSeek 生成 SQL，
在自建 SQLite 库（tables.json schema + 假数据）上执行，对比标准答案 SQL 的结果集算 EX。
用法: python -m agent.eval_spider --limit 100
"""
import json
import os
import random
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parent.parent
DEV_PATH = ROOT / ".dbgpt_tmp" / "eval" / "data" / "dev.json"
TABLES_PATH = ROOT / ".dbgpt_tmp" / "eval" / "data" / "tables.json"
REPORT_PATH = ROOT / "spider_eval_report.md"
DB_DIR = ROOT / ".spider_dbs"


# ---------------------------------------------------------------------------
# 1. schema 解析 + 建库 + 假数据
# ---------------------------------------------------------------------------
def _type_map(col_type: str) -> str:
    """Spider column_type -> SQLite 类型"""
    ct = col_type.lower()
    if "number" in ct or "int" in ct or ct in ("real", "float", "double"):
        return "REAL"
    if "time" in ct or "date" in ct:
        return "TEXT"
    return "TEXT"


# SQLite 保留字（用作列/表名时必须加引号）
_SQLITE_RESERVED = {
    "ABORT", "ACTION", "ADD", "AFTER", "ALL", "ALTER", "ALWAYS", "ANALYZE", "AND", "AS",
    "ASC", "ATTACH", "AUTOINCREMENT", "BEFORE", "BEGIN", "BETWEEN", "BY", "CASCADE", "CASE",
    "CAST", "CHECK", "COLLATE", "COLUMN", "COMMIT", "CONFLICT", "CONSTRAINT", "CREATE", "CROSS",
    "CURRENT", "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP", "DATABASE", "DEFAULT",
    "DEFERRABLE", "DEFERRED", "DELETE", "DESC", "DETACH", "DISTINCT", "DO", "DROP", "EACH",
    "ELSE", "END", "ESCAPE", "EXCEPT", "EXCLUDE", "EXCLUSIVE", "EXISTS", "EXPLAIN", "FILTER",
    "FOLLOWING", "FOR", "FOREIGN", "FROM", "FULL", "GENERATED", "GLOB", "GROUP", "GROUPS",
    "HAVING", "IF", "IGNORE", "IMMEDIATE", "IN", "INDEX", "INDEXED", "INITIALLY", "INNER",
    "INSERT", "INSTEAD", "INTERSECT", "INTO", "IS", "ISNULL", "JOIN", "KEY", "LEFT", "LIKE",
    "LIMIT", "MATCH", "NATURAL", "NO", "NOT", "NOTHING", "NOTNULL", "NULL", "NULLS", "OF",
    "OFFSET", "ON", "OR", "ORDER", "OTHERS", "OUTER", "OVER", "PARTITION", "PLAN", "PRAGMA",
    "PRECEDING", "PRIMARY", "QUERY", "RAISE", "RANGE", "RECURSIVE", "REFERENCES", "REGEXP",
    "REINDEX", "RELEASE", "RENAME", "REPLACE", "RESTRICT", "RETURNING", "RIGHT", "ROLLBACK",
    "ROW", "ROWS", "SAVEPOINT", "SELECT", "SET", "TABLE", "TEMP", "TEMPORARY", "THEN", "TIES",
    "TO", "TRANSACTION", "TRIGGER", "UNBOUNDED", "UNION", "UNIQUE", "UPDATE", "USING", "VACUUM",
    "VALUES", "VIEW", "VIRTUAL", "WHEN", "WHERE", "WINDOW", "WITH", "WITHOUT",
}


def _needs_quote(name: str) -> bool:
    """判断标识符是否需要加引号：含空格/特殊字符、以数字开头、或是保留字"""
    if not name.replace("_", "").isalnum():
        return True
    if name[0].isdigit():
        return True
    if name.upper() in _SQLITE_RESERVED:
        return True
    return False


# SQLite 内部保留表名，必须重命名避免冲突
_RESERVED_TABLES = {"sqlite_sequence", "sqlite_master", "sqlite_stat1", "sqlite_stat2",
                    "sqlite_stat3", "sqlite_stat4", "sqlite_schema", "sqlite_temp_master"}


def _norm_table(name: str) -> str:
    """表名规范化：空格转下划线，保留表名/`sqlite_` 前缀重命名避免冲突"""
    n = name.replace(" ", "_")
    if n.lower().startswith("sqlite_"):
        n = "tbl_" + n  # 加前缀避开 sqlite_ 保留命名空间
    if n.lower() in _RESERVED_TABLES:
        n = n + "_tbl"
    return n


def _norm(name: str) -> str:
    """Spider tables.json 用空格分隔单词，但实际数据库和 gold SQL 用下划线。统一替换。"""
    return name.replace(" ", "_")


def _quote(name: str) -> str:
    """必要时加双引号，否则原样返回（保证大小写不敏感匹配）"""
    return f'"{name}"' if _needs_quote(name) else name


def build_schema_sql(db_schema: dict) -> str:
    """根据 tables.json 的一条记录生成 CREATE TABLE 语句"""
    table_names = db_schema["table_names"]
    col_names = db_schema["column_names"]  # [[table_idx, col_name], ...]
    col_types = db_schema["column_types"]
    pks = set(db_schema.get("primary_keys", []))

    # 按表分组
    cols_by_table = defaultdict(list)
    for idx, (tidx, cname) in enumerate(col_names):
        if tidx == -1:
            continue  # '*' 占位
        cols_by_table[tidx].append((idx, cname, col_types[idx]))

    stmts = []
    for tidx, tname in enumerate(table_names):
        cols = cols_by_table.get(tidx, [])
        if not cols:
            continue
        col_defs = []
        # 该表的主键列（可能是复合主键）
        table_pks = [cidx for cidx, _, _ in cols if cidx in pks]
        for cidx, cname, ctype in cols:
            # 复合主键时不在列定义里加 PRIMARY KEY，统一在表级声明
            pk = "" if len(table_pks) > 1 else (" PRIMARY KEY" if cidx in pks else "")
            col_defs.append(f'{_quote(_norm(cname))} {_type_map(ctype)}{pk}')
        # 复合主键：表级约束
        if len(table_pks) > 1:
            pk_cols = ", ".join(_quote(_norm(c)) for ci, c, _ in cols if ci in pks)
            col_defs.append(f"PRIMARY KEY ({pk_cols})")
        stmts.append(f'CREATE TABLE IF NOT EXISTS {_quote(_norm_table(tname))} ({", ".join(col_defs)});')
    return "\n".join(stmts)


def insert_fake_data(conn: sqlite3.Connection, db_schema: dict, rows_per_table: int = 15):
    """根据 schema 生成假数据并插入，保证外键关联"""
    table_names = db_schema["table_names"]
    col_names = db_schema["column_names"]
    col_types = db_schema["column_types"]
    fks = db_schema.get("foreign_keys", [])  # [[col_idx, ref_col_idx], ...]
    pks = set(db_schema.get("primary_keys", []))

    # 先按表收集列
    cols_by_table = defaultdict(list)
    for idx, (tidx, cname) in enumerate(col_names):
        if tidx == -1:
            continue
        cols_by_table[tidx].append((idx, cname, col_types[idx]))

    # 生成每个表的数据
    table_data = {}
    for tidx, tname in enumerate(table_names):
        cols = cols_by_table.get(tidx, [])
        if not cols:
            continue
        rows = []
        for r in range(rows_per_table):
            row = []
            for cidx, cname, ctype in cols:
                ct = ctype.lower()
                if cidx in pks:
                    row.append(r + 1)
                elif "number" in ct or ct in ("real", "float", "double", "int"):
                    row.append(random.randint(1, 1000) if "int" in ct else round(random.uniform(1, 10000), 2))
                elif "time" in ct or "date" in ct:
                    row.append(f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}")
                else:
                    row.append(f"{cname[:4]}_{r+1}")
            rows.append(row)
        table_data[tidx] = rows

    # 处理外键：把外键列的值替换成引用表主键的值
    for fk_col, ref_col in fks:
        # 找到外键列属于哪个表
        fk_tidx = None
        ref_tidx = None
        for idx, (tidx, _) in enumerate(col_names):
            if idx == fk_col:
                fk_tidx = tidx
            if idx == ref_col:
                ref_tidx = tidx
        if fk_tidx is None or ref_tidx is None:
            continue
        fk_rows = table_data.get(fk_tidx, [])
        ref_rows = table_data.get(ref_tidx, [])
        if not fk_rows or not ref_rows:
            continue
        # 找外键列在 fk 表中的位置和引用主键列在 ref 表中的位置
        fk_cols = cols_by_table[fk_tidx]
        ref_cols = cols_by_table[ref_tidx]
        fk_pos = next((i for i, (ci, _, _) in enumerate(fk_cols) if ci == fk_col), None)
        ref_pk_pos = next((i for i, (ci, _, _) in enumerate(ref_cols) if ci == ref_col), None)
        if fk_pos is None or ref_pk_pos is None:
            continue
        ref_values = [row[ref_pk_pos] for row in ref_rows]
        # 关键修复：若外键列同时是主键，必须保证值不重复（1:1 关系，如 employee_hire_evaluation）
        if fk_col in pks:
            unique_ref = list(dict.fromkeys(ref_values))
            if len(unique_ref) >= len(fk_rows):
                sampled = random.sample(unique_ref, len(fk_rows))
            else:
                # 引用表唯一值不足，循环填充（极端情况，PK 约束可能仍冲突）
                sampled = (unique_ref * ((len(fk_rows) // len(unique_ref)) + 1))[:len(fk_rows)]
            for row, val in zip(fk_rows, sampled):
                row[fk_pos] = val
        else:
            for row in fk_rows:
                row[fk_pos] = random.choice(ref_values)

    # 插入
    for tidx, tname in enumerate(table_names):
        cols = cols_by_table.get(tidx, [])
        if not cols:
            continue
        col_names_str = ", ".join(_quote(_norm(c)) for _, c, _ in cols)
        placeholders = ", ".join(["?"] * len(cols))
        conn.executemany(
            f'INSERT INTO {_quote(_norm_table(tname))} ({col_names_str}) VALUES ({placeholders})',
            table_data[tidx],
        )


def build_db(db_schema: dict) -> sqlite3.Connection:
    """为一个 db 建库（内存）并填假数据"""
    conn = sqlite3.connect(":memory:")
    conn.executescript(build_schema_sql(db_schema))
    insert_fake_data(conn, db_schema)
    return conn


# ---------------------------------------------------------------------------
# 2. LLM 生成 SQL
# ---------------------------------------------------------------------------
PROMPT = """You are a text-to-SQL expert. Given the database schema (with foreign keys) and a natural language question, generate a single SQLite SQL query that answers the question.

Schema (table: columns):
{schema}

Foreign keys:
{fks}

Question: {question}

Rules:
- Use ONLY the table and column names listed above.
- For multi-table queries, JOIN on the foreign keys listed.
- Output a single SQL statement, no explanation, no markdown code fences."""


def generate_sql(llm: ChatOpenAI, db_schema: dict, question: str) -> str:
    """调用 LLM 生成 SQL"""
    table_names = db_schema["table_names"]
    col_names = db_schema["column_names"]
    col_types = db_schema["column_types"]
    fks = db_schema.get("foreign_keys", [])

    cols_by_table = defaultdict(list)
    for idx, (tidx, cname) in enumerate(col_names):
        if tidx == -1:
            continue
        cols_by_table[tidx].append((cname, col_types[idx]))

    schema_lines = []
    for tidx, tname in enumerate(table_names):
        cols = ", ".join(f"{_norm(c)}({t})" for c, t in cols_by_table.get(tidx, []))
        schema_lines.append(f"{_norm_table(tname)}: {cols}")
    schema_text = "\n".join(schema_lines)

    # 外键描述
    fk_lines = []
    for fk_col, ref_col in fks:
        fk_tidx = col_names[fk_col][0]
        ref_tidx = col_names[ref_col][0]
        if fk_tidx == -1 or ref_tidx == -1:
            continue
        fk_table = _norm_table(table_names[fk_tidx])
        fk_col_name = _norm(col_names[fk_col][1])
        ref_table = _norm_table(table_names[ref_tidx])
        ref_col_name = _norm(col_names[ref_col][1])
        fk_lines.append(f"{fk_table}.{fk_col_name} -> {ref_table}.{ref_col_name}")
    fk_text = "\n".join(fk_lines) if fk_lines else "none"

    try:
        resp = llm.invoke(PROMPT.format(schema=schema_text, fks=fk_text, question=question))
        sql = resp.content.strip()
        # 去掉可能的 markdown 代码块
        if sql.startswith("```"):
            sql = sql.split("```")[1]
            if sql.startswith("sql"):
                sql = sql[3:]
            sql = sql.strip()
        # 去掉末尾分号
        sql = sql.rstrip(";").strip()
        return sql
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# 3. EX 计算
# ---------------------------------------------------------------------------
def exec_sql(conn: sqlite3.Connection, sql: str):
    """执行 SQL，返回 (rows, error)"""
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        return rows, None
    except Exception as e:
        return None, str(e)


def normalize_rows(rows):
    """标准化结果集：排序 + 转 tuple，忽略行顺序"""
    if rows is None:
        return None
    return sorted(tuple(r) for r in rows)


# ---------------------------------------------------------------------------
# 4. 主流程
# ---------------------------------------------------------------------------
def main(limit: int = 100):
    random.seed(42)
    dev = json.load(open(DEV_PATH, encoding="utf-8"))
    tables_list = json.load(open(TABLES_PATH, encoding="utf-8"))
    schema_by_db = {t["db_id"]: t for t in tables_list}

    # 按 db 均匀选样本
    by_db = defaultdict(list)
    for s in dev:
        by_db[s["db_id"]].append(s)
    selected = []
    db_list = sorted(by_db.keys())
    for db in db_list:
        samples = by_db[db]
        random.shuffle(samples)
        selected.extend(samples[: max(1, limit // len(db_list))])
    random.shuffle(selected)
    selected = selected[:limit]
    print(f"选中 {len(selected)} 条样本，覆盖 {len(set(s['db_id'] for s in selected))} 个数据库")

    # LLM
    from agent.config import load_environment
    settings = load_environment()
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com/v1",
        temperature=0.0,
        timeout=60,
    )

    results = []
    ex_pass = 0
    exec_pass = 0  # 生成的 SQL 能成功执行
    t0 = time.time()

    for i, sample in enumerate(selected):
        db_id = sample["db_id"]
        question = sample["question"]
        gold_sql = sample["query"]
        schema = schema_by_db[db_id]

        conn = build_db(schema)
        # 标准答案执行
        gold_rows, gold_err = exec_sql(conn, gold_sql)

        # LLM 生成
        pred_sql = generate_sql(llm, schema, question)
        pred_rows, pred_err = exec_sql(conn, pred_sql)

        ex_ok = False
        if gold_err is None and pred_err is None:
            exec_pass += 1
            ex_ok = normalize_rows(gold_rows) == normalize_rows(pred_rows)
        if ex_ok:
            ex_pass += 1

        results.append({
            "db_id": db_id,
            "question": question,
            "gold_sql": gold_sql,
            "pred_sql": pred_sql,
            "ex_ok": ex_ok,
            "gold_err": gold_err,
            "pred_err": pred_err,
        })
        conn.close()

        if (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(f"[{i+1}/{len(selected)}] EX={ex_pass}/{i+1} ({ex_pass/(i+1)*100:.1f}%)  exec={exec_pass}/{i+1}  {elapsed:.0f}s")

    total = len(selected)
    ex_rate = ex_pass / total * 100
    exec_rate = exec_pass / total * 100
    elapsed = time.time() - t0

    # 写报告
    lines = [
        "# Spider dev 集评测报告",
        "",
        f"- 样本数: **{total}**",
        f"- EX (Execution Accuracy): **{ex_rate:.1f}%** ({ex_pass}/{total})",
        f"- Executable Rate: **{exec_rate:.1f}%** ({exec_pass}/{total})",
        f"- 模型: DeepSeek deepseek-chat",
        f"- 耗时: {elapsed:.0f}s",
        "",
        "> 注：数据库由 Spider tables.json schema 重建并填充假数据（保证外键关联）。",
        "> EX = 生成 SQL 与标准答案 SQL 在同一数据库上执行结果集一致（忽略行/列顺序）。",
        "",
        "## 失败案例（前 10 条 EX 不通过）",
        "",
        "| db_id | question | gold | pred | 原因 |",
        "|-------|----------|------|------|------|",
    ]
    fail_count = 0
    for r in results:
        if not r["ex_ok"] and fail_count < 10:
            reason = "pred执行错误" if r["pred_err"] else "结果集不一致"
            q = r["question"][:50].replace("|", "/")
            lines.append(f"| {r['db_id']} | {q} | `{r['gold_sql'][:60]}` | `{r['pred_sql'][:60]}` | {reason} |")
            fail_count += 1

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{'='*50}")
    print(f"Spider EX = {ex_rate:.1f}%  ({ex_pass}/{total})")
    print(f"Executable = {exec_rate:.1f}%")
    print(f"报告: {REPORT_PATH}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    main(args.limit)
