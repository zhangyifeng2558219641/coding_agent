<template>
  <div class="dashboard">
    <h2 class="page-title">📊 数据看板</h2>

    <div v-if="!stats" class="empty card">加载中...</div>
    <div v-else>
      <!-- 统计卡片 -->
      <div class="cards">
        <div class="card stat">
          <div class="stat-label">总销售额</div>
          <div class="stat-num red">¥{{ fmt(stats.totalSales) }}</div>
          <div class="stat-sub">今日 ¥{{ fmt(stats.todaySales) }}</div>
        </div>
        <div class="card stat">
          <div class="stat-label">订单总数</div>
          <div class="stat-num">{{ stats.totalOrders }}</div>
          <div class="stat-sub">今日 {{ stats.todayOrders }} 单</div>
        </div>
        <div class="card stat">
          <div class="stat-label">待发货</div>
          <div class="stat-num blue">{{ stats.pendingShip }}</div>
          <div class="stat-sub">待支付 {{ stats.pendingPayment }}</div>
        </div>
        <div class="card stat">
          <div class="stat-label">用户数</div>
          <div class="stat-num green">{{ stats.userCount }}</div>
          <div class="stat-sub">注册用户</div>
        </div>
        <div class="card stat">
          <div class="stat-label">商品</div>
          <div class="stat-num orange">{{ stats.onSaleCount }}<i class="unit">/{{ stats.productCount }}</i></div>
          <div class="stat-sub">在售 / 全部</div>
        </div>
      </div>

      <div class="cols">
        <!-- 热门商品 -->
        <div class="card panel">
          <h3>🔥 热门商品 TOP5</h3>
          <div v-if="stats.topProducts.length === 0" class="empty-tip">暂无数据</div>
          <div v-for="(p, i) in stats.topProducts" :key="p.name" class="row">
            <span class="rank" :class="'r' + (i + 1)">{{ i + 1 }}</span>
            <span class="name">{{ p.name }}</span>
            <span class="sales">销量 {{ p.sales }}</span>
            <span class="rating">⭐ {{ p.avg_rating != null ? p.avg_rating : '—' }}</span>
          </div>
        </div>

        <!-- 最近订单 -->
        <div class="card panel">
          <h3>🕐 最近订单</h3>
          <div v-if="stats.recentOrders.length === 0" class="empty-tip">暂无数据</div>
          <div v-for="o in stats.recentOrders" :key="o.id" class="row">
            <span class="order-no">{{ o.order_no }}</span>
            <span class="nick">{{ o.nickname }}</span>
            <span class="amount">¥{{ o.actual_amount }}</span>
            <span class="tag" :class="String(o.status).toLowerCase()">{{ statusLabel(o.status) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getAdminStats } from '../api/admin'

const statusMap = {
  PENDING_PAYMENT: '待支付',
  PAID: '待发货',
  SHIPPED: '待收货',
  COMPLETED: '已完成',
  CANCELLED: '已取消'
}
const statusLabel = s => statusMap[s] || s

const stats = ref(null)

function fmt(v) {
  if (v == null) return '0.00'
  return Number(v).toFixed(2)
}

onMounted(async () => {
  try {
    stats.value = await getAdminStats()
  } catch {
    stats.value = { totalSales: 0, todaySales: 0, totalOrders: 0, todayOrders: 0, pendingShip: 0, pendingPayment: 0, userCount: 0, productCount: 0, onSaleCount: 0, topProducts: [], recentOrders: [] }
  }
})
</script>

<style scoped>
.page-title {
  margin-bottom: 16px;
  font-size: 20px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.stat {
  padding: 18px;
}

.stat-label {
  font-size: 13px;
  color: #999;
  margin-bottom: 8px;
}

.stat-num {
  font-size: 28px;
  font-weight: bold;
  color: #303133;
  line-height: 1.1;
}

.stat-num .unit {
  font-size: 14px;
  font-style: normal;
  color: #bbb;
  font-weight: normal;
}

.stat-num.red { color: #f56c6c; }
.stat-num.blue { color: #409eff; }
.stat-num.green { color: #67c23a; }
.stat-num.orange { color: #e6a23c; }

.stat-sub {
  margin-top: 6px;
  font-size: 12px;
  color: #bbb;
}

.cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 760px) {
  .cols {
    grid-template-columns: 1fr;
  }
}

.panel {
  padding: 18px;
}

.panel h3 {
  font-size: 15px;
  margin-bottom: 12px;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px dashed #f2f3f5;
  font-size: 13px;
}

.row:last-child {
  border-bottom: none;
}

.rank {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #f5f6fa;
  color: #666;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.rank.r1 { background: #fff3e0; color: #e65100; font-weight: bold; }
.rank.r2 { background: #f5f5f5; color: #616161; font-weight: bold; }
.rank.r3 { background: #fdecea; color: #d84315; font-weight: bold; }

.name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sales,
.rating {
  color: #999;
  font-size: 12px;
  flex-shrink: 0;
}

.order-no {
  flex: 1;
  font-size: 12px;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nick {
  color: #999;
  font-size: 12px;
  flex-shrink: 0;
}

.amount {
  font-weight: bold;
  color: #f56c6c;
  flex-shrink: 0;
}

.tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 8px;
  flex-shrink: 0;
}

.tag.pending_payment { background: #fff3e0; color: #e65100; }
.tag.paid { background: #e3f2fd; color: #1565c0; }
.tag.shipped { background: #e8f5e9; color: #2e7d32; }
.tag.completed { background: #f3e5f5; color: #6a1b9a; }
.tag.cancelled { background: #f5f5f5; color: #999; }

.empty-tip {
  text-align: center;
  color: #999;
  padding: 20px 0;
  font-size: 13px;
}

.empty {
  text-align: center;
  color: #999;
  padding: 60px 0;
}
</style>
