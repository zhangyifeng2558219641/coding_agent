<template>
  <div class="admin-page">
    <div class="head">
      <h2>👥 用户管理</h2>
    </div>

    <div class="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>昵称</th>
            <th>用户名</th>
            <th>邮箱</th>
            <th>角色</th>
            <th>积分</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.id }}</td>
            <td>{{ u.nickname }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.email }}</td>
            <td>
              <span class="role-tag" :class="u.role === 'ADMIN' ? 'admin' : 'user'">
                {{ u.role === 'ADMIN' ? '管理员' : '用户' }}
              </span>
            </td>
            <td class="points-num">{{ u.points }}</td>
            <td class="ops">
              <button class="btn sm ghost" @click="openRecords(u)">积分明细</button>
              <button class="btn sm" @click="openAdjust(u)">调整积分</button>
            </td>
          </tr>
          <tr v-if="users.length === 0">
            <td colspan="7" class="empty-row">暂无用户</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 积分明细弹窗 -->
    <div v-if="recordsShow" class="mask" @click.self="recordsShow = false">
      <div class="dialog wide">
        <h3>积分明细 —— {{ recordsTarget?.nickname || recordsTarget?.username }}</h3>
        <p class="current">当前积分:<b>{{ recordsTarget?.points }}</b></p>
        <div class="records">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>类型</th>
                <th>变动</th>
                <th>余额</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in records" :key="r.id">
                <td class="time">{{ formatTime(r.createdAt) }}</td>
                <td><span class="rec-type" :class="r.type.toLowerCase()">{{ typeLabel(r.type) }}</span></td>
                <td :class="r.points > 0 ? 'gain' : 'spend'">{{ r.points > 0 ? '+' : '' }}{{ r.points }}</td>
                <td>{{ r.balance }}</td>
                <td class="remark">{{ r.remark }}</td>
              </tr>
              <tr v-if="recordsLoading">
                <td colspan="5" class="empty-row">加载中...</td>
              </tr>
              <tr v-if="!recordsLoading && records.length === 0">
                <td colspan="5" class="empty-row">暂无积分流水</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="recordsShow = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 调整积分弹窗 -->
    <div v-if="dialogShow" class="mask" @click.self="dialogShow = false">
      <div class="dialog card">
        <h3>调整积分 —— {{ target?.nickname || target?.username }}</h3>
        <p class="current">当前积分:<b>{{ target?.points }}</b>(调整后不得为负)</p>
        <label>变动值</label>
        <input v-model.number="adjust.points" type="number" placeholder="正数加分,负数扣分" />
        <label>备注</label>
        <input v-model.trim="adjust.remark" placeholder="调整原因(可选)" />
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="dialogShow = false">取消</button>
          <button class="btn" :disabled="saving" @click="submit">{{ saving ? '保存中...' : '保存' }}</button>
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
import { getUsers, adjustUserPoints, getUserPointRecords } from '../api/admin'

const users = ref([])
const loading = ref(false)
const saving = ref(false)
const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null

const dialogShow = ref(false)
const target = ref(null)
const adjust = reactive({ points: 0, remark: '' })

const recordsShow = ref(false)
const recordsTarget = ref(null)
const records = ref([])
const recordsLoading = ref(false)

const typeMap = { GAIN: '获得', SPEND: '使用', ADMIN: '管理员调整' }
const typeLabel = t => typeMap[t] || t

function formatTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 19)
}

function showToast(text, type = 'success') {
  toast.text = text
  toast.type = type
  toast.show = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.show = false), 2200)
}

async function load() {
  loading.value = true
  try {
    users.value = await getUsers()
  } catch (e) {
    showToast(e.response?.data?.error || '加载用户失败', 'error')
  } finally {
    loading.value = false
  }
}

function openAdjust(u) {
  target.value = u
  adjust.points = 0
  adjust.remark = ''
  dialogShow.value = true
}

async function openRecords(u) {
  recordsTarget.value = u
  records.value = []
  recordsShow.value = true
  recordsLoading.value = true
  try {
    records.value = await getUserPointRecords(u.id)
  } catch (e) {
    showToast(e.response?.data?.error || '加载积分明细失败', 'error')
    recordsShow.value = false
  } finally {
    recordsLoading.value = false
  }
}

async function submit() {
  if (!adjust.points || adjust.points === 0) return showToast('请输入非零变动值', 'error')
  if (!Number.isInteger(adjust.points)) return showToast('积分必须为整数', 'error')
  saving.value = true
  try {
    await adjustUserPoints(target.value.id, adjust.points, adjust.remark)
    dialogShow.value = false
    showToast('积分调整成功')
    load()
  } catch (e) {
    showToast(e.response?.data?.error || '调整失败', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  margin-bottom: 16px;
}

.head h2 {
  font-size: 20px;
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

.role-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 8px;
}

.role-tag.admin {
  background: #fdecea;
  color: #e74c3c;
}

.role-tag.user {
  background: #e8f5e9;
  color: #2e7d32;
}

.points-num {
  font-weight: bold;
  color: #d48806;
}

.ops {
  white-space: nowrap;
}

.sm {
  padding: 5px 12px;
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
  width: 400px;
  max-width: calc(100vw - 32px);
}

.dialog.wide {
  width: 680px;
  max-width: calc(100vw - 32px);
}

.dialog h3 {
  margin-bottom: 8px;
  font-size: 16px;
}

.records {
  max-height: 50vh;
  overflow-y: auto;
  border: 1px solid #f2f3f5;
  border-radius: 4px;
}

.records table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.records th,
.records td {
  padding: 8px 6px;
  text-align: left;
  border-bottom: 1px solid #f5f6fa;
}

.records th {
  background: #fafafa;
  color: #999;
  font-weight: normal;
  white-space: nowrap;
}

.rec-type {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 8px;
  white-space: nowrap;
}

.rec-type.gain {
  background: #e8f5e9;
  color: #2e7d32;
}

.rec-type.spend {
  background: #fff3e0;
  color: #e65100;
}

.rec-type.admin {
  background: #e3f2fd;
  color: #1565c0;
}

.gain {
  color: #2e7d32;
  font-weight: bold;
}

.spend {
  color: #e65100;
  font-weight: bold;
}

.remark {
  color: #666;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ghost {
  background: #f5f6fa;
  color: #333;
}

.current {
  font-size: 13px;
  color: #666;
  margin-bottom: 12px;
}

.current b {
  color: #d48806;
  margin: 0 4px;
}

.dialog label {
  display: block;
  font-size: 13px;
  color: #666;
  margin: 10px 0 4px;
}

.dialog input {
  width: 100%;
  height: 32px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 0 10px;
  font-size: 13px;
  outline: none;
}

.dialog input:focus {
  border-color: #409eff;
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
