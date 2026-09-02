<template>
  <div class="detail-page">
    <button class="back link" @click="goBack">← 返回商品列表</button>

    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="!product" class="empty">😕 商品不存在或已下架</div>
    <div v-else>
      <!-- 商品信息 -->
      <div class="product card">
        <div class="thumb" :style="thumbStyle">{{ emojiOf }}</div>
        <div class="info">
          <div class="name-row">
            <h2 class="name">{{ product.name }}</h2>
            <span class="tag">{{ product.category }}</span>
          </div>
          <p class="desc">{{ product.description || '暂无描述' }}</p>
          <div class="meta">
            <span class="price">¥{{ product.price }}</span>
            <span class="stock" :class="{ low: product.stock <= 10 }">库存 {{ product.stock }}</span>
          </div>
          <div class="meta sub">
            <span>销量 {{ product.sales }}</span>
            <span>
              评分
              <template v-if="product.avgRating != null">{{ product.avgRating }} 分</template>
              <template v-else>暂无</template>
            </span>
          </div>
          <button class="btn buy" :disabled="product.stock <= 0" @click="onAddCart">
            {{ product.stock > 0 ? '加入购物车' : '已售罄' }}
          </button>
        </div>
      </div>

      <!-- 评价列表 -->
      <div class="card reviews">
        <div class="rev-head">
          <h3>💬 用户评价</h3>
          <span v-if="reviews.length" class="count">共 {{ reviews.length }} 条</span>
        </div>
        <div v-if="reviews.length === 0" class="no-rev">暂无评价,购买后可评价</div>
        <div v-for="r in reviews" :key="r.id" class="rev">
          <div class="rev-top">
            <span class="nick">{{ r.userNickname || `用户#${r.userId}` }}</span>
            <span class="stars">{{ '★'.repeat(r.rating) }}<i>{{ '☆'.repeat(5 - r.rating) }}</i></span>
            <span class="time">{{ formatTime(r.createdAt) }}</span>
          </div>
          <div class="content">{{ r.content }}</div>
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
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../store/user'
import { getProduct, getProductReviews } from '../api/products'
import { addToCart } from '../api/cart'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const product = ref(null)
const reviews = ref([])
const loading = ref(false)

const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null
function showToast(text, type = 'success') {
  toast.text = text
  toast.type = type
  toast.show = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.show = false), 2200)
}

const palette = ['#e3f2fd', '#e8f5e9', '#fff3e0', '#fce4ec', '#f3e5f5', '#e0f7fa', '#fffde7', '#e0f2f1']

const thumbStyle = computed(() => ({ background: palette[product.value.id % palette.length] }))

const emojiMap = { 数码: '🎧', 服饰: '👕', 生活: '☕', 食品: '🍎' }
const emojiOf = computed(() => emojiMap[product.value.category] || '📦')

function formatTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 19)
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

async function load() {
  const id = route.params.id
  loading.value = true
  try {
    const [p, rs] = await Promise.all([getProduct(id), getProductReviews(id)])
    product.value = p
    reviews.value = rs
  } catch (e) {
    showToast(e.response?.data?.error || '加载商品失败', 'error')
  } finally {
    loading.value = false
  }
}

async function onAddCart() {
  if (!userStore.isLoggedIn) {
    showToast('请先登录后再加入购物车', 'error')
    setTimeout(() => router.push({ path: '/login', query: { redirect: route.fullPath } }), 600)
    return
  }
  try {
    await addToCart(product.value.id, 1)
    showToast(`已将「${product.value.name}」加入购物车`)
  } catch (e) {
    showToast(e.response?.data?.error || '加入购物车失败', 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.back {
  margin-bottom: 14px;
  font-size: 14px;
}

.link {
  border: none;
  background: none;
  color: #409eff;
  cursor: pointer;
  padding: 0;
}

.product {
  display: flex;
  gap: 24px;
  padding: 24px;
  margin-bottom: 16px;
}

.thumb {
  width: 220px;
  min-height: 180px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 80px;
  flex-shrink: 0;
}

.info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.name {
  font-size: 20px;
}

.tag {
  font-size: 12px;
  color: #409eff;
  background: #ecf5ff;
  padding: 2px 10px;
  border-radius: 10px;
}

.desc {
  color: #666;
  font-size: 14px;
  line-height: 1.6;
}

.meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.meta.sub {
  font-size: 13px;
  color: #999;
}

.price {
  color: #f56c6c;
  font-size: 24px;
  font-weight: bold;
}

.stock {
  font-size: 13px;
  color: #67c23a;
}

.stock.low {
  color: #e6a23c;
}

.buy {
  margin-top: 10px;
  align-self: flex-start;
  padding: 10px 34px;
  font-size: 15px;
}

.reviews {
  padding: 20px 24px;
}

.rev-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.rev-head h3 {
  font-size: 16px;
}

.count {
  font-size: 12px;
  color: #999;
}

.no-rev {
  text-align: center;
  color: #999;
  padding: 30px 0;
}

.rev {
  border-top: 1px solid #f2f3f5;
  padding: 12px 0;
}

.rev-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.nick {
  font-weight: bold;
  font-size: 14px;
}

.stars {
  color: #f5a623;
  font-size: 14px;
}

.stars i {
  color: #ddd;
  font-style: normal;
}

.time {
  margin-left: auto;
  color: #999;
  font-size: 12px;
}

.content {
  color: #555;
  font-size: 14px;
  line-height: 1.6;
}

.empty {
  text-align: center;
  color: #999;
  padding: 60px 0;
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
