# 在线商城系统(含积分体系)

> 基于 `demo/需求文档.md`(v1.0)实施的项目。当前进度:**M7 测试与收尾 ✅ 已完成**(M1 基础框架、M2 商品+购物车、M3 订单/支付/积分/评价、M4 评价列表+订单搜索、M5 数据看板+用户资料、M6 管理后台完善均已完成),按方案 C(分阶段停靠)推进,达到可交付状态。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + Vite + Vue Router + Axios + Pinia(端口 5174,代理 `/api` 到 8082) |
| 后端 | Spring Boot 3.2.5 + Maven + Java 21(端口 8082) |
| 数据库 | H2 文件库(`backend/data/mall.mv.db`),启动自动建表(`schema.sql`) |
| 鉴权 | 轻量 JWT(HS256,零额外依赖)+ BCrypt(`spring-security-crypto`) |

## 目录结构

```
demo/
├── 需求文档.md          # 需求规格(范围基线)
├── TSP会议记录.md       # TSP 会议纪要
├── backend/             # Spring Boot 后端
│   ├── pom.xml
│   ├── verify.sh        # 后端自动化验证脚本(101 项,含 M1-M7)
│   └── src/main/
│       ├── resources/application.yml
│       ├── resources/schema.sql       # 7 张核心表(一键建库,幂等)
│       └── java/com/example/mall/
│           ├── MallApplication.java
│           ├── config/    # WebConfig / GlobalExceptionHandler / DataInitializer / ForbiddenException
│           ├── controller/ # Auth / User / Product / AdminProduct / Cart / Order / AdminOrder / Point / AdminUser / AdminStats / Hello
│           ├── dto/        # 注册/登录/资料/密码/商品/购物车/下单/评价/调整积分等请求体
│           ├── entity/     # User / Product / CartItem / Order / OrderItem / Review / PointRecord
│           ├── repository/ # 各实体 JdbcTemplate 仓库 + StatsRepository(看板统计)
│           ├── security/   # JwtUtil / AuthInterceptor
│           └── service/    # User / Product / Cart / Order / Point
└── frontend/            # Vue3 前端
    ├── vite.config.js   # 端口 5174 + /api 代理
    ├── smoke_m3.sh      # M3 端到端冒烟脚本(走 5174 代理)
    └── src/
        ├── api/         # request.js(拦截器)/ auth / user / products / cart / order / admin
        ├── router/      # 路由 + 守卫(requiresAuth / requiresAdmin)
        ├── store/       # Pinia user store
        ├── views/       # Home / ProductDetail / Login / Register / Profile / Cart / OrderList / Points / AdminDashboard / AdminProducts / AdminOrders / AdminUsers
        └── App.vue      # 顶栏(积分显示、登录态、管理入口)
```

## 启动方式

### 1. 后端(端口 8082)

> 系统默认 JDK 是 8,必须用 Java 21 启动。

```bash
cd demo/backend
JAVA_HOME="C:\Users\25582\.jdks\ms-21.0.9" mvn spring-boot:run
```

首次启动会自动建表(H2 文件库,数据持久化到 `backend/data/`),并预置账号:

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | admin@mall.com | admin123456 |
| 普通用户 | demo@example.com | demo123456 |

种子数据含 10 个演示商品(1 个下架)。

### 2. 前端(端口 5174)

```bash
cd demo/frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5174 。

## 页面清单

| 页面 | 路由 | 权限 | 说明 |
| --- | --- | --- | --- |
| 首页 | / | 公开 | 商品列表:分类/关键词/排序筛选,卡片点击进详情 |
| 商品详情 | /product/:id | 公开 | 商品信息 + 用户评价列表 + 加入购物车 |
| 登录 / 注册 | /login /register | 游客 | JWT 登录 |
| 个人中心 | /profile | 登录 | 资料展示、编辑资料、修改密码、积分入口 |
| 购物车 | /cart | 登录 | 加购/改量/删除,结算弹窗(收货信息+积分抵扣) |
| 我的订单 | /orders | 登录 | 状态筛选 + 支付/取消/确认收货/评价/详情 |
| 积分明细 | /points | 登录 | 积分流水 |
| 数据看板 | /admin | ADMIN | 销售额/订单/用户/商品统计、热门商品 TOP5、最近订单 |
| 商品管理 | /admin/products | ADMIN | 商品 CRUD + 上下架 |
| 订单管理 | /admin/orders | ADMIN | 全部订单 + 发货 + 状态/关键字搜索 |
| 用户管理 | /admin/users | ADMIN | 用户列表 + 调整积分 |

## 后端接口(当前)

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | /api/hello | 冒烟接口 | 公开 |
| POST | /api/auth/register | 注册(返回 token) | 公开 |
| POST | /api/auth/login | 登录(返回 token) | 公开 |
| GET | /api/auth/me | 获取当前登录用户 | 需登录 |
| PUT | /api/users/profile | 修改昵称/手机号 | 需登录 |
| PUT | /api/users/password | 修改密码(校验原密码) | 需登录 |
| GET | /api/products | 商品列表(仅上架,支持 category/keyword/sort) | 公开 |
| GET | /api/products/categories | 分类列表 | 公开 |
| GET | /api/products/{id} | 商品详情(仅上架) | 公开 |
| GET | /api/products/{id}/reviews | 商品评价列表(JOIN 昵称) | 公开 |
| GET/POST/PUT/DELETE | /api/cart[/{id}] | 购物车(加购/列表/改数量/删项/清空) | 需登录 |
| POST | /api/orders | 从购物车创建订单(含积分抵扣) | 需登录 |
| GET | /api/orders | 我的订单列表(可 status 筛选) | 需登录 |
| GET | /api/orders/{id} | 订单详情(含明细) | 需登录(归属校验) |
| POST | /api/orders/{id}/pay | 支付(扣抵扣积分 + 返利) | 需登录 |
| POST | /api/orders/{id}/cancel | 取消(恢复库存) | 需登录 |
| POST | /api/orders/{id}/confirm | 确认收货 | 需登录 |
| POST | /api/orders/{id}/review | 评价(重算商品平均分) | 需登录 |
| GET | /api/points | 我的积分流水 | 需登录 |
| GET | /api/admin/stats | 数据看板统计(销售额/订单/用户/商品/热门/最近订单) | ADMIN |
| GET/POST/PUT/PUT | /api/admin/products[/{id}][/status] | 商品 CRUD + 上下架 | ADMIN |
| GET | /api/admin/orders | 全部订单(status/keyword 筛选:订单号/昵称/邮箱;startDate/endDate 日期筛选) | ADMIN |
| GET | /api/admin/orders/{id} | 订单详情(含明细 + 用户昵称/邮箱) | ADMIN |
| PUT | /api/admin/orders/{id}/ship | 发货 | ADMIN |
| GET | /api/admin/users | 用户列表 | ADMIN |
| PUT | /api/admin/users/{id}/points | 调整用户积分(正加负减,余额不可为负) | ADMIN |
| GET | /api/admin/users/{id}/points | 用户积分明细流水 | ADMIN |

> 鉴权方式:`Authorization: Bearer <token>`。JWT 有效期 12 小时,payload 含 `role`(USER/ADMIN)。

## 积分规则

- **抵扣**:10 积分 = 1 元,下单时选择,支付时扣减(不超过订单总额)。
- **返利**:支付成功后按实付金额每 1 元返 1 积分(向下取整)。
- 管理员可正负调整用户积分,余额不得为负;所有变动写入 `point_record` 流水。

## 订单状态机

```
PENDING_PAYMENT(待支付) ──支付──▶ PAID(待发货) ──发货(管理端)──▶ SHIPPED(待收货) ──确认收货──▶ COMPLETED(已完成)
        └────────── 取消 ──▶ CANCELLED(已取消,恢复库存)
```

评价仅在 COMPLETED 状态开放,每个订单明细只能评一次,评价后重算商品平均分。

## 自动化验证

后端启动后执行:

```bash
cd demo/backend && bash verify.sh
```

当前 **101 项全部通过**:鉴权/商品/购物车(M1+M2)、订单/支付/积分/评价/管理端发货与调分(M3)、公开评价列表与订单搜索(M4)、数据看板与资料/密码(M5)、订单详情/日期筛选/积分明细(M6)、越权/边界/安全(M7)全链路。

前端端到端冒烟(走 5174 代理,后端 8082 需已启动):

```bash
cd demo/frontend && bash smoke_m3.sh
```

## 已完成的里程碑

### M1 基础框架 ✅
- [x] 后端脚手架(Spring Boot 3.2.5 + Java 21 + H2)
- [x] 数据库初始化:7 张核心表(一键建库,幂等)
- [x] 注册/登录/退出/me 接口,JWT + BCrypt
- [x] 登录拦截器 + 种子账号(管理员 + 演示用户)
- [x] 前端脚手架 + 页面:首页/登录/注册/个人中心

### M2 商品 + 购物车 ✅
- [x] 商品列表(仅上架)/ 分类筛选 / 关键词搜索 / 排序(价格/销量/评分)
- [x] 管理端商品 CRUD + 上下架(ADMIN 鉴权)
- [x] 购物车:加购 / 列表 / 改数量 / 删项 / 清空,按用户隔离,库存与上架校验
- [x] 前端商品列表页 / 购物车页 / 管理端商品管理页
- [x] 种子数据 10 个演示商品(1 个下架)

### M3 订单 / 支付 / 积分 / 评价 ✅
- [x] 从购物车下单(事务:校验库存 → 生成订单+明细 → 扣库存加销量 → 清购物车)
- [x] 积分抵扣(10 积分=1 元,支付时扣减) + 支付返利(实付每 1 元返 1 积分)
- [x] 取消订单恢复库存;管理端发货;用户确认收货
- [x] 评价(仅已完成,每明细一次,重算商品平均分)
- [x] 积分流水(point_record:SPEND/GAIN/ADMIN)+ 管理端调整积分(余额不可为负)
- [x] 前端:结算弹窗(收货信息+积分抵扣)、我的订单页、积分明细页、管理端订单/用户页

### M4 评价列表 + 订单搜索 ✅
- [x] 公开评价列表接口 `GET /api/products/{id}/reviews`(JOIN 用户昵称,仅上架商品)
- [x] 管理端订单 keyword 搜索(订单号/昵称/邮箱模糊,可与 status 组合)
- [x] 前端商品详情页(评价列表)+ 首页卡片跳详情 + 管理端订单搜索框
- [x] verify.sh 扩至 69 项全过

### M5 数据看板 + 用户资料 ✅
- [x] 管理端数据看板:总销售额/订单/用户/商品/今日数据、热门商品 TOP5、最近订单
- [x] 用户修改资料(昵称/手机号)、修改密码(校验原密码)
- [x] 前端:管理端导航"数据看板"页 + 个人中心"账户设置"弹窗
- [x] verify.sh 扩至 79 项全过

### M6 管理后台完善 ✅
- [x] 管理端订单详情接口(含明细 + 用户昵称/邮箱,归属与存在性校验)
- [x] 管理端订单列表日期筛选(startDate/endDate,非法日期返回 400)
- [x] 管理端用户积分明细接口(按类型/时间倒序)
- [x] 前端管理端各页展示完善
- [x] verify.sh 扩至 88 项全过

### M7 测试与收尾 ✅
- [x] 越权防护:未登录/普通用户访问管理接口、他人订单详情/支付、操作他人购物车项均返回 401/403/400
- [x] 边界:空购物车下单、缺收货人、超库存改量、评分越界、未支付确认收货、非整数调分、非法日期等均正确拒绝
- [x] 数据一致性:关键字搜索匹配、价格排序正确
- [x] verify.sh 扩至 **101 项全过**,前端构建通过,5174 代理端到端冒烟通过(订单详情/积分明细/日期筛选/管理页)
- [x] README 更新至完整交付状态

### 后续可选扩展(超出本次需求基线)
历史订单统计报表、支付回调真实化、商品图片上传/CDN、分页优化、前端自动化(e2e)等。
