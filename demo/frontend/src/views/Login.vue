<template>
  <div class="auth">
    <h1>登录</h1>
    <form class="auth-form" @submit.prevent="submit">
      <input v-model="form.email" type="email" placeholder="邮箱" required />
      <input v-model="form.password" type="password" placeholder="密码" required />
      <p v-if="error" class="error">{{ error }}</p>
      <button class="btn" type="submit" :disabled="loading">
        {{ loading ? '登录中...' : '登录' }}
      </button>
    </form>
    <p class="tip">还没有账号？<router-link to="/register">去注册</router-link></p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../api/auth'
import { useUserStore } from '../store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const form = ref({ email: '', password: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    const data = await login({ ...form.value })
    userStore.setAuth(data.token, data.user)
    // 管理员直接进入个人中心(后续里程碑会跳管理后台)
    router.push(route.query.redirect || '/')
  } catch (e) {
    error.value = e.response?.data?.error || '登录失败：' + e.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth {
  max-width: 380px;
  margin: 60px auto;
  padding: 30px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.auth h1 {
  margin-bottom: 20px;
  text-align: center;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.auth-form input {
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.auth-form input:focus {
  outline: none;
  border-color: #409eff;
}

.error {
  color: #e74c3c;
  font-size: 13px;
}

.tip {
  margin-top: 15px;
  text-align: center;
  font-size: 13px;
  color: #888;
}
</style>
