<template>
  <div class="auth">
    <h1>注册</h1>
    <form class="auth-form" @submit.prevent="submit">
      <input v-model="form.username" placeholder="用户名(2-20位)" required minlength="2" maxlength="20" />
      <input v-model="form.email" type="email" placeholder="邮箱" required />
      <input v-model="form.password" type="password" placeholder="密码(至少6位)" required minlength="6" />
      <p v-if="error" class="error">{{ error }}</p>
      <button class="btn" type="submit" :disabled="loading">
        {{ loading ? '注册中...' : '注册并登录' }}
      </button>
    </form>
    <p class="tip">已有账号？<router-link to="/login">去登录</router-link></p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { register } from '../api/auth'
import { useUserStore } from '../store/user'

const router = useRouter()
const userStore = useUserStore()

const form = ref({ username: '', email: '', password: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    const data = await register({ ...form.value })
    // 注册成功直接签发 token,自动登录
    userStore.setAuth(data.token, data.user)
    router.push('/')
  } catch (e) {
    error.value = e.response?.data?.error || '注册失败：' + e.message
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
