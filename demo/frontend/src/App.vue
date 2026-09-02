<template>
  <div id="app">
    <header class="header">
      <div class="header-left">
        <router-link to="/" class="logo">🛒 在线商城</router-link>
      </div>
      <nav class="header-nav">
        <router-link to="/">首页</router-link>
        <router-link v-if="userStore.isLoggedIn" to="/cart">购物车</router-link>
        <router-link v-if="userStore.isLoggedIn" to="/orders">我的订单</router-link>
        <router-link v-if="userStore.isLoggedIn" to="/profile">个人中心</router-link>
        <router-link v-if="userStore.isAdmin" to="/admin">数据看板</router-link>
        <router-link v-if="userStore.isAdmin" to="/admin/products">商品管理</router-link>
        <router-link v-if="userStore.isAdmin" to="/admin/orders">订单管理</router-link>
        <router-link v-if="userStore.isAdmin" to="/admin/users">用户管理</router-link>
      </nav>
      <div class="header-right">
        <template v-if="userStore.isLoggedIn">
          <span class="points" v-if="userStore.user">
            💰 {{ userStore.user.points }} 积分
            <i v-if="userStore.isAdmin" class="admin-tag">管理员</i>
          </span>
          <router-link to="/profile" class="welcome">
            你好, {{ userStore.user?.nickname || userStore.user?.username }}
          </router-link>
          <button class="btn btn-danger logout-btn" @click="logout">退出</button>
        </template>
        <template v-else>
          <router-link to="/login">登录</router-link>
          <router-link to="/register" class="register-link">注册</router-link>
        </template>
      </div>
    </header>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useUserStore } from './store/user'

const router = useRouter()
const userStore = useUserStore()

function logout() {
  userStore.logout()
  router.push('/')
}
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  height: 56px;
  background: #fff;
  border-bottom: 1px solid #eee;
  position: sticky;
  top: 0;
  z-index: 10;
}

.logo {
  font-size: 18px;
  font-weight: bold;
  color: #409eff;
}

.header-nav {
  display: flex;
  gap: 20px;
}

.header-nav a {
  color: #555;
  font-size: 14px;
}

.header-nav a.router-link-exact-active {
  color: #409eff;
  font-weight: bold;
}

.header-right {
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 14px;
}

.welcome {
  color: #333;
}

.points {
  background: #fff7e6;
  color: #d48806;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 13px;
}

.admin-tag {
  font-style: normal;
  background: #f5222d;
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  margin-left: 6px;
}

.logout-btn {
  padding: 5px 12px;
  font-size: 13px;
}

.main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 20px;
}
</style>
