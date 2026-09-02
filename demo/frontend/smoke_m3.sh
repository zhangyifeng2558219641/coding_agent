#!/bin/sh
# M3 端到端冒烟:通过 5174 前端代理访问后端
BASE=http://localhost:5174/api
PASS=0; FAIL=0
check() { if [ "$2" = "$3" ]; then echo "  [PASS] $1"; PASS=$((PASS+1)); else echo "  [FAIL] $1 (期望 $3, 实际 $2)"; FAIL=$((FAIL+1)); fi; }
json_field() { echo "$1" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['$2'])" 2>/dev/null; }

# 用户登录
TOKEN=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" -d '{"email":"demo@example.com","password":"demo123456"}' | python -c "import sys,json;print(json.load(sys.stdin.buffer)['token'])")
[ -n "$TOKEN" ] && echo "  [PASS] 用户登录拿到token" && PASS=$((PASS+1)) || { echo "  [FAIL] 用户登录"; FAIL=$((FAIL+1)); }

# 管理员登录
ADM=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" -d '{"email":"admin@mall.com","password":"admin123456"}' | python -c "import sys,json;print(json.load(sys.stdin.buffer)['token'])")

# 加购商品3 x1
curl -s -o /dev/null -X POST "$BASE/cart" -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"productId":3,"quantity":1}'
CART=$(curl -s "$BASE/cart" -H "Authorization: Bearer $TOKEN")
CID=$(echo "$CART" | python -c "import sys,json;print(json.load(sys.stdin.buffer)[0]['cartItemId'])" 2>/dev/null)
[ -n "$CID" ] && echo "  [PASS] 加购成功" && PASS=$((PASS+1)) || { echo "  [FAIL] 加购"; FAIL=$((FAIL+1)); }

# 下单(积分抵扣 30 = 3 元)
ORDER=$(curl -s -X POST "$BASE/orders" -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d "{\"cartItemIds\":[$CID],\"usePoints\":30,\"receiver\":\"Smoke Test\",\"phone\":\"13800138000\",\"address\":\"Smoke Address\"}")
OID=$(json_field "$ORDER" "id")
st=$(json_field "$ORDER" "status")
check "下单状态 PENDING_PAYMENT" "$st" "PENDING_PAYMENT"
dsc=$(json_field "$ORDER" "discountAmount")
echo "$ORDER" | grep -q "\"discountAmount\":3.00" && echo "  [PASS] 抵扣金额 3.00" && PASS=$((PASS+1)) || { echo "  [FAIL] 抵扣金额 3.00"; FAIL=$((FAIL+1)); }

# 支付
PAID=$(curl -s -X POST "$BASE/orders/$OID/pay" -H "Authorization: Bearer $TOKEN")
st=$(json_field "$PAID" "status")
check "支付后 PAID" "$st" "PAID"

# 管理端订单列表(含用户昵称)
ADM_ORDERS=$(curl -s "$BASE/admin/orders" -H "Authorization: Bearer $ADM")
echo "$ADM_ORDERS" | grep -q "userNickname" && echo "  [PASS] 管理端订单含用户昵称" && PASS=$((PASS+1)) || { echo "  [FAIL] 管理端订单含用户昵称"; FAIL=$((FAIL+1)); }

# 发货
SHIP=$(curl -s -X PUT "$BASE/admin/orders/$OID/ship" -H "Authorization: Bearer $ADM")
st=$(json_field "$SHIP" "status")
check "发货后 SHIPPED" "$st" "SHIPPED"

# 确认收货
DONE=$(curl -s -X POST "$BASE/orders/$OID/confirm" -H "Authorization: Bearer $TOKEN")
st=$(json_field "$DONE" "status")
check "确认收货后 COMPLETED" "$st" "COMPLETED"

# 评价
ITEM=$(echo "$DONE" | python -c "import sys,json;print(json.load(sys.stdin.buffer)['items'][0]['id'])")
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/orders/$OID/review" -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d "{\"orderItemId\":$ITEM,\"rating\":4,\"content\":\"smoke review\"}")
check "评价返回 200" "$code" "200"

# 我的积分流水
LOG=$(curl -s "$BASE/points" -H "Authorization: Bearer $TOKEN")
echo "$LOG" | grep -q "SPEND" && echo "  [PASS] 积分流水含扣减" && PASS=$((PASS+1)) || { echo "  [FAIL] 积分流水含扣减"; FAIL=$((FAIL+1)); }

# 管理端用户列表 + 调整积分
USERS=$(curl -s "$BASE/admin/users" -H "Authorization: Bearer $ADM")
echo "$USERS" | grep -q "demo@example.com" && echo "  [PASS] 管理端用户列表" && PASS=$((PASS+1)) || { echo "  [FAIL] 管理端用户列表"; FAIL=$((FAIL+1)); }
code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/admin/users/2/points" -H "Content-Type: application/json" -H "Authorization: Bearer $ADM" -d '{"points":10,"remark":"smoke bonus"}')
check "调整积分 200" "$code" "200"

# 我的订单列表
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/orders" -H "Authorization: Bearer $TOKEN")
check "我的订单列表 200" "$code" "200"

echo "-------------------------------------"
echo " 通过: $PASS / 失败: $FAIL"
[ "$FAIL" -eq 0 ] && echo "✅ E2E 冒烟通过" || echo "❌ 存在失败"
