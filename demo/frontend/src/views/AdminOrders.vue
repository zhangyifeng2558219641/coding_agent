<template>
  <div class="admin-page">
    <div class="head">
      <h2>📦 订单管理</h2>
    </div>

    <!-- 状态筛选 -->
    <div class="tabs card">
      <button v-for="t in tabs" :key="t.value" class="tab" :class="{ active: status === t.value }"
              @click="switchStatus(t.value)">
        {{ t.label }}
      </button>
    </div>

    <!-- 搜索 -->
    <div class="search card">
      <input v-model="keyword" placeholder="搜索订单号 / 用户昵称 / 邮箱" @keyup.enter="load" />
      <input v-model="startDate" type="date" class="date" title="开始日期" />
      <input v-model="endDate" type="date" class="date" title="结束日期" />
      <button class="btn" @click="load">搜索</button>
      <button v-if="startDate || endDate || keyword" class="btn btn-ghost" @click="resetFilter">重置</button>
    </div>

    <div class="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>订单号</th>
            <th>用户</th>
            <th>商品</th>
            <th>实付</th>
            <th>积分抵扣</th>
            <th>收货信息</th>
            <th>状态</th>
            <th>下单时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in orders" :key="o.id">
            <td class="no">{{ o.orderNo }}</td>
            <td>{{ userLabel(o) }}</td>
            <td>
              <div v-for="it in o.items" :key="it.id" class="mini-item">
                {{ it.productName }} ×{{ it.quantity }}
              </div>
            </td>
            <td class="actual">¥{{ o.actualAmount }}</td>
            <td>{{ o.discountPoints > 0 ? `-¥${o.discountAmount}` : '—' }}</td>
            <td class="addr">
              {{ o.receiver }} {{ o.phone }}<br />
              <span class="addr-text">{{ o.address }}</span>
            </td>
            <td><span class="status-tag" :class="o.status.toLowerCase()">{{ statusLabel(o.status) }}</span></td>
            <td class="time">{{ formatTime(o.createdAt) }}</td>
            <td class="ops">
              <button v-if="o.status === 'PAID'" class="btn sm" @click="onShip(o)">发货</button>
              <button class="link" @click="openDetail(o)">详情</button>
            </td>
          </tr>
          <tr v-if="orders.length === 0">
            <td colspan="9" class="empty-row">暂无订单</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detailShow" class="mask" @click.self="detailShow = false">
      <div class="dialog card">
        <h3>订单详情</h3>
        <div v-if="detail" class="detail">
          <p><span>订单号</span><b>{{ detail.orderNo }}</b></p>
          <p><span>用户</span>{{ detail.userId }} · {{ userLabel(detail) }}</p>
          <p><span>状态</span><b>{{ statusLabel(detail.status) }}</b></p>
          <p><span>收货人</span>{{ detail.receiver }} {{ detail.phone }}</p>
          <p><span>地址</span>{{ detail.address }}</p>
          <p v-if="Number(detail.discountPoints) > 0"><span>抵扣积分</span>{{ detail.discountPoints }} 积分(-¥{{ detail.discountAmount }})</p>
          <p><span>商品总额</span>¥{{ detail.totalAmount }}</p>
          <p><span>实付金额</span><b class="actual">¥{{ detail.actualAmount }}</b></p>
          <div class="detail-items">
            <div v-for="it in detail.items" :key="it.id" class="drow">
              <span>{{ it.productName }}</span>
              <span>×{{ it.quantity }}</span>
              <span>¥{{ it.price }}</span>
            </div>
          </div>
          <p class="time">{{ formatTime(detail.createdAt) }}</p>
        </div>
        <div v-else-if="detailLoading" class="detail-loading">加载中...</div>
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="detailShow = false">关闭</button>
        </div>
      </div>
    </div>

    <transition name="fade">
      <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.text }}</div>
    </transition>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { getAdminOrders, getAdminOrderDetail, shipOrder } from '../api/admin'

const tabs = [
  { value: '', label: '全部' },
  { value: 'PENDING_PAYMENT', label: '待支付' },
  { value: 'PAID', label: '待发货' },
  { value: 'SHIPPED', label: '待收货' },
  { value: 'COMPLETED', label: '已完成' },
  { value: 'CANCELLED', label: '已取消' }
]
const statusMap = {
  PENDING_PAYMENT: '待支付',
  PAID: '待发货',
  SHIPPED: '待收货',
  COMPLETED: '已完成',
  CANCELLED: '已取消'
}
const statusLabel = s => statusMap[s] || s

const orders = ref([])
const loading = ref(false)
const status = ref('')
const keyword = ref('')
const startDate = ref('')
const endDate = ref('')
const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null
const detailShow = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

function showToast(text, type = 'success') {
  toast.text = text
  toast.type = type
  toast.show = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.show = false), 2200)
}

function formatTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 19)
}

function userLabel(o) {
  return o.userNickname || o.userEmail || `#${o.userId}`
}

async function load() {
  loading.value = true
  try {
    orders.value = await getAdminOrders(status.value, keyword.value, startDate.value, endDate.value)
  } catch (e) {
    showToast(e.response?.data?.error || '加载订单失败', 'error')
  } finally {
    loading.value = false
  }
}

function switchStatus(v) {
  status.value = v
  load()
}

function resetFilter() {
  keyword.value = ''
  startDate.value = ''
  endDate.value = ''
  load()
}

async function onShip(o) {
  if (!confirm(`确认为订单 ${o.orderNo} 发货?`)) return
  try {
    await shipOrder(o.id)
    showToast('已发货')
    load()
  } catch (e) {
    showToast(e.response?.data?.error || '发货失败', 'error')
  }
}

async function openDetail(o) {
  detailShow.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await getAdminOrderDetail(o.id)
  } catch (e) {
    showToast(e.response?.data?.error || '加载订单详情失败', 'error')
    detailShow.value = false
  } finally {
    detailLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.head h2 {
  font-size: 20px;
}

.tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 16px;
  padding: 8px;
  flex-wrap: wrap;
}

.tab {
  border: none;
  background: none;
  padding: 6px 14px;
  font-size: 14px;
  color: #666;
  cursor: pointer;
  border-radius: 4px;
}

.tab.active {
  background: #409eff;
  color: #fff;
}

.search {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 16px;
}

.search input {
  flex: 1;
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
  outline: none;
}

.search input.date {
  flex: 0 0 150px;
  font-size: 13px;
  color: #666;
}

.detail-loading {
  text-align: center;
  color: #999;
  padding: 24px 0;
  font-size: 13px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th,
td {
  padding: 10px 8px;
  text-align: left;
  border-bottom: 1px solid #f2f3f5;
  vertical-align: top;
}

th {
  color: #999;
  font-weight: normal;
  background: #fafafa;
  white-space: nowrap;
}

.no {
  font-size: 12px;
  white-space: nowrap;
}

.mini-item {
  line-height: 1.6;
  white-space: nowrap;
}

.actual {
  color: #f56c6c;
  font-weight: bold;
  white-space: nowrap;
}

.addr {
  max-width: 200px;
  font-size: 12px;
  color: #666;
}

.addr-text {
  color: #999;
}

.status-tag {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  white-space: nowrap;
}

.status-tag.pending_payment {
  background: #fff3e0;
  color: #e65100;
}

.status-tag.paid {
  background: #e3f2fd;
  color: #1565c0;
}

.status-tag.shipped {
  background: #e8f5e9;
  color: #2e7d32;
}

.status-tag.completed {
  background: #f3e5f5;
  color: #6a1b9a;
}

.status-tag.cancelled {
  background: #f5f5f5;
  color: #999;
}

.time {
  color: #999;
  font-size: 12px;
  white-space: nowrap;
}

.ops {
  display: flex;
  gap: 8px;
  align-items: center;
  white-space: nowrap;
}

.sm {
  padding: 5px 12px;
  font-size: 13px;
}

.link {
  border: none;
  background: none;
  color: #409eff;
  cursor: pointer;
  font-size: 13px;
}

.empty-row {
  text-align: center;
  color: #999;
  padding: 30px 0;
}

.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.dialog {
  width: 460px;
  max-width: calc(100vw - 32px);
  max-height: 80vh;
  overflow-y: auto;
}

.dialog h3 {
  margin-bottom: 14px;
  font-size: 16px;
}

.detail p {
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
}

.detail p span {
  display: inline-block;
  width: 80px;
  color: #999;
}

.detail-items {
  border-top: 1px dashed #eee;
  margin: 8px 0;
  padding: 8px 0;
}

.drow {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #333;
  padding: 3px 0;
}

.dialog-ops {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.btn-ghost {
  background: #f5f6fa;
  color: #333;
}

.toast {
  position: fixed;
  top: 70px;
  left: 50%;
  transform: translateX(-50%);
  background: #303133;
  color: #fff;
  padding: 10px 22px;
  border-radius: 6px;
  font-size: 14px;
  z-index: 99;
}

.toast.error {
  background: #e74c3c;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
