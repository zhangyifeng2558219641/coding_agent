<template>
  <div class="profile" v-if="userStore.user">
    <h2>个人中心</h2>
    <div class="card info">
      <div class="avatar">👤</div>
      <div class="fields">
        <p><span>昵称</span>{{ userStore.user.nickname }}</p>
        <p><span>用户名</span>{{ userStore.user.username }}</p>
        <p><span>邮箱</span>{{ userStore.user.email }}</p>
        <p><span>角色</span>
          <b :class="userStore.isAdmin ? 'text-admin' : ''">
            {{ userStore.isAdmin ? '管理员' : '普通用户' }}
          </b>
        </p>
      </div>
      <div class="points-box">
        <div class="points-num">{{ userStore.user.points }}</div>
        <div class="points-label">当前积分</div>
        <router-link to="/points" class="points-link">积分明细 ›</router-link>
      </div>
    </div>

    <div class="card section">
      <h3>📋 我的服务</h3>
      <div class="menu">
        <router-link to="/orders" class="menu-item">📦 我的订单</router-link>
        <router-link to="/cart" class="menu-item">🛒 购物车</router-link>
        <router-link to="/points" class="menu-item">💰 积分明细</router-link>
      </div>
    </div>

    <div class="card section">
      <h3>⚙️ 账户设置</h3>
      <div class="menu">
        <button class="menu-item btn-plain" @click="openEdit">✏️ 编辑资料 / 修改密码</button>
      </div>
    </div>

    <!-- 编辑资料弹窗 -->
    <div v-if="editShow" class="mask" @click.self="editShow = false">
      <div class="dialog card">
        <h3>编辑资料</h3>
        <label>昵称</label>
        <input v-model.trim="editForm.nickname" placeholder="昵称" />
        <label>手机号</label>
        <input v-model.trim="editForm.phone" placeholder="手机号(可选)" />
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="editShow = false">取消</button>
          <button class="btn" :disabled="saving" @click="submitProfile">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
        <hr />
        <h3>修改密码</h3>
        <label>原密码</label>
        <input v-model="pwdForm.oldPassword" type="password" placeholder="请输入原密码" />
        <label>新密码(至少 6 位)</label>
        <input v-model="pwdForm.newPassword" type="password" placeholder="请输入新密码" />
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="editShow = false">取消</button>
          <button class="btn" :disabled="savingPwd" @click="submitPassword">{{ savingPwd ? '提交中...' : '修改密码' }}</button>
        </div>
      </div>
    </div>

    <div class="card section">
      <h3>📈 最近积分流水</h3>
      <div v-if="records.length === 0" class="empty-tip">暂无积分记录</div>
      <div v-else class="records">
        <div v-for="r in records.slice(0, 5)" :key="r.id" class="rec">
          <span class="rec-type" :class="r.points >= 0 ? 'gain' : 'spend'">
            {{ r.points >= 0 ? '+' : '' }}{{ r.points }}
          </span>
          <span class="rec-text">{{ r.remark || (r.points >= 0 ? '积分增加' : '积分减少') }}</span>
          <span class="rec-time">{{ formatTime(r.createdAt) }}</span>
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
import { useUserStore } from '../store/user'
import { getPointRecords } from '../api/order'
import { updateProfile, changePassword } from '../api/user'

const userStore = useUserStore()
const records = ref([])

// 编辑资料弹窗
const editShow = ref(false)
const saving = ref(false)
const savingPwd = ref(false)
const editForm = reactive({ nickname: '', phone: '' })
const pwdForm = reactive({ oldPassword: '', newPassword: '' })

const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null
function showToast(text, type = 'success') {
  toast.text = text
  toast.type = type
  toast.show = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.show = false), 2200)
}

function openEdit() {
  editForm.nickname = userStore.user?.nickname || ''
  editForm.phone = userStore.user?.phone || ''
  pwdForm.oldPassword = ''
  pwdForm.newPassword = ''
  editShow.value = true
}

async function submitProfile() {
  if (!editForm.nickname) {
    showToast('昵称不能为空', 'error')
    return
  }
  saving.value = true
  try {
    const user = await updateProfile({ nickname: editForm.nickname, phone: editForm.phone })
    userStore.setUser(user)
    localStorage.setItem('user', JSON.stringify(user))
    showToast('资料已保存')
    editShow.value = false
  } catch (e) {
    showToast(e.response?.data?.error || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function submitPassword() {
  if (!pwdForm.oldPassword || !pwdForm.newPassword) {
    showToast('请填写原密码和新密码', 'error')
    return
  }
  if (pwdForm.newPassword.length < 6) {
    showToast('新密码至少 6 位', 'error')
    return
  }
  savingPwd.value = true
  try {
    await changePassword({ oldPassword: pwdForm.oldPassword, newPassword: pwdForm.newPassword })
    pwdForm.oldPassword = ''
    pwdForm.newPassword = ''
    showToast('密码修改成功,请重新登录')
    setTimeout(() => {
      userStore.logout()
      window.location.href = '/login'
    }, 800)
  } catch (e) {
    showToast(e.response?.data?.error || '修改失败', 'error')
  } finally {
    savingPwd.value = false
  }
}

function formatTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(5, 16)
}

onMounted(async () => {
  try {
    records.value = await getPointRecords()
  } catch {
    /* 忽略加载失败 */
  }
})
</script>

<style scoped>
.profile h2 {
  margin-bottom: 16px;
}

.info {
  display: flex;
  gap: 20px;
  align-items: center;
}

.avatar {
  font-size: 48px;
  background: #ecf5ff;
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}

.fields {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 24px;
}

.fields p {
  font-size: 14px;
  color: #333;
}

.fields span {
  color: #999;
  margin-right: 8px;
}

.text-admin {
  color: #f5222d;
}

.points-box {
  text-align: center;
  background: #fff7e6;
  border-radius: 8px;
  padding: 12px 20px;
}

.points-num {
  font-size: 28px;
  font-weight: bold;
  color: #d48806;
}

.points-label {
  font-size: 13px;
  color: #d48806;
}

.points-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: #409eff;
}

.section {
  margin-top: 16px;
}

.section h3 {
  margin-bottom: 12px;
  font-size: 15px;
}

.menu {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.menu-item {
  display: inline-block;
  padding: 12px 20px;
  background: #f5f6fa;
  border-radius: 8px;
  color: #333;
  font-size: 14px;
}

.menu-item:hover {
  background: #ecf5ff;
  color: #409eff;
}

.records {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rec {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  padding: 6px 0;
  border-bottom: 1px dashed #f2f3f5;
}

.rec:last-child {
  border-bottom: none;
}

.rec-type {
  font-weight: bold;
  min-width: 50px;
}

.rec-type.gain {
  color: #2e7d32;
}

.rec-type.spend {
  color: #e74c3c;
}

.rec-text {
  flex: 1;
  color: #555;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-time {
  color: #bbb;
  font-size: 12px;
}

.empty-tip {
  color: #999;
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}

.btn-plain {
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-family: inherit;
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
  width: 420px;
  max-width: calc(100vw - 32px);
  max-height: 80vh;
  overflow-y: auto;
}

.dialog h3 {
  margin-bottom: 12px;
  font-size: 16px;
}

.dialog hr {
  border: none;
  border-top: 1px dashed #eee;
  margin: 18px 0;
}

.dialog label {
  display: block;
  font-size: 13px;
  color: #666;
  margin: 10px 0 4px;
}

.dialog input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
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
