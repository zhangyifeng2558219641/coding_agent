<template>
  <div class="points-page">
    <h2 class="page-title">💰 我的积分</h2>

    <div class="card balance">
      <div class="num">{{ userStore.user?.points ?? '—' }}</div>
      <div class="label">当前积分余额</div>
      <div class="rule">规则:10 积分 = 1 元抵扣 · 支付时按实付金额每 1 元返 1 积分</div>
    </div>

    <div class="card table-wrap">
      <h3 class="sub-title">积分明细</h3>
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>变动</th>
            <th>余额</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in records" :key="r.id">
            <td class="time">{{ formatTime(r.createdAt) }}</td>
            <td><span class="type-tag" :class="typeClass(r.type)">{{ typeLabel(r.type) }}</span></td>
            <td :class="r.points >= 0 ? 'gain' : 'spend'">
              {{ r.points >= 0 ? '+' : '' }}{{ r.points }}
            </td>
            <td>{{ r.balance }}</td>
            <td class="remark">{{ r.remark || '—' }}</td>
          </tr>
          <tr v-if="records.length === 0">
            <td colspan="5" class="empty-row">暂无积分记录</td>
          </tr>
        </tbody>
      </table>
    </div>

    <transition name="fade">
      <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.text }}</div>
    </transition>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useUserStore } from '../store/user'
import { getPointRecords } from '../api/order'

const userStore = useUserStore()
const records = ref([])
const loading = ref(false)
const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null

const typeMap = { SPEND: '消费抵扣', GAIN: '购物返利', ADMIN: '管理员调整' }
const typeLabel = t => typeMap[t] || t
const typeClass = t => (t === 'SPEND' ? 'spend' : t === 'GAIN' ? 'gain' : 'admin')

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
    records.value = await getPointRecords()
  } catch (e) {
    showToast(e.response?.data?.error || '加载积分记录失败', 'error')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-title {
  margin-bottom: 16px;
  font-size: 20px;
}

.balance {
  text-align: center;
  padding: 28px 20px;
  margin-bottom: 16px;
  background: linear-gradient(135deg, #fff7e6, #fff1d6);
}

.num {
  font-size: 40px;
  font-weight: bold;
  color: #d48806;
}

.label {
  font-size: 14px;
  color: #d48806;
  margin-top: 4px;
}

.rule {
  margin-top: 12px;
  font-size: 12px;
  color: #999;
}

.sub-title {
  font-size: 15px;
  margin-bottom: 12px;
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
}

th {
  color: #999;
  font-weight: normal;
  background: #fafafa;
}

.time {
  color: #999;
  white-space: nowrap;
}

.type-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 8px;
}

.type-tag.spend {
  background: #fdecea;
  color: #e74c3c;
}

.type-tag.gain {
  background: #e8f5e9;
  color: #2e7d32;
}

.type-tag.admin {
  background: #e3f2fd;
  color: #1565c0;
}

.gain {
  color: #2e7d32;
  font-weight: bold;
}

.spend {
  color: #e74c3c;
  font-weight: bold;
}

.remark {
  color: #666;
  max-width: 260px;
}

.empty-row {
  text-align: center;
  color: #999;
  padding: 30px 0;
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
