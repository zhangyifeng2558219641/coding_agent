<template>
  <div class="cart-page">
    <h2 class="page-title">🛒 我的购物车</h2>

    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="items.length === 0" class="empty card">
      <p>购物车还是空的</p>
      <router-link to="/" class="btn">去逛逛</router-link>
    </div>

    <template v-else>
      <div class="cart-list">
        <div v-for="item in items" :key="item.cartItemId" class="cart-item card">
          <div class="thumb" :style="thumbStyle(item)">{{ emojiOf(item) }}</div>
          <div class="info">
            <div class="name-row">
              <span class="name">{{ item.productName }}</span>
              <span v-if="item.status !== 'ON_SALE'" class="offline-tag">已下架</span>
            </div>
            <div class="unit-price">单价 ¥{{ item.price }}</div>
            <div class="ops">
              <div class="stepper">
                <button @click="changeQty(item, -1)" :disabled="item.quantity <= 1">−</button>
                <span>{{ item.quantity }}</span>
                <button @click="changeQty(item, 1)" :disabled="item.quantity >= item.stock">+</button>
              </div>
              <button class="remove" @click="remove(item)">删除</button>
            </div>
          </div>
          <div class="subtotal">¥{{ item.subtotal }}</div>
        </div>
      </div>

      <div class="footer card">
        <button class="btn btn-danger" @click="onClear">清空购物车</button>
        <div class="total">
          共 <b>{{ totalCount }}</b> 件,合计 <b class="total-price">¥{{ totalAmount }}</b>
        </div>
        <button class="btn" :disabled="!canCheckout" @click="onCheckout">
          {{ canCheckout ? '去结算' : '存在已下架商品' }}
        </button>
      </div>
    </template>

    <transition name="fade">
      <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.text }}</div>
    </transition>

    <!-- 结算弹窗 -->
    <transition name="fade">
      <div v-if="checkoutShow" class="modal-mask" @click.self="checkoutShow = false">
        <div class="modal card">
          <h3 class="modal-title">确认订单</h3>
          <div class="form">
            <label>
              <span>收货人</span>
              <input v-model.trim="checkout.receiver" placeholder="请输入收货人姓名" />
            </label>
            <label>
              <span>手机号</span>
              <input v-model.trim="checkout.phone" placeholder="请输入11位手机号" maxlength="11" />
            </label>
            <label>
              <span>收货地址</span>
              <input v-model.trim="checkout.address" placeholder="请输入详细地址" />
            </label>
            <label>
              <span>积分抵扣</span>
              <input type="number" v-model.number="checkout.usePoints" min="0" :max="maxUsablePoints" />
            </label>
            <p class="hint">
              10 积分 = 1 元,当前可用 <b>{{ userStore.user?.points || 0 }}</b> 积分,
              本单最多可用 <b>{{ maxUsablePoints }}</b> 积分
            </p>
          </div>
          <div class="amount">
            <div class="amount-row"><span>商品总额</span><b>¥{{ totalAmount }}</b></div>
            <div class="amount-row"><span>积分抵扣</span><b class="discount">-¥{{ discountAmount }}</b></div>
            <div class="amount-row total-row"><span>实付金额</span><b class="actual">¥{{ actualAmount }}</b></div>
          </div>
          <div class="modal-ops">
            <button class="btn btn-plain" @click="checkoutShow = false">取消</button>
            <button class="btn btn-danger" :disabled="submitting" @click="submitOrder">
              {{ submitting ? '提交中...' : '提交订单' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../store/user'
import { getCart, updateCartItem, removeCartItem, clearCart } from '../api/cart'
import { createOrder } from '../api/order'

const router = useRouter()
const userStore = useUserStore()

const items = ref([])
const loading = ref(false)
const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null

const checkoutShow = ref(false)
const submitting = ref(false)
const checkout = reactive({ receiver: '', phone: '', address: '', usePoints: 0 })

function showToast(text, type = 'success') {
  toast.text = text
  toast.type = type
  toast.show = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.show = false), 2200)
}

const totalCount = computed(() => items.value.reduce((s, i) => s + i.quantity, 0))
const totalAmount = computed(() =>
  items.value.reduce((s, i) => s + Number(i.subtotal), 0).toFixed(2)
)
const canCheckout = computed(() => items.value.length > 0 && items.value.every(i => i.status === 'ON_SALE'))

// 积分抵扣:不超过用户积分,且不超过订单总额对应的积分数
const maxUsablePoints = computed(() => {
  const byPoints = userStore.user?.points || 0
  const byAmount = Math.floor(Number(totalAmount.value) * 10)
  return Math.max(0, Math.min(byPoints, byAmount))
})
const discountAmount = computed(() => (Math.floor((checkout.usePoints || 0) / 10)).toFixed(2))
const actualAmount = computed(() =>
  (Number(totalAmount.value) - Number(discountAmount.value)).toFixed(2)
)

const palette = ['#e3f2fd', '#e8f5e9', '#fff3e0', '#fce4ec', '#f3e5f5', '#e0f7fa']
const emojiMap = { 数码: '🎧', 服饰: '👕', 生活: '☕', 食品: '🍎' }

function emojiOf(item) {
  return emojiMap[item.category] || '📦'
}

function thumbStyle(item) {
  return { background: palette[(item.productId || 0) % palette.length] }
}

async function load() {
  loading.value = true
  try {
    items.value = await getCart()
  } catch (e) {
    showToast(e.response?.data?.error || '加载购物车失败', 'error')
  } finally {
    loading.value = false
  }
}

async function changeQty(item, delta) {
  const next = item.quantity + delta
  if (next < 1 || next > item.stock) return
  try {
    const updated = await updateCartItem(item.cartItemId, next)
    item.quantity = updated.quantity
    item.subtotal = updated.subtotal
  } catch (e) {
    showToast(e.response?.data?.error || '修改数量失败', 'error')
  }
}

async function remove(item) {
  try {
    await removeCartItem(item.cartItemId)
    items.value = items.value.filter(i => i.cartItemId !== item.cartItemId)
    showToast('已删除')
  } catch (e) {
    showToast(e.response?.data?.error || '删除失败', 'error')
  }
}

async function onClear() {
  if (!confirm('确定清空购物车吗?')) return
  try {
    await clearCart()
    items.value = []
    showToast('购物车已清空')
  } catch (e) {
    showToast(e.response?.data?.error || '清空失败', 'error')
  }
}

function onCheckout() {
  checkout.receiver = ''
  checkout.phone = ''
  checkout.address = ''
  checkout.usePoints = 0
  checkoutShow.value = true
}

async function submitOrder() {
  if (!checkout.receiver) return showToast('请填写收货人', 'error')
  if (!/^1\d{10}$/.test(checkout.phone)) return showToast('请填写正确的11位手机号', 'error')
  if (!checkout.address) return showToast('请填写收货地址', 'error')
  if ((checkout.usePoints || 0) > maxUsablePoints.value) {
    return showToast(`本单最多可用 ${maxUsablePoints.value} 积分`, 'error')
  }
  submitting.value = true
  try {
    const order = await createOrder({
      cartItemIds: items.value.map(i => i.cartItemId),
      usePoints: checkout.usePoints || 0,
      receiver: checkout.receiver,
      phone: checkout.phone,
      address: checkout.address
    })
    checkoutShow.value = false
    showToast('下单成功,请及时支付')
    items.value = []
    router.push(`/orders?highlight=${order.id}`)
  } catch (e) {
    showToast(e.response?.data?.error || '下单失败', 'error')
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

.cart-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cart-item {
  display: flex;
  align-items: center;
  gap: 16px;
}

.thumb {
  width: 72px;
  height: 72px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  flex-shrink: 0;
}

.info {
  flex: 1;
  min-width: 0;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.name {
  font-weight: bold;
}

.offline-tag {
  font-size: 11px;
  color: #999;
  border: 1px solid #dcdfe6;
  padding: 1px 6px;
  border-radius: 8px;
}

.unit-price {
  color: #999;
  font-size: 13px;
  margin-top: 4px;
}

.ops {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
}

.stepper {
  display: inline-flex;
  align-items: center;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}

.stepper button {
  width: 28px;
  height: 28px;
  border: none;
  background: #f5f6fa;
  cursor: pointer;
  font-size: 16px;
}

.stepper button:disabled {
  color: #ccc;
  cursor: not-allowed;
}

.stepper span {
  width: 40px;
  text-align: center;
  font-size: 14px;
}

.remove {
  border: none;
  background: none;
  color: #e74c3c;
  font-size: 13px;
  cursor: pointer;
}

.subtotal {
  font-size: 16px;
  font-weight: bold;
  color: #f56c6c;
  min-width: 80px;
  text-align: right;
}

.footer {
  margin-top: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.total {
  font-size: 14px;
}

.total-price {
  color: #f56c6c;
  font-size: 20px;
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

/* 结算弹窗 */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  width: 420px;
  max-width: calc(100vw - 32px);
}

.modal-title {
  margin-bottom: 14px;
  font-size: 16px;
}

.form label {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 13px;
}

.form label span {
  width: 64px;
  color: #666;
  text-align: right;
  flex-shrink: 0;
}

.form input {
  flex: 1;
  height: 32px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 0 10px;
  font-size: 13px;
  outline: none;
}

.form input:focus {
  border-color: #409eff;
}

.hint {
  font-size: 12px;
  color: #999;
  padding-left: 74px;
}

.hint b {
  color: #d48806;
}

.amount {
  margin-top: 12px;
  border-top: 1px dashed #eee;
  padding-top: 10px;
}

.amount-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
}

.total-row {
  font-size: 15px;
  color: #333;
}

.actual {
  color: #f56c6c;
  font-size: 18px;
}

.discount {
  color: #e74c3c;
}

.modal-ops {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.btn-plain {
  background: #f5f6fa;
  color: #333;
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
