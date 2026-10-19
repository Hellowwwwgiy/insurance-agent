import os
import random
from urllib.parse import quote_plus
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool

from .config import Settings


def _load_sqlite_seed(engine: Engine) -> None:
    """向 SQLite 引擎注入种子数据。
    schema 与 docker/init.sql（PostgreSQL）完全一致：
      customers(id, name, phone, address, age)
      policies(id, policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date)
      claims(id, claim_no, policy_id, customer_id, claim_date, claim_type, claim_amount, approved_amount, status, description)
      underwriting(id, policy_id, customer_id, underwrite_date, health_score, risk_level, decision, extra_premium_rate, notes)
      renewal(id, policy_id, customer_id, renewal_date, previous_end_date, new_end_date, premium, status, discount_rate)
    """
    random.seed(42)
    with engine.begin() as conn:
        # 与 PostgreSQL init.sql 对齐（SQLite 无 SERIAL/REFERENCES/DATE，用等价类型）
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                address TEXT,
                age INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS policies (
                id INTEGER PRIMARY KEY,
                policy_no TEXT UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                product TEXT,
                premium REAL,
                insured_amount REAL,
                status TEXT DEFAULT 'active',
                start_date TEXT,
                end_date TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY,
                claim_no TEXT UNIQUE NOT NULL,
                policy_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                claim_date TEXT,
                claim_type TEXT,
                claim_amount REAL,
                approved_amount REAL,
                status TEXT DEFAULT 'pending',
                description TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS underwriting (
                id INTEGER PRIMARY KEY,
                policy_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                underwrite_date TEXT,
                health_score INTEGER,
                risk_level TEXT,
                decision TEXT,
                extra_premium_rate REAL,
                notes TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS renewal (
                id INTEGER PRIMARY KEY,
                policy_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                renewal_date TEXT,
                previous_end_date TEXT,
                new_end_date TEXT,
                premium REAL,
                status TEXT DEFAULT 'pending',
                discount_rate REAL
            )
        """))
        for t in ("renewal", "underwriting", "claims", "policies", "customers"):
            conn.execute(text(f"DELETE FROM {t}"))
        try:
            conn.execute(text("DELETE FROM sqlite_sequence WHERE name IN ('customers','policies','claims','underwriting','renewal')"))
        except Exception:
            pass

        # 种子客户（与 init.sql 一致）
        conn.execute(text("INSERT INTO customers (id, name, phone, address, age) VALUES (:id,:name,:phone,:addr,:age)"), [
            {"id": 1, "name": "张三", "phone": "13800138000", "addr": "北京市朝阳区", "age": 32},
            {"id": 2, "name": "李四", "phone": "13900139999", "addr": "上海市浦东新区", "age": 28},
            {"id": 3, "name": "王五", "phone": "13700137000", "addr": "广州市天河区", "age": 45},
        ])
        # 种子保单（与 init.sql 一致）
        conn.execute(text("""
            INSERT INTO policies (id, policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date)
            VALUES (:id,:pn,:cid,:prod,:prem,:ia,:st,:sd,:ed)
        """), [
            {"id": 1, "pn": "P20250405001", "cid": 1, "prod": "安心健康保", "prem": 3200.00, "ia": 500000.00, "st": "active",  "sd": "2025-04-05", "ed": "2045-04-04"},
            {"id": 2, "pn": "P20250405002", "cid": 1, "prod": "终身寿险",   "prem": 3000.00, "ia": 800000.00, "st": "active",  "sd": "2024-01-15", "ed": "2074-01-14"},
            {"id": 3, "pn": "P20250405003", "cid": 3, "prod": "综合意外险", "prem": 1800.00, "ia": 300000.00, "st": "expired", "sd": "2023-06-01", "ed": "2024-05-31"},
        ])
        # 种子理赔（与 init.sql 一致）
        conn.execute(text("""
            INSERT INTO claims (id, claim_no, policy_id, customer_id, claim_date, claim_type, claim_amount, approved_amount, status, description)
            VALUES (:id,:cn,:pid,:cid,:cd,:ct,:cam,:aam,:st,:desc)
        """), [
            {"id": 1, "cn": "C202501001", "pid": 1, "cid": 1, "cd": "2025-06-10", "ct": "住院", "cam": 28000.00, "aam": 24500.00, "st": "paid",  "desc": "急性阑尾炎住院手术"},
            {"id": 2, "cn": "C202501002", "pid": 1, "cid": 1, "cd": "2025-09-15", "ct": "门诊", "cam": 3200.00,  "aam": 2800.00,  "st": "paid",  "desc": "常规体检门诊复查"},
            {"id": 3, "cn": "C202501003", "pid": 3, "cid": 3, "cd": "2024-03-20", "ct": "意外", "cam": 15000.00, "aam": 12000.00, "st": "paid",  "desc": "交通事故意外医疗"},
        ])
        # 种子核保（与 init.sql 一致）
        conn.execute(text("""
            INSERT INTO underwriting (id, policy_id, customer_id, underwrite_date, health_score, risk_level, decision, extra_premium_rate, notes)
            VALUES (:id,:pid,:cid,:ud,:hs,:rl,:dec,:epr,:notes)
        """), [
            {"id": 1, "pid": 1, "cid": 1, "ud": "2025-04-01", "hs": 85, "rl": "low",    "dec": "approved",      "epr": 0.0,  "notes": "体检正常，标准承保"},
            {"id": 2, "pid": 2, "cid": 1, "ud": "2024-01-10", "hs": 78, "rl": "medium", "dec": "extra_premium", "epr": 0.15, "notes": "轻度脂肪肝，加费 15%"},
            {"id": 3, "pid": 3, "cid": 3, "ud": "2023-05-28", "hs": 92, "rl": "low",    "dec": "approved",      "epr": 0.0,  "notes": "健康状况良好"},
        ])
        # 种子续保（与 init.sql 一致）
        conn.execute(text("""
            INSERT INTO renewal (id, policy_id, customer_id, renewal_date, previous_end_date, new_end_date, premium, status, discount_rate)
            VALUES (:id,:pid,:cid,:rd,:ped,:ned,:prem,:st,:dr)
        """), [
            {"id": 1, "pid": 2, "cid": 1, "rd": "2024-01-10", "ped": "2024-01-14", "ned": "2075-01-14", "prem": 3000.00, "st": "confirmed", "dr": 0.0},
            {"id": 2, "pid": 3, "cid": 3, "rd": "2024-05-20", "ped": "2024-05-31", "ned": None,         "prem": 1800.00, "st": "lapsed",    "dr": None},
        ])

        # 扩产到 300 客户 + 350 保单 + 理赔/核保/续保（与 init.sql 一致规模）
        seed_names = ["陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林"]
        cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "重庆", "西安", "苏州", "天津", "长沙", "青岛", "郑州"]
        products = ["安心健康保", "终身寿险", "综合意外险", "重疾无忧", "齿科医疗险"]
        statuses = ["active", "active", "active", "expired", "pending"]
        claim_types = ["住院", "手术", "门诊", "意外", "重疾"]
        claim_statuses = ["pending", "approved", "rejected", "paid", "paid"]
        risk_levels = ["low", "low", "low", "medium", "high"]
        uw_decisions = ["approved", "approved", "approved", "rejected", "extra_premium"]
        renewal_statuses = ["confirmed", "confirmed", "lapsed", "pending"]

        cust_batch, pol_batch = [], []
        claim_batch, uw_batch, renew_batch = [], [], []
        for i in range(4, 301):
            cust_batch.append({
                "id": i,
                "name": seed_names[(i - 4) % 15] + "客户" + f"{i:03d}",
                "phone": "13" + f"{(80000000 + i * 137) % 100000000:08d}",
                "addr": cities[(i - 4) % 15] + "市某区",
                "age": 22 + ((i - 4) % 50),
            })

        for p in range(1, 351):
            cid = 1 + ((p - 1) % 300)
            pol_batch.append({
                "id": 3 + p,
                "pn": "P2025" + f"{p:06d}",
                "cid": cid,
                "prod": products[(p - 1) % 5],
                "prem": 1000 + ((p - 1) * 17) % 9000,
                "ia": 100000 + ((p - 1) * 31) % 900000,
                "st": statuses[(p - 1) % 5],
                "sd": "2020-01-01",
                "ed": "2020-01-01",
            })
            # 每个保单 1 条核保（id 从 4 开始，避开种子 1-3）
            uw_batch.append({
                "id": 3 + p,
                "pid": 3 + p,
                "cid": cid,
                "ud": "2020-01-01",
                "hs": 60 + ((p - 1) * 3) % 40,
                "rl": risk_levels[(p - 1) % 5],
                "dec": uw_decisions[(p - 1) % 5],
                "epr": 0.1 + ((p - 1) % 5) * 0.05 if uw_decisions[(p - 1) % 5] == "extra_premium" else 0.0,
                "notes": "自动生成核保记录",
            })
            # 30% 保单有理赔
            if p % 3 == 0:
                claim_batch.append({
                    "id": len(claim_batch) + 4,
                    "cn": f"C{p:08d}",
                    "pid": 3 + p,
                    "cid": cid,
                    "cd": "2020-03-01",
                    "ct": claim_types[(p - 1) % 5],
                    "cam": 5000 + ((p - 1) * 13) % 95000,
                    "aam": 4000 + ((p - 1) * 11) % 80000,
                    "st": claim_statuses[(p - 1) % 5],
                    "desc": "自动生成理赔记录",
                })
            # expired 保单有续保记录
            if statuses[(p - 1) % 5] == "expired":
                renew_batch.append({
                    "id": len(renew_batch) + 3,
                    "pid": 3 + p,
                    "cid": cid,
                    "rd": "2020-01-01",
                    "ped": "2020-01-01",
                    "ned": None,
                    "prem": 1000 + ((p - 1) * 17) % 9000,
                    "st": renewal_statuses[(p - 1) % 4],
                    "dr": 0.05 if renewal_statuses[(p - 1) % 4] == "confirmed" else None,
                })

        if cust_batch:
            conn.execute(text("INSERT INTO customers (id, name, phone, address, age) VALUES (:id,:name,:phone,:addr,:age)"), cust_batch)
        if pol_batch:
            conn.execute(text("INSERT INTO policies (id, policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date) VALUES (:id,:pn,:cid,:prod,:prem,:ia,:st,:sd,:ed)"), pol_batch)
        if claim_batch:
            conn.execute(text("INSERT INTO claims (id, claim_no, policy_id, customer_id, claim_date, claim_type, claim_amount, approved_amount, status, description) VALUES (:id,:cn,:pid,:cid,:cd,:ct,:cam,:aam,:st,:desc)"), claim_batch)
        if uw_batch:
            conn.execute(text("INSERT INTO underwriting (id, policy_id, customer_id, underwrite_date, health_score, risk_level, decision, extra_premium_rate, notes) VALUES (:id,:pid,:cid,:ud,:hs,:rl,:dec,:epr,:notes)"), uw_batch)
        if renew_batch:
            conn.execute(text("INSERT INTO renewal (id, policy_id, customer_id, renewal_date, previous_end_date, new_end_date, premium, status, discount_rate) VALUES (:id,:pid,:cid,:rd,:ped,:ned,:prem,:st,:dr)"), renew_batch)


def create_database_connection(settings: Settings, logger=None) -> Engine:
    """创建并返回 SQLAlchemy Engine 实例。
    默认连 PostgreSQL；若连接失败则自动降级到内存 SQLite + 种子数据，
    方便开发环境零依赖直接跑。
    """
    db_uri = (
        f"postgresql+psycopg2://{settings.db_user}:{quote_plus(settings.db_password)}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )

    if logger:
        logger.info(f"🔧 连接 PostgreSQL: {settings.db_host}:{settings.db_port}/{settings.db_name}")
        logger.info("⏳ 正在连接数据库...")

    try:
        engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            connect_args={"client_encoding": "UTF8", "options": "-c client_encoding=UTF8"},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        if logger:
            logger.info("✅ PostgreSQL 连接成功！")
        return engine
    except Exception as e:
        if logger:
            logger.warning(f"⚠️  PostgreSQL 连接失败: {e}")
            logger.info("🔄 自动降级到 SQLite 内存库 + 种子数据...")

        sqlite_uri = "sqlite:///:memory:"
        engine = create_engine(
            sqlite_uri,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _load_sqlite_seed(engine)

        if logger:
            with engine.connect() as conn:
                cust_cnt = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()
                pol_cnt = conn.execute(text("SELECT COUNT(*) FROM policies")).scalar()
            logger.info(f"✅ SQLite 降级成功！种子数据: {cust_cnt} 客户 + {pol_cnt} 保单")
        return engine
