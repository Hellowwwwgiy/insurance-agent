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

-- 理赔记录
CREATE TABLE IF NOT EXISTS claims (
    id              SERIAL PRIMARY KEY,
    claim_no        TEXT UNIQUE NOT NULL,
    policy_id       INTEGER NOT NULL REFERENCES policies(id),
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    claim_date      DATE,
    claim_type      TEXT,           -- 住院/手术/门诊/意外/重疾
    claim_amount    REAL,           -- 申请金额
    approved_amount REAL,           -- 核准金额
    status          TEXT DEFAULT 'pending',  -- pending/approved/rejected/paid
    description     TEXT
);

-- 核保记录
CREATE TABLE IF NOT EXISTS underwriting (
    id               SERIAL PRIMARY KEY,
    policy_id        INTEGER NOT NULL REFERENCES policies(id),
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    underwrite_date  DATE,
    health_score     INTEGER,        -- 健康评分 0-100
    risk_level       TEXT,           -- low/medium/high
    decision         TEXT,           -- approved/rejected/postponed/extra_premium
    extra_premium_rate REAL,         -- 加费比例
    notes            TEXT
);

-- 续保记录
CREATE TABLE IF NOT EXISTS renewal (
    id                SERIAL PRIMARY KEY,
    policy_id         INTEGER NOT NULL REFERENCES policies(id),
    customer_id       INTEGER NOT NULL REFERENCES customers(id),
    renewal_date      DATE,
    previous_end_date DATE,
    new_end_date      DATE,
    premium           REAL,
    status            TEXT DEFAULT 'pending',  -- pending/confirmed/lapsed
    discount_rate     REAL                     -- 续保折扣率
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

-- 种子理赔记录
INSERT INTO claims (claim_no, policy_id, customer_id, claim_date, claim_type, claim_amount, approved_amount, status, description) VALUES
    ('C202501001', 1, 1, '2025-06-10', '住院', 28000.00, 24500.00, 'paid', '急性阑尾炎住院手术'),
    ('C202501002', 1, 1, '2025-09-15', '门诊', 3200.00, 2800.00, 'paid', '常规体检门诊复查'),
    ('C202501003', 3, 3, '2024-03-20', '意外', 15000.00, 12000.00, 'paid', '交通事故意外医疗')
ON CONFLICT DO NOTHING;

-- 种子核保记录
INSERT INTO underwriting (policy_id, customer_id, underwrite_date, health_score, risk_level, decision, extra_premium_rate, notes) VALUES
    (1, 1, '2025-04-01', 85, 'low', 'approved', 0.0, '体检正常，标准承保'),
    (2, 1, '2024-01-10', 78, 'medium', 'extra_premium', 0.15, '轻度脂肪肝，加费 15%'),
    (3, 3, '2023-05-28', 92, 'low', 'approved', 0.0, '健康状况良好')
ON CONFLICT DO NOTHING;

-- 种子续保记录
INSERT INTO renewal (policy_id, customer_id, renewal_date, previous_end_date, new_end_date, premium, status, discount_rate) VALUES
    (2, 1, '2024-01-10', '2024-01-14', '2075-01-14', 3000.00, 'confirmed', 0.0),
    (3, 3, '2024-05-20', '2024-05-31', NULL, 1800.00, 'lapsed', NULL)
ON CONFLICT DO NOTHING;

-- 扩产（100x 级别）：自动追加 297 客户 + 350 保单 + 理赔/核保/续保
DO $$
DECLARE
    i INTEGER;
    p INTEGER;
    customer_id INTEGER;
    seed_names TEXT[] := ARRAY['陈', '杨', '赵', '黄', '周', '吴', '徐', '孙', '马', '朱', '胡', '郭', '何', '高', '林'];
    cities TEXT[] := ARRAY['北京', '上海', '广州', '深圳', '杭州', '成都', '南京', '武汉', '重庆', '西安', '苏州', '天津', '长沙', '青岛', '郑州'];
    products TEXT[] := ARRAY['安心健康保', '终身寿险', '综合意外险', '重疾无忧', '齿科医疗险'];
    statuses TEXT[] := ARRAY['active', 'active', 'active', 'expired', 'pending'];
    claim_types TEXT[] := ARRAY['住院', '手术', '门诊', '意外', '重疾'];
    claim_statuses TEXT[] := ARRAY['pending', 'approved', 'rejected', 'paid', 'paid'];
    risk_levels TEXT[] := ARRAY['low', 'low', 'low', 'medium', 'high'];
    uw_decisions TEXT[] := ARRAY['approved', 'approved', 'approved', 'rejected', 'extra_premium'];
    renewal_statuses TEXT[] := ARRAY['confirmed', 'confirmed', 'lapsed', 'pending'];
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

        -- 每个保单 1 条核保记录
        INSERT INTO underwriting (policy_id, customer_id, underwrite_date, health_score, risk_level, decision, extra_premium_rate, notes)
        VALUES (
            3 + p,
            customer_id,
            DATE '2020-01-01' + ((p * 7) % 1800) - 5,
            60 + (p * 3) % 40,
            risk_levels[1 + (p % 5)],
            uw_decisions[1 + (p % 5)],
            CASE WHEN uw_decisions[1 + (p % 5)] = 'extra_premium' THEN 0.1 + (p % 5) * 0.05 ELSE 0.0 END,
            '自动生成核保记录'
        );

        -- 30% 保单有理赔记录
        IF p % 3 = 0 THEN
            INSERT INTO claims (claim_no, policy_id, customer_id, claim_date, claim_type, claim_amount, approved_amount, status, description)
            VALUES (
                'C' || LPAD(p::text, 8, '0'),
                3 + p,
                customer_id,
                DATE '2020-01-01' + ((p * 7) % 1800) + 60,
                claim_types[1 + (p % 5)],
                5000 + (p * 13) % 95000,
                4000 + (p * 11) % 80000,
                claim_statuses[1 + (p % 5)],
                '自动生成理赔记录'
            );
        END IF;

        -- expired 保单生成续保记录
        IF statuses[1 + (p % 5)] = 'expired' THEN
            INSERT INTO renewal (policy_id, customer_id, renewal_date, previous_end_date, new_end_date, premium, status, discount_rate)
            VALUES (
                3 + p,
                customer_id,
                DATE '2020-01-01' + ((p * 7) % 1800) + 365 * (10 + (p % 30)) - 30,
                DATE '2020-01-01' + ((p * 7) % 1800) + 365 * (10 + (p % 30)),
                NULL,
                1000 + (p * 17) % 9000,
                renewal_statuses[1 + (p % 4)],
                CASE WHEN renewal_statuses[1 + (p % 4)] = 'confirmed' THEN 0.05 ELSE NULL END
            );
        END IF;
    END LOOP;
END $$;
