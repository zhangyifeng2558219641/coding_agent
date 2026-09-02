<template>
  <div class="orders-page">
    <h2 class="page-title">📋 我的订单</h2>

    <!-- 状态筛选 -->
    <div class="tabs card">
      <button v-for="t in tabs" :key="t.value" class="tab" :class="{ active: status === t.value }"
              @click="switchStatus(t.value)">
        {{ t.label }}
      </button>
    </div>

    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="orders.length === 0" class="empty card">
      <p>暂无相关订单</p>
      <router-link to="/" class="btn">去逛逛</router-link>
    </div>

    <div v-else class="order-list">
      <div v-for="o in orders" :key="o.id" class="order card" :class="{ highlight: o.id === highlightId }">
        <div class="order-head">
          <div class="no">
            <span>订单号</span>
            <b>{{ o.orderNo }}</b>
          </div>
          <span class="status-tag" :class="o.status.toLowerCase()">{{ statusLabel(o.status) }}</span>
        </div>
        <div class="order-items">
          <div v-for="it in o.items" :key="it.id" class="item-row">
            <span class="item-name">{{ it.productName }}</span>
            <span class="item-qty">×{{ it.quantity }}</span>
            <span class="item-price">¥{{ it.price }}</span>
          </div>
        </div>
        <div class="order-foot">
          <div class="amounts">
            <span v-if="Number(o.discountAmount) > 0" class="disc">积分抵扣 -¥{{ o.discountAmount }}</span>
            <span>实付 <b class="actual">¥{{ o.actualAmount }}</b></span>
            <span class="time">{{ formatTime(o.createdAt) }}</span>
          </div>
          <div class="ops">
            <button v-if="o.status === 'PENDING_PAYMENT'" class="btn btn-danger sm" @click="onPay(o)">立即支付</button>
            <button v-if="o.status === 'PENDING_PAYMENT'" class="btn btn-ghost sm" @click="onCancel(o)">取消订单</button>
            <button v-if="o.status === 'SHIPPED'" class="btn sm" @click="onConfirm(o)">确认收货</button>
            <button v-if="o.status === 'COMPLETED'" class="btn sm" @click="openReview(o)">评价</button>
            <button class="link" @click="openDetail(o)">查看详情</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 订单详情弹窗 -->
    <div v-if="detailShow" class="mask" @click.self="detailShow = false">
      <div class="dialog card">
        <h3>订单详情</h3>
        <div v-if="detail" class="detail">
          <p><span>订单号</span><b>{{ detail.orderNo }}</b></p>
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
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="detailShow = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 评价弹窗 -->
    <div v-if="reviewShow" class="mask" @click.self="reviewShow = false">
      <div class="dialog card">
        <h3>商品评价</h3>
        <label>商品</label>
        <div class="review-product">{{ reviewItem?.productName }} ×{{ reviewItem?.quantity }}</div>
        <label>评分</label>
        <div class="stars">
          <span v-for="n in 5" :key="n" class="star" :class="{ active: n <= reviewForm.rating }" @click="reviewForm.rating = n">
            ★
          </span>
        </div>
        <label>评价内容</label>
        <textarea v-model.trim="reviewForm.content" rows="3" placeholder="说说商品怎么样吧(可选)"></textarea>
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="reviewShow = false">取消</button>
          <button class="btn" :disabled="submitting" @click="submitReview">{{ submitting ? '提交中...' : '提交评价' }}</button>
        </div>
      </div>
    </div>

    <transition name="fade">
      <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.text }}</div>
    </transition>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getMyOrders, getOrderDetail, payOrder, cancelOrder, confirmOrder, reviewOrder } from '../api/order'

const route = useRoute()

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
const highlightId = ref(Number(route.query.highlight) || 0)
const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null

const detailShow = ref(false)
const detail = ref(null)
const reviewShow = ref(false)
const reviewOrderId = ref(null)
const reviewItem = ref(null)
const reviewForm = reactive({ rating: 5, content: '' })
const submitting = ref(false)

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

async function load() {
  loading.value = true
  try {
    orders.value = await getMyOrders(status.value)
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

async function onPay(o) {
  if (!confirm(`确认支付订单 ${o.orderNo} 吗?(实付 ¥${o.actualAmount},使用 ${o.discountPoints} 积分)`)) return
  try {
    await payOrder(o.id)
    showToast('支付成功')
    load()
  } catch (e) {
    showToast(e.response?.data?.error || '支付失败', 'error')
  }
}

async function onCancel(o) {
  if (!confirm(`确认取消订单 ${o.orderNo} 吗?`)) return
  try {
    await cancelOrder(o.id)
    showToast('订单已取消')
    load()
  } catch (e) {
    showToast(e.response?.data?.error || '取消失败', 'error')
  }
}

async function onConfirm(o) {
  if (!confirm('确认已收到货吗?')) return
  try {
    await confirmOrder(o.id)
    showToast('已确认收货,欢迎评价')
    load()
  } catch (e) {
    showToast(e.response?.data?.error || '操作失败', 'error')
  }
}

async function openDetail(o) {
  try {
    detail.value = await getOrderDetail(o.id)
    detailShow.value = true
  } catch (e) {
    showToast(e.response?.data?.error || '加载详情失败', 'error')
  }
}

function openReview(o) {
  reviewOrderId.value = o.id
  reviewItem.value = o.items && o.items.length ? o.items[0] : null
  reviewForm.rating = 5
  reviewForm.content = ''
  reviewShow.value = true
}

async function submitReview() {
  if (!reviewItem.value) return
  submitting.value = true
  try {
    await reviewOrder(reviewOrderId.value, {
      orderItemId: reviewItem.value.id,
      rating: reviewForm.rating,
      content: reviewForm.content
    })
    reviewShow.value = false
    showToast('评价成功')
  } catch (e) {
    showToast(e.response?.data?.error || '评价失败', 'error')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-title {
  margin-bottom: 16px;
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

.order-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.order {
  transition: box-shadow 0.3s;
}

.order.highlight {
  box-shadow: 0 0 0 2px #409eff;
}

.order-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 10px;
  border-bottom: 1px dashed #eee;
}

.no {
  font-size: 13px;
  color: #999;
}

.no b {
  color: #333;
  margin-left: 8px;
}

.status-tag {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
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

.order-items {
  padding: 10px 0;
}

.item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 14px;
  gap: 12px;
}

.item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-qty {
  color: #999;
  font-size: 13px;
  flex-shrink: 0;
}

.item-price {
  font-weight: bold;
  flex-shrink: 0;
  min-width: 70px;
  text-align: right;
}

.order-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px dashed #eee;
}

.amounts {
  display: flex;
  gap: 14px;
  font-size: 13px;
  color: #666;
  align-items: center;
  flex-wrap: wrap;
}

.disc {
  color: #e74c3c;
}

.actual {
  color: #f56c6c;
  font-size: 16px;
}

.time {
  color: #bbb;
  font-size: 12px;
}

.ops {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.sm {
  padding: 5px 12px;
  font-size: 13px;
}

.btn-ghost {
  background: #f5f6fa;
  color: #333;
}

.link {
  border: none;
  background: none;
  color: #409eff;
  cursor: pointer;
  font-size: 13px;
}

/* 弹窗 */
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

.time {
  color: #bbb;
}

.dialog label {
  display: block;
  font-size: 13px;
  color: #666;
  margin: 10px 0 4px;
}

.review-product {
  font-size: 14px;
  font-weight: bold;
  padding: 6px 0;
}

.stars {
  font-size: 26px;
  letter-spacing: 4px;
  cursor: pointer;
}

.star {
  color: #ddd;
}

.star.active {
  color: #f5a623;
}

.dialog textarea {
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 8px;
  font-size: 13px;
  resize: vertical;
  outline: none;
  font-family: inherit;
}

.dialog textarea:focus {
  border-color: #409eff;
}

.dialog-ops {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.empty {
  text-align: center;
  color: #999;
  padding: 60px 0;
}

.empty .btn {
  margin-top: 16px;
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
