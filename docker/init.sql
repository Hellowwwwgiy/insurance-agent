-- Insurance Agent 生产种子数据（PostgreSQL 版）
-- 与 tests/conftest.py 的 SQLite fixture 保持一致
CREATE TABLE IF NOT EXISTS customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT,
    address     TEXT,
    age         INTEGER
);

CREATE TABLE IF NOT EXISTS policies (
    id          SERIAL PRIMARY KEY,
    policy_no   TEXT UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product     TEXT,
    premium     REAL,
    insured_amount REAL,
    status      TEXT DEFAULT 'active',
    start_date  DATE,
    end_date    DATE
);

-- 种子客户
INSERT INTO customers (name, phone, address, age) VALUES
    ('张三', '13800138000', '北京市朝阳区', 32),
    ('李四', '13900139999', '上海市浦东新区', 28),
    ('王五', '13700137000', '广州市天河区', 45)
ON CONFLICT DO NOTHING;

-- 种子保单
INSERT INTO policies (policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date) VALUES
    ('P20250405001', 1, '安心健康保', 3200.00, 500000.00, 'active', '2025-04-05', '2045-04-04'),
    ('P20250405002', 1, '终身寿险', 3000.00, 800000.00, 'active', '2024-01-15', '2074-01-14'),
    ('P20250405003', 3, '综合意外险', 1800.00, 300000.00, 'expired', '2023-06-01', '2024-05-31')
ON CONFLICT DO NOTHING;

-- 扩产（100x 级别）：自动追加 297 客户 + 350 保单
DO $$
DECLARE
    i INTEGER;
    p INTEGER;
    customer_id INTEGER;
    seed_names TEXT[] := ARRAY['陈', '杨', '赵', '黄', '周', '吴', '徐', '孙', '马', '朱', '胡', '郭', '何', '高', '林'];
    cities TEXT[] := ARRAY['北京', '上海', '广州', '深圳', '杭州', '成都', '南京', '武汉', '重庆', '西安', '苏州', '天津', '长沙', '青岛', '郑州'];
    products TEXT[] := ARRAY['安心健康保', '终身寿险', '综合意外险', '重疾无忧', '齿科医疗险'];
    statuses TEXT[] := ARRAY['active', 'active', 'active', 'expired', 'pending'];
BEGIN
    -- 297 客户
    FOR i IN 4..300 LOOP
        INSERT INTO customers (name, phone, address, age)
        VALUES (
            seed_names[1 + (i % 15)] || '客户' || LPAD(i::text, 3, '0'),
            '13' || LPAD((80000000 + i * 137) % 100000000::text, 8, '0'),
            cities[1 + (i % 15)] || '市某区',
            22 + (i % 50)
        );
    END LOOP;

    -- 350 保单（20% 客户有 2 份）
    FOR p IN 1..350 LOOP
        customer_id := 1 + (p % 300);
        INSERT INTO policies (policy_no, customer_id, product, premium, insured_amount, status, start_date, end_date)
        VALUES (
            'P2025' || LPAD(p::text, 6, '0'),
            customer_id,
            products[1 + (p % 5)],
            1000 + (p * 17) % 9000,
            100000 + (p * 31) % 900000,
            statuses[1 + (p % 5)],
            DATE '2020-01-01' + ((p * 7) % 1800),
            DATE '2020-01-01' + ((p * 7) % 1800) + 365 * (10 + (p % 30))
        );
    END LOOP;
END $$;
