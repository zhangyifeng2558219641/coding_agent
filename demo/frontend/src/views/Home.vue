<template>
  <div class="home">
    <div class="hero card">
      <h1>🛍️ 在线商城</h1>
      <p v-if="!userStore.isLoggedIn">浏览商品,登录后可加入购物车并下单</p>
      <p v-else>你好,<b>{{ userStore.user?.nickname }}</b> —— 尽情选购吧!</p>
    </div>

    <!-- 筛选栏 -->
    <div class="toolbar card">
      <select v-model="filters.category" @change="loadProducts">
        <option value="">全部分类</option>
        <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
      </select>
      <input v-model="filters.keyword" placeholder="搜索商品名称 / 描述" @keyup.enter="loadProducts" />
      <select v-model="filters.sort" @change="loadProducts">
        <option value="">默认排序</option>
        <option value="price">按价格</option>
        <option value="sales">按销量</option>
        <option value="rating">按评分</option>
      </select>
      <button class="btn" @click="loadProducts">查询</button>
    </div>

    <!-- 商品列表 -->
    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="products.length === 0" class="empty">😕 没有找到符合条件的商品</div>
    <div v-else class="grid">
      <div v-for="p in products" :key="p.id" class="product card" @click="goDetail(p)">
        <div class="thumb" :style="thumbStyle(p)">{{ emojiOf(p) }}</div>
        <div class="info">
          <div class="name-row">
            <span class="name" :title="p.name">{{ p.name }}</span>
            <span class="tag">{{ p.category }}</span>
          </div>
          <div class="desc">{{ p.description || '暂无描述' }}</div>
          <div class="meta">
            <span class="price">¥{{ p.price }}</span>
            <span class="stock" :class="{ low: p.stock <= 10 }">库存 {{ p.stock }}</span>
          </div>
          <div class="meta sub">
            <span>销量 {{ p.sales }}</span>
            <span>评分 {{ p.avgRating != null ? p.avgRating : '暂无' }}</span>
          </div>
          <button class="btn buy" :disabled="p.stock <= 0" @click.stop="onAddCart(p)">
            {{ p.stock > 0 ? '加入购物车' : '已售罄' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 轻提示 -->
    <transition name="fade">
      <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.text }}</div>
    </transition>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../store/user'
import { getProducts, getCategories } from '../api/products'
import { addToCart } from '../api/cart'

const router = useRouter()
const userStore = useUserStore()

const products = ref([])
const categories = ref([])
const loading = ref(false)
const filters = reactive({ category: '', keyword: '', sort: '' })

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

function thumbStyle(p) {
  return { background: palette[p.id % palette.length] }
}

function emojiOf(p) {
  const map = { 数码: '🎧', 服饰: '👕', 生活: '☕', 食品: '🍎' }
  return map[p.category] || '📦'
}

async function loadProducts() {
  loading.value = true
  try {
    const data = await getProducts({
      category: filters.category || undefined,
      keyword: filters.keyword || undefined,
      sort: filters.sort || undefined
    })
    products.value = data
  } catch (e) {
    showToast(e.response?.data?.error || '加载商品失败', 'error')
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  try {
    categories.value = await getCategories()
  } catch {
    /* 忽略分类加载失败 */
  }
}

async function onAddCart(p) {
  if (!userStore.isLoggedIn) {
    showToast('请先登录后再加入购物车', 'error')
    setTimeout(() => router.push({ path: '/login', query: { redirect: '/' } }), 600)
    return
  }
  try {
    await addToCart(p.id, 1)
    showToast(`已将「${p.name}」加入购物车`)
  } catch (e) {
    showToast(e.response?.data?.error || '加入购物车失败', 'error')
  }
}

function goDetail(p) {
  router.push(`/product/${p.id}`)
}

onMounted(() => {
  loadCategories()
  loadProducts()
})
</script>

<style scoped>
.hero {
  text-align: center;
  padding: 28px 20px;
  margin-bottom: 16px;
}

.hero h1 {
  color: #409eff;
  margin-bottom: 8px;
}

.hero p {
  color: #666;
}

.toolbar {
  display: flex;
  gap: 10px;
  padding: 14px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar select,
.toolbar input {
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
  outline: none;
}

.toolbar input {
  flex: 1;
  min-width: 200px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 16px;
}

.product {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
  cursor: pointer;
  transition: transform 0.15s;
}

.product:hover {
  transform: translateY(-3px);
}

.thumb {
  height: 130px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 52px;
}

.info {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.name {
  font-weight: bold;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tag {
  flex-shrink: 0;
  font-size: 11px;
  color: #409eff;
  background: #ecf5ff;
  padding: 2px 8px;
  border-radius: 10px;
}

.desc {
  font-size: 12px;
  color: #999;
  min-height: 32px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.meta.sub {
  font-size: 12px;
  color: #999;
}

.price {
  color: #f56c6c;
  font-size: 18px;
  font-weight: bold;
}

.stock {
  font-size: 12px;
  color: #67c23a;
}

.stock.low {
  color: #e6a23c;
}

.buy {
  margin-top: auto;
  width: 100%;
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
