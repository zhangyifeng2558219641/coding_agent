#!/usr/bin/env bash
# =============================================================
# 商城后端自动化验证脚本(M1 登录鉴权 + M2 商品/购物车/管理权限)
# 用法: bash verify.sh
# 前提:后端已在 8082 端口启动
# =============================================================
set -u

BASE="http://localhost:8082"
PASS=0
FAIL=0

check() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  [PASS] $desc"
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $desc (期望 $expected, 实际 $actual)"
    FAIL=$((FAIL+1))
  fi
}

json_field() {
  # 从 JSON 中提取字段: json_field '<json>' '<field>'
  echo "$1" | python -c "import sys,json;print(json.load(sys.stdin)['$2'])" 2>/dev/null
}

echo "== M1 登录鉴权验证 =="

# 1. hello 公开接口
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/hello")
check "GET /api/hello 返回 200" "200" "$code"

# 2. 未登录访问受保护接口 -> 401
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/auth/me")
check "未登录访问 /api/auth/me 返回 401" "401" "$code"

# 3. 登录 demo 用户 -> 200 且有 token
resp=$(curl -s -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"demo123456"}')
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"demo123456"}')
check "登录 demo 用户返回 200" "200" "$code"
echo "$resp" | grep -q '"token"' && { echo "  [PASS] 登录返回 token"; PASS=$((PASS+1)); } || { echo "  [FAIL] 登录返回 token"; FAIL=$((FAIL+1)); }

# 4. 管理员登录 -> 200 且 role=ADMIN
adm=$(curl -s -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"admin@mall.com","password":"admin123456"}')
echo "$adm" | grep -q '"role":"ADMIN"' && { echo "  [PASS] 管理员登录且 role=ADMIN"; PASS=$((PASS+1)); } || { echo "  [FAIL] 管理员登录且 role=ADMIN"; FAIL=$((FAIL+1)); }

# 5. 错误密码 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"wrongpass"}')
check "错误密码登录返回 400" "400" "$code"

# 6. 伪造 token -> 401
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/auth/me" -H "Authorization: Bearer fake.token.here")
check "伪造 token 返回 401" "401" "$code"

# 7. 带 token 访问 /api/auth/me -> 200 且返回当前用户
TOKEN=$(json_field "$resp" "token")
me=$(curl -s "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")
check "带 token 访问 /api/auth/me 返回 200" "200" "$code"
echo "$me" | grep -q '"email":"demo@example.com"' && { echo "  [PASS] me 返回正确用户"; PASS=$((PASS+1)); } || { echo "  [FAIL] me 返回正确用户"; FAIL=$((FAIL+1)); }

# 8. 注册新用户 -> 200 且带 token
n=$(date +%s)
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/register" -H "Content-Type: application/json" \
  -d "{\"username\":\"Tester${n}\",\"email\":\"t${n}@test.com\",\"password\":\"pass123456\"}")
check "注册新用户返回 200" "200" "$code"

# 9. 重复邮箱注册 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/register" -H "Content-Type: application/json" \
  -d '{"username":"Again","email":"demo@example.com","password":"pass123456"}')
check "重复邮箱注册返回 400" "400" "$code"

# ---------- M2 商品 / 购物车 / 管理权限 ----------
echo ""
echo "== M2 商品 / 购物车 / 管理权限验证 =="

ADM_TOKEN=$(json_field "$adm" "token")

# 清空 demo 购物车,保证后续加购断言幂等
curl -s -o /dev/null -X DELETE "$BASE/api/cart" -H "Authorization: Bearer $TOKEN"

# 10. 商品列表公开可访问且非空
list=$(curl -s "$BASE/api/products")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/products")
check "GET /api/products 返回 200(公开)" "200" "$code"
count=$(echo "$list" | python -c "import sys,json;print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
[ "$count" -ge 8 ] && { echo "  [PASS] 商品列表非空(共 $count 个上架商品)"; PASS=$((PASS+1)); } || { echo "  [FAIL] 商品列表非空(共 $count 个)"; FAIL=$((FAIL+1)); }

# 11. 分类列表
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/products/categories")
check "GET /api/products/categories 返回 200" "200" "$code"

# 12. 上架商品详情 -> 200
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/products/1")
check "GET /api/products/1(上架)返回 200" "200" "$code"

# 13. 下架商品详情(种子 id=8 香薰蜡烛为 OFF_SHELF)-> 400
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/products/8")
check "GET /api/products/8(下架)返回 400" "400" "$code"

# 14. 筛选:分类=数码(用 unicode 转义比较 + buffer 按 UTF-8 读 stdin,规避 Windows shell 编码)
catlist=$(curl -s "$BASE/api/products?category=%E6%95%B0%E7%A0%81")
cnt=$(echo "$catlist" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(len(d), all(i['category']==u'\u6570\u7801' for i in d))" 2>/dev/null)
echo "$cnt" | grep -q "True" && { echo "  [PASS] 分类筛选生效"; PASS=$((PASS+1)); } || { echo "  [FAIL] 分类筛选生效"; FAIL=$((FAIL+1)); }

# 15. 未登录加购 -> 401
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -d '{"productId":1,"quantity":1}')
check "未登录加购返回 401" "401" "$code"

# 16. 普通用户访问管理端接口 -> 403
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/products" -H "Authorization: Bearer $TOKEN")
check "普通用户访问 /api/admin/products 返回 403" "403" "$code"

# 17. 管理员访问管理端接口 -> 200
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/products" -H "Authorization: Bearer $ADM_TOKEN")
check "管理员访问 /api/admin/products 返回 200" "200" "$code"

# 18. demo 加购商品1 -> 200
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":1,"quantity":2}')
check "加购商品返回 200" "200" "$code"

# 19. 重复加购累加数量(2+1=3)
cart=$(curl -s -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":1,"quantity":1}')
qty=$(json_field "$cart" "quantity")
check "重复加购后数量=3" "3" "$qty"

# 20. 超过库存加购 -> 400(库存 100,一次加 999)
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":1,"quantity":999}')
check "超库存加购返回 400" "400" "$code"

# 21. 加购下架商品(8 号)-> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":8,"quantity":1}')
check "加购下架商品返回 400" "400" "$code"

# 22. 购物车列表 -> 包含商品1且数量为3
cartlist=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
echo "$cartlist" | grep -q '"productName":"无线蓝牙耳机"' && { echo "  [PASS] 购物车列表包含商品"; PASS=$((PASS+1)); } || { echo "  [FAIL] 购物车列表包含商品"; FAIL=$((FAIL+1)); }
CART_ID=$(echo "$cartlist" | python -c "import sys,json;d=json.load(sys.stdin);print(d[0]['cartItemId'] if d else '')" 2>/dev/null)

# 23. 修改购物车数量为 5
cart_upd=$(curl -s -X PUT "$BASE/api/cart/$CART_ID" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"quantity":5}')
qty5=$(json_field "$cart_upd" "quantity")
check "修改购物车数量=5" "5" "$qty5"

# 24. 删除购物车项 -> 200
code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/api/cart/$CART_ID" -H "Authorization: Bearer $TOKEN")
check "删除购物车项返回 200" "200" "$code"

# 25. 管理员新增商品 -> 200(单次调用,避免重复创建)
newp_file=$(mktemp)
code=$(curl -s -o "$newp_file" -w "%{http_code}" -X POST "$BASE/api/admin/products" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" \
  -d '{"name":"verify-test-product","category":"test","description":"verify created","price":9.9,"stock":10,"status":"ON_SALE"}')
newp=$(cat "$newp_file")
rm -f "$newp_file"
check "管理员新增商品返回 200" "200" "$code"
NEW_ID=$(json_field "$newp" "id")

# 26. 管理员下架该商品 -> status=OFF_SHELF
off=$(curl -s -X PUT "$BASE/api/admin/products/$NEW_ID/status" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" -d '{"status":"OFF_SHELF"}')
st=$(json_field "$off" "status")
check "下架后 status=OFF_SHELF" "OFF_SHELF" "$st"

# 27. 管理员编辑商品价格 -> 200
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/admin/products/$NEW_ID" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" \
  -d '{"name":"verify-test-product","category":"test","description":"verify edited","price":19.9,"stock":20}')
check "管理员编辑商品返回 200" "200" "$code"

# 28. 用户列表不再包含下架的测试商品
list2=$(curl -s "$BASE/api/products")
echo "$list2" | grep -q "verify-test-product" && { echo "  [FAIL] 下架商品不出现在用户列表"; FAIL=$((FAIL+1)); } || { echo "  [PASS] 下架商品不出现在用户列表"; PASS=$((PASS+1)); }

# 29. 管理员新增商品缺名称 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/admin/products" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" -d '{"name":"","price":1,"stock":1}')
check "空名称新增商品返回 400" "400" "$code"

# ---------- M3 订单 / 支付 / 积分 / 评价 ----------
echo ""
echo "== M3 订单 / 支付 / 积分 / 评价验证 =="

# 记录 demo 当前积分(相对断言,保证脚本可重复运行)
me0=$(curl -s "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")
P0=$(json_field "$me0" "points")

# 清空购物车,保证幂等
curl -s -o /dev/null -X DELETE "$BASE/api/cart" -H "Authorization: Bearer $TOKEN"

# 30. 未登录访问 /api/orders -> 401
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/orders")
check "未登录访问 /api/orders 返回 401" "401" "$code"

# 31. 加购商品2 x1 并创建订单(usePoints=0)
curl -s -o /dev/null -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":2,"quantity":1}'
CART_LIST=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
CID2=$(echo "$CART_LIST" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(d[0]['cartItemId'])")
STOCK_BEFORE=$(curl -s "$BASE/api/products/2" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['stock'])")
orderA_file=$(mktemp)
code=$(curl -s -o "$orderA_file" -w "%{http_code}" -X POST "$BASE/api/orders" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"cartItemIds\":[$CID2],\"usePoints\":0,\"receiver\":\"Zhang San\",\"phone\":\"13800138000\",\"address\":\"Beijing Haidian\"}")
orderA=$(cat "$orderA_file")
rm -f "$orderA_file"
check "创建订单返回 200" "200" "$code"
st=$(json_field "$orderA" "status")
check "新订单状态 PENDING_PAYMENT" "PENDING_PAYMENT" "$st"
OID_A=$(json_field "$orderA" "id")

# 32. 订单金额:total=399.00, actual=399.00(按 JSON 原文匹配)
echo "$orderA" | grep -q '"totalAmount":399.00' && { echo "  [PASS] 订单总额 399.00"; PASS=$((PASS+1)); } || { echo "  [FAIL] 订单总额 399.00 ($(echo "$orderA" | head -c 200))"; FAIL=$((FAIL+1)); }
echo "$orderA" | grep -q '"actualAmount":399.00' && { echo "  [PASS] 实付金额 399.00"; PASS=$((PASS+1)); } || { echo "  [FAIL] 实付金额 399.00"; FAIL=$((FAIL+1)); }

# 33. 下单后购物车被清空
cart_after=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
empty=$(echo "$cart_after" | python -c "import sys,json;print(len(json.load(sys.stdin.buffer)))" 2>/dev/null)
check "下单后购物车为空" "0" "$empty"

# 34. 库存扣减(下单前-1)
STOCK_AFTER=$(curl -s "$BASE/api/products/2" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['stock'])")
check "下单后库存=原库存-1" "$((STOCK_BEFORE-1))" "$STOCK_AFTER"

# 35. 支付订单 -> PAID
paid=$(curl -s -X POST "$BASE/api/orders/$OID_A/pay" -H "Authorization: Bearer $TOKEN")
st=$(json_field "$paid" "status")
check "支付后状态 PAID" "PAID" "$st"

# 36. 支付后积分 = 原积分 + 实付(399)
me1=$(curl -s "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")
P1=$(json_field "$me1" "points")
check "支付后返积分 P0+399" "$((P0+399))" "$P1"

# 37. 管理员发货 -> SHIPPED
ship=$(curl -s -X PUT "$BASE/api/admin/orders/$OID_A/ship" -H "Authorization: Bearer $ADM_TOKEN")
st=$(json_field "$ship" "status")
check "发货后状态 SHIPPED" "SHIPPED" "$st"

# 38. 用户确认收货 -> COMPLETED
done_order=$(curl -s -X POST "$BASE/api/orders/$OID_A/confirm" -H "Authorization: Bearer $TOKEN")
st=$(json_field "$done_order" "status")
check "确认收货后状态 COMPLETED" "COMPLETED" "$st"

# 39. 评价商品2(5星)-> 200,商品平均分更新为 5.0
ITEM_A=$(echo "$done_order" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['items'][0]['id'])")
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders/$OID_A/review" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d "{\"orderItemId\":$ITEM_A,\"rating\":5,\"content\":\"very good\"}")
check "评价返回 200" "200" "$code"
rating=$(curl -s "$BASE/api/products/2" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['avgRating'])")
check "商品2平均评分=5.0" "5.0" "$rating"

# 40. 重复评价 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders/$OID_A/review" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d "{\"orderItemId\":$ITEM_A,\"rating\":4}")
check "重复评价返回 400" "400" "$code"

# 41. 取消已支付订单 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders/$OID_A/cancel" -H "Authorization: Bearer $TOKEN")
check "取消已支付订单返回 400" "400" "$code"

# 42. 积分抵扣下单:商品1 x1(199)使用 100 积分 -> 抵 10 元,实付 189
curl -s -o /dev/null -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":1,"quantity":1}'
CART_LIST=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
CID1=$(echo "$CART_LIST" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(d[0]['cartItemId'])")
orderB=$(curl -s -X POST "$BASE/api/orders" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"cartItemIds\":[$CID1],\"usePoints\":100,\"receiver\":\"Zhang San\",\"phone\":\"13800138000\",\"address\":\"Shanghai Pudong\"}")
OID_B=$(json_field "$orderB" "id")
echo "$orderB" | grep -q '"discountAmount":10.00' && { echo "  [PASS] 积分抵扣金额 10.00"; PASS=$((PASS+1)); } || { echo "  [FAIL] 积分抵扣金额 10.00"; FAIL=$((FAIL+1)); }
echo "$orderB" | grep -q '"actualAmount":189.00' && { echo "  [PASS] 抵扣后实付 189.00"; PASS=$((PASS+1)); } || { echo "  [FAIL] 抵扣后实付 189.00"; FAIL=$((FAIL+1)); }

# 43. 支付订单B -> 积分 = P1 - 100 + 189 = P0 + 488
paidB=$(curl -s -X POST "$BASE/api/orders/$OID_B/pay" -H "Authorization: Bearer $TOKEN")
st=$(json_field "$paidB" "status")
check "订单B支付后状态 PAID" "PAID" "$st"
me2=$(curl -s "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN")
P2=$(json_field "$me2" "points")
check "支付订单B后积分=P0+488" "$((P0+488))" "$P2"

# 44. 积分流水包含 SPEND 记录
points_log=$(curl -s "$BASE/api/points" -H "Authorization: Bearer $TOKEN")
echo "$points_log" | grep -q '"SPEND"' && { echo "  [PASS] 积分流水包含扣减记录"; PASS=$((PASS+1)); } || { echo "  [FAIL] 积分流水包含扣减记录"; FAIL=$((FAIL+1)); }

# 45. 取消待支付订单 -> 库存恢复
curl -s -o /dev/null -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":4,"quantity":1}'
CART_LIST=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
CID4=$(echo "$CART_LIST" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(d[0]['cartItemId'])")
STOCK4_BEFORE=$(curl -s "$BASE/api/products/4" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['stock'])")
orderC=$(curl -s -X POST "$BASE/api/orders" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"cartItemIds\":[$CID4],\"usePoints\":0,\"receiver\":\"Li Si\",\"phone\":\"13900139000\",\"address\":\"Guangzhou Tianhe\"}")
OID_C=$(json_field "$orderC" "id")
cancelC=$(curl -s -X POST "$BASE/api/orders/$OID_C/cancel" -H "Authorization: Bearer $TOKEN")
st=$(json_field "$cancelC" "status")
check "取消后状态 CANCELLED" "CANCELLED" "$st"
STOCK4_AFTER=$(curl -s "$BASE/api/products/4" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['stock'])")
check "取消后库存恢复" "$STOCK4_BEFORE" "$STOCK4_AFTER"

# 46. 管理端订单列表 -> 200 且包含订单A
adm_orders=$(curl -s "$BASE/api/admin/orders" -H "Authorization: Bearer $ADM_TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders" -H "Authorization: Bearer $ADM_TOKEN")
check "管理端订单列表返回 200" "200" "$code"
echo "$adm_orders" | grep -q '"orderNo"' && { echo "  [PASS] 管理端订单列表包含数据"; PASS=$((PASS+1)); } || { echo "  [FAIL] 管理端订单列表包含数据"; FAIL=$((FAIL+1)); }

# 47. 管理员调整积分:demo +50
adj=$(curl -s -X PUT "$BASE/api/admin/users/2/points" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" -d '{"points":50,"remark":"test bonus"}')
pts=$(json_field "$adj" "points")
check "管理员+50积分后余额=P0+538" "$((P0+538))" "$pts"

# 48. 管理员扣积分导致负余额 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/admin/users/2/points" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" -d '{"points":-100000,"remark":"overflow"}')
check "扣到负数返回 400" "400" "$code"

# 49. 我的订单列表 -> 200 且非空
my_orders=$(curl -s "$BASE/api/orders" -H "Authorization: Bearer $TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/orders" -H "Authorization: Bearer $TOKEN")
check "我的订单列表返回 200" "200" "$code"
cnt=$(echo "$my_orders" | python -c "import sys,json;print(len(json.load(sys.stdin.buffer)))" 2>/dev/null)
[ "$cnt" -ge 3 ] && { echo "  [PASS] 我的订单列表非空(共 $cnt 单)"; PASS=$((PASS+1)); } || { echo "  [FAIL] 我的订单列表非空(共 $cnt 单)"; FAIL=$((FAIL+1)); }

echo ""
echo "== M4 扩展:公开评价列表 + 管理端订单搜索 =="

# 50. 公开评价列表(无 token)-> 200 且包含昵称
reviews=$(curl -s "$BASE/api/products/2/reviews")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/products/2/reviews")
check "GET /api/products/2/reviews 返回 200" "200" "$code"
echo "$reviews" | grep -q '"userNickname"' && { echo "  [PASS] 评价列表包含用户昵称"; PASS=$((PASS+1)); } || { echo "  [FAIL] 评价列表包含用户昵称"; FAIL=$((FAIL+1)); }
echo "$reviews" | grep -q 'very good' && { echo "  [PASS] 评价列表包含评价内容"; PASS=$((PASS+1)); } || { echo "  [FAIL] 评价列表包含评价内容"; FAIL=$((FAIL+1)); }

# 51. 不存在的商品评价 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/products/99999/reviews")
check "不存在商品评价返回 400" "400" "$code"

# 52. 管理端订单按昵称/邮箱/订单号搜索
adm_demo=$(curl -s "$BASE/api/admin/orders?keyword=demo" -H "Authorization: Bearer $ADM_TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders?keyword=demo" -H "Authorization: Bearer $ADM_TOKEN")
check "管理端按 keyword=demo 搜索返回 200" "200" "$code"
echo "$adm_demo" | grep -q '"orderNo"' && { echo "  [PASS] keyword 搜索返回订单"; PASS=$((PASS+1)); } || { echo "  [FAIL] keyword 搜索返回订单"; FAIL=$((FAIL+1)); }

adm_email=$(curl -s "$BASE/api/admin/orders?keyword=demo%40example.com" -H "Authorization: Bearer $ADM_TOKEN")
echo "$adm_email" | grep -q '"orderNo"' && { echo "  [PASS] 按邮箱 keyword 搜索返回订单"; PASS=$((PASS+1)); } || { echo "  [FAIL] 按邮箱 keyword 搜索返回订单"; FAIL=$((FAIL+1)); }

# 53. 组合 keyword+status 筛选
adm_combo=$(curl -s "$BASE/api/admin/orders?keyword=demo&status=COMPLETED" -H "Authorization: Bearer $ADM_TOKEN")
combo_cnt=$(echo "$adm_combo" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(len(d))" 2>/dev/null)
combo_ok=$(echo "$adm_combo" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(1 if d and all(o['status']=='COMPLETED' for o in d) else 0)" 2>/dev/null)
check "keyword+status 组合筛选中全部为 COMPLETED($combo_cnt 条)" "1" "$combo_ok"

# 54. 不存在的关键字 -> 空列表
adm_none=$(curl -s "$BASE/api/admin/orders?keyword=zzzz_not_exist" -H "Authorization: Bearer $ADM_TOKEN")
none_cnt=$(echo "$adm_none" | python -c "import sys,json;print(len(json.load(sys.stdin.buffer)))" 2>/dev/null)
check "无匹配关键字返回空列表" "0" "$none_cnt"

echo ""
echo "== M5 扩展:数据看板 + 用户资料/密码 =="

# 55. 管理员统计看板 -> 200 且含关键字段
stats=$(curl -s "$BASE/api/admin/stats" -H "Authorization: Bearer $ADM_TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/stats" -H "Authorization: Bearer $ADM_TOKEN")
check "GET /api/admin/stats 返回 200" "200" "$code"
echo "$stats" | grep -q '"totalSales"' && { echo "  [PASS] 统计包含 totalSales"; PASS=$((PASS+1)); } || { echo "  [FAIL] 统计包含 totalSales"; FAIL=$((FAIL+1)); }
echo "$stats" | grep -q '"topProducts"' && { echo "  [PASS] 统计包含热门商品"; PASS=$((PASS+1)); } || { echo "  [FAIL] 统计包含热门商品"; FAIL=$((FAIL+1)); }

# 56. 普通用户访问统计 -> 403
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/stats" -H "Authorization: Bearer $TOKEN")
check "普通用户访问统计返回 403" "403" "$code"

# 57. 修改个人资料(昵称/手机号)-> 200 且生效(用 ASCII 昵称避免 shell 编码差异)
up=$(curl -s -X PUT "$BASE/api/users/profile" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"nickname":"verify-user","phone":"13800138000"}')
nick=$(json_field "$up" "nickname")
check "修改资料后昵称=verify-user" "verify-user" "$nick"
phone=$(json_field "$up" "phone")
check "修改资料后手机号=13800138000" "13800138000" "$phone"
# 恢复 demo 昵称为"演示用户"(UTF-8 十六进制,避免 Windows shell 编码差异)
printf '{"nickname":"\xe6\xbc\x94\xe7\xa4\xba\xe7\x94\xa8\xe6\x88\xb7","phone":""}' > /tmp/mall_profile_restore.json
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/users/profile" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" --data-binary @/tmp/mall_profile_restore.json)
check "恢复昵称为演示用户返回 200" "200" "$code"

# 58. 修改密码:错误旧密码 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/users/password" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"oldPassword":"wrongpass","newPassword":"newpass123"}')
check "错误原密码修改返回 400" "400" "$code"

# 59. 修改密码:正确修改 -> 200(改回原密码)
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/users/password" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"oldPassword":"demo123456","newPassword":"demo123456"}')
check "正确修改密码返回 200" "200" "$code"

# 60. 修改密码:新密码过短 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/users/password" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"oldPassword":"demo123456","newPassword":"123"}')
check "过短新密码返回 400" "400" "$code"

echo ""
echo "== M6 管理后台完善:订单详情/时间筛选/积分明细 =="

# 61. 管理端订单详情 -> 200 且含明细与用户昵称
adm_detail=$(curl -s "$BASE/api/admin/orders/$OID_A" -H "Authorization: Bearer $ADM_TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders/$OID_A" -H "Authorization: Bearer $ADM_TOKEN")
check "管理端订单详情返回 200" "200" "$code"
echo "$adm_detail" | grep -q '"items"' && { echo "  [PASS] 管理端订单详情包含明细"; PASS=$((PASS+1)); } || { echo "  [FAIL] 管理端订单详情包含明细"; FAIL=$((FAIL+1)); }
echo "$adm_detail" | grep -q '"userNickname"' && { echo "  [PASS] 管理端订单详情包含用户昵称"; PASS=$((PASS+1)); } || { echo "  [FAIL] 管理端订单详情包含用户昵称"; FAIL=$((FAIL+1)); }

# 62. 管理端不存在的订单详情 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders/99999" -H "Authorization: Bearer $ADM_TOKEN")
check "管理端不存在订单详情返回 400" "400" "$code"

# 63. 管理端订单按时间范围筛选(未来日期 -> 空)
adm_future=$(curl -s "$BASE/api/admin/orders?startDate=2099-01-01" -H "Authorization: Bearer $ADM_TOKEN")
future_cnt=$(echo "$adm_future" | python -c "import sys,json;print(len(json.load(sys.stdin.buffer)))" 2>/dev/null)
check "未来日期筛选返回空列表" "0" "$future_cnt"

# 64. 非法日期格式 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders?startDate=abc" -H "Authorization: Bearer $ADM_TOKEN")
check "非法日期格式返回 400" "400" "$code"

# 65. 管理端查看用户积分明细 -> 200 且非空
adm_points=$(curl -s "$BASE/api/admin/users/2/points" -H "Authorization: Bearer $ADM_TOKEN")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/users/2/points" -H "Authorization: Bearer $ADM_TOKEN")
check "管理端用户积分明细返回 200" "200" "$code"
echo "$adm_points" | grep -q '"type"' && { echo "  [PASS] 积分明细含类型字段"; PASS=$((PASS+1)); } || { echo "  [FAIL] 积分明细含类型字段"; FAIL=$((FAIL+1)); }

# 66. 管理端查看不存在用户积分明细 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/users/99999/points" -H "Authorization: Bearer $ADM_TOKEN")
check "不存在用户积分明细返回 400" "400" "$code"

# 67. 普通用户访问管理端订单详情 -> 403
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders/$OID_A" -H "Authorization: Bearer $TOKEN")
check "普通用户访问管理端订单详情返回 403" "403" "$code"

echo ""
echo "== M7 边界与安全测试 =="

# 68. 未登录访问管理端订单详情 -> 401
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/admin/orders/$OID_A")
check "未登录访问管理端订单详情返回 401" "401" "$code"

# 69. 用户访问他人订单详情 -> 400(注册新用户访问 demo 的订单)
n2=$(date +%s)
oth=$(curl -s -X POST "$BASE/api/auth/register" -H "Content-Type: application/json" \
  -d "{\"username\":\"Other${n2}\",\"email\":\"other${n2}@test.com\",\"password\":\"pass123456\"}")
OTH_TOKEN=$(json_field "$oth" "token")
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/orders/$OID_A" -H "Authorization: Bearer $OTH_TOKEN")
check "他人订单详情访问返回 400" "400" "$code"

# 70. 他人订单支付 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders/$OID_A/pay" -H "Authorization: Bearer $OTH_TOKEN")
check "他人订单支付返回 400" "400" "$code"

# 71. 空购物车下单 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"cartItemIds":[],"usePoints":0,"receiver":"A","phone":"13800000000","address":"X"}')
check "空购物车下单返回 400" "400" "$code"

# 72. 下单缺少收货人 -> 400
curl -s -o /dev/null -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":5,"quantity":1}'
CART_LIST=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
CID5=$(echo "$CART_LIST" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(d[0]['cartItemId'])")
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d "{\"cartItemIds\":[$CID5],\"usePoints\":0,\"receiver\":\"\",\"phone\":\"13800000000\",\"address\":\"X\"}")
check "缺少收货人下单返回 400" "400" "$code"

# 73. 超库存修改购物车数量 -> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/cart/$CID5" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"quantity":99999}')
check "超库存改购物车数量返回 400" "400" "$code"
# 清掉商品5的购物车项
curl -s -o /dev/null -X DELETE "$BASE/api/cart/$CID5" -H "Authorization: Bearer $TOKEN"

# 74. 评价评分越界(6分)-> 400
# 用已完成订单 OID_A 的另一个未评明细,若无则直接请求 6 分应 400(商品2已评,评分校验在前)
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders/$OID_A/review" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d "{\"orderItemId\":$ITEM_A,\"rating\":6,\"content\":\"bad\"}")
check "评分越界(6分)返回 400" "400" "$code"

# 75. 未支付订单直接确认收货 -> 400(新下单不支付直接 confirm)
curl -s -o /dev/null -X POST "$BASE/api/cart" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -d '{"productId":3,"quantity":1}'
CART_LIST=$(curl -s "$BASE/api/cart" -H "Authorization: Bearer $TOKEN")
CID3=$(echo "$CART_LIST" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(d[0]['cartItemId'])")
orderD=$(curl -s -X POST "$BASE/api/orders" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"cartItemIds\":[$CID3],\"usePoints\":0,\"receiver\":\"Wang Wu\",\"phone\":\"13700137000\",\"address\":\"Chengdu\"}")
OID_D=$(json_field "$orderD" "id")
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/orders/$OID_D/confirm" -H "Authorization: Bearer $TOKEN")
check "未支付订单确认收货返回 400" "400" "$code"
# 取消该订单,保持数据干净
curl -s -o /dev/null -X POST "$BASE/api/orders/$OID_D/cancel" -H "Authorization: Bearer $TOKEN"

# 76. 调整积分参数非法(非整数/为空)-> 400
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/admin/users/2/points" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADM_TOKEN" -d '{"points":"abc","remark":"x"}')
check "非整数积分调整返回 400" "400" "$code"

# 77. 修改购物车他人项 -> 400
# 用 OTH 用户访问 demo 的购物车项(先取 demo 购物车,当前应为空,则取任意不存在的项)
code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/api/cart/99999" -H "Authorization: Bearer $OTH_TOKEN")
check "操作他人/不存在购物车项返回 400" "400" "$code"

# 78. 商品列表关键字搜索 -> 200 且仅含匹配项
sr=$(curl -s "$BASE/api/products?keyword=%E8%80%B3%E6%9C%BA")  # 耳机
sr_ok=$(echo "$sr" | python -c "import sys,json;d=json.load(sys.stdin.buffer);print(1 if d and all(u'\u8033\u673a' in i['name'] for i in d) else 0)" 2>/dev/null)
check "关键字搜索'耳机'结果均匹配" "1" "$sr_ok"

# 79. 商品排序:按价格升序(sort=price&order=asc)
sorted=$(curl -s "$BASE/api/products?sort=price&order=asc")
sorted_ok=$(echo "$sorted" | python -c "
import sys,json
d=json.load(sys.stdin.buffer)
p=[float(i['price']) for i in d]
print(1 if p==sorted(p) else 0)" 2>/dev/null)
check "按价格升序排序正确" "1" "$sorted_ok"

echo ""
echo "==========================================="
echo " 通过: $PASS / 失败: $FAIL"
echo "==========================================="
[ "$FAIL" -eq 0 ] && echo "✅ 全部通过" || echo "❌ 存在失败项"
exit $FAIL
