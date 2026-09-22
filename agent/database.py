import os
import random
from urllib.parse import quote_plus
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool

from .config import Settings


def _load_sqlite_seed(engine: Engine) -> None:
    """向 SQLite 引擎注入种子数据（与 tests/conftest.py 保持一致）"""
    random.seed(42)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, city TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS policies (policy_no TEXT PRIMARY KEY, customer_id INTEGER, product TEXT, premium REAL, status TEXT)"))
        conn.execute(text("DELETE FROM policies"))
        conn.execute(text("DELETE FROM customers"))

        conn.execute(text("INSERT INTO customers VALUES (:id, :name, :phone, :city)"), [
            {"id": 1, "name": "张三", "phone": "13800138000", "city": "北京市朝阳区"},
            {"id": 2, "name": "李四", "phone": "13900139999", "city": "青岛市市北区"},
            {"id": 3, "name": "王五", "phone": "13700137777", "city": "上海市浦东新区"},
        ])
        conn.execute(text("INSERT INTO policies VALUES (:pn, :cid, :prod, :prem, :st)"), [
            {"pn": "P20250405001", "cid": 1, "prod": "安心健康保", "prem": 3200.0, "st": "active"},
            {"pn": "P20250405002", "cid": 2, "prod": "终身寿险", "prem": 5200.0, "st": "active"},
            {"pn": "P20250405003", "cid": 1, "prod": "意外险", "prem": 880.0, "st": "expired"},
        ])

        families = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳")
        given_names = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "霞", "平", "刚", "桂英", "鑫", "雨桐", "梓涵", "浩然", "子轩", "一诺", "思远", "思琪"]
        cities = ["北京市海淀区", "广州市天河区", "深圳市南山区", "成都市武侯区", "杭州市西湖区", "南京市鼓楼区", "武汉市洪山区", "西安市雁塔区", "重庆市渝中区", "苏州市工业园区", "沈阳市和平区", "天津市河西区", "郑州市金水区", "长沙市岳麓区", "合肥市蜀山区"]
        products = ["安心健康保", "终身寿险", "意外险", "重疾险", "百万医疗险", "少儿平安险", "养老年金", "家财险"]
        statuses = ["active", "active", "active", "active", "expired", "pending"]

        cust_batch, pol_batch = [], []
        for i in range(4, 301):
            cust_batch.append({
                "id": i,
                "name": random.choice(families) + random.choice(given_names),
                "phone": f"1{random.choice(['3','5','7','8','9'])}{''.join(str(random.randint(0,9)) for _ in range(9))}",
                "city": random.choice(cities),
            })
            cid = i
            year, month, day = random.randint(2024, 2025), random.randint(1, 12), random.randint(1, 28)
            pol_batch.append({
                "pn": f"P{year}{month:02d}{day:02d}{random.randint(1000, 9999)}",
                "cid": cid, "prod": random.choice(products),
                "prem": round(random.uniform(500, 15000), 2),
                "st": random.choice(statuses),
            })
            if random.random() < 0.2:
                pol_batch.append({
                    "pn": f"P{year}{month:02d}{day:02d}{random.randint(1000, 9999)}",
                    "cid": cid, "prod": random.choice(products),
                    "prem": round(random.uniform(300, 8000), 2),
                    "st": random.choice(statuses),
                })
        conn.execute(text("INSERT INTO customers VALUES (:id, :name, :phone, :city)"), cust_batch)
        conn.execute(text("INSERT INTO policies VALUES (:pn, :cid, :prod, :prem, :st)"), pol_batch)


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
