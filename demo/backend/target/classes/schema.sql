-- =====================================================================
-- 商城系统数据库初始化脚本(schema.sql)
-- 兼容 H2(MySQL 模式),建表幂等:CREATE TABLE IF NOT EXISTS
-- 对应需求文档第 6 章数据模型:7 张核心表
-- =====================================================================

-- 用户表
CREATE TABLE IF NOT EXISTS app_user (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL,
    password_hash VARCHAR(100) NOT NULL,
    nickname      VARCHAR(50),
    email         VARCHAR(100) NOT NULL UNIQUE,
    phone         VARCHAR(20),
    role          VARCHAR(10)  NOT NULL DEFAULT 'USER',   -- USER / ADMIN
    points        INT          NOT NULL DEFAULT 0,        -- 当前可用积分
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- 商品表
CREATE TABLE IF NOT EXISTS product (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100)   NOT NULL,
    category    VARCHAR(50),
    description VARCHAR(1000),
    image_url   VARCHAR(500),
    price       DECIMAL(10,2)  NOT NULL,
    stock       INT            NOT NULL DEFAULT 0 CHECK (stock >= 0),
    sales       INT            NOT NULL DEFAULT 0,
    avg_rating  DECIMAL(3,1),                              -- 平均评分,无评价时为 NULL
    status      VARCHAR(20)    NOT NULL DEFAULT 'ON_SALE', -- ON_SALE / OFF_SHELF
    created_at  TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- 购物车项
CREATE TABLE IF NOT EXISTS cart_item (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT      NOT NULL,
    product_id BIGINT      NOT NULL,
    quantity   INT         NOT NULL DEFAULT 1 CHECK (quantity > 0),
    created_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_item (user_id);

-- 订单表(order 为保留字,表名用 mall_order)
CREATE TABLE IF NOT EXISTS mall_order (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_no         VARCHAR(32)   NOT NULL UNIQUE,
    user_id          BIGINT        NOT NULL,
    total_amount     DECIMAL(10,2) NOT NULL,   -- 应付金额(商品小计)
    discount_points  INT           NOT NULL DEFAULT 0,   -- 使用积分数量
    discount_amount  DECIMAL(10,2) NOT NULL DEFAULT 0,   -- 积分抵扣金额
    actual_amount    DECIMAL(10,2) NOT NULL,             -- 实付金额
    status           VARCHAR(20)   NOT NULL DEFAULT 'PENDING_PAYMENT',
    receiver         VARCHAR(50),
    phone            VARCHAR(20),
    address          VARCHAR(200),
    created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    paid_at          TIMESTAMP,
    shipped_at       TIMESTAMP,
    completed_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_order_user ON mall_order (user_id);
CREATE INDEX IF NOT EXISTS idx_order_status ON mall_order (status);

-- 订单明细(商品名称/单价快照)
CREATE TABLE IF NOT EXISTS order_item (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id     BIGINT        NOT NULL,
    product_id   BIGINT        NOT NULL,
    product_name VARCHAR(100)  NOT NULL,   -- 下单时商品名称快照
    price        DECIMAL(10,2) NOT NULL,   -- 下单时单价快照
    quantity     INT           NOT NULL CHECK (quantity > 0),
    reviewed     BOOLEAN       NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_order_item_order ON order_item (order_id);

-- 评价表
CREATE TABLE IF NOT EXISTS review (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT       NOT NULL,
    order_id   BIGINT       NOT NULL,
    product_id BIGINT       NOT NULL,
    rating     INT          NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content    VARCHAR(500),
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_review_product ON review (product_id);

-- 积分流水表
CREATE TABLE IF NOT EXISTS point_record (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    BIGINT       NOT NULL,
    type       VARCHAR(10)  NOT NULL,   -- GAIN(获得)/SPEND(使用)/ADMIN(管理员调整)
    points     INT          NOT NULL,   -- 变动数量,正为获得、负为扣减
    balance    INT          NOT NULL,   -- 变动后余额快照
    order_id   BIGINT,                  -- 关联订单(可空)
    remark     VARCHAR(200),
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_point_user ON point_record (user_id);
