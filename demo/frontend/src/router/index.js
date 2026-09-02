import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import ProductDetail from '../views/ProductDetail.vue'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'
import Profile from '../views/Profile.vue'
import Cart from '../views/Cart.vue'
import OrderList from '../views/OrderList.vue'
import Points from '../views/Points.vue'
import AdminProducts from '../views/AdminProducts.vue'
import AdminOrders from '../views/AdminOrders.vue'
import AdminUsers from '../views/AdminUsers.vue'
import AdminDashboard from '../views/AdminDashboard.vue'

const routes = [
  { path: '/', name: 'Home', component: Home },
  { path: '/product/:id', name: 'ProductDetail', component: ProductDetail },
  { path: '/login', name: 'Login', component: Login, meta: { guestOnly: true } },
  { path: '/register', name: 'Register', component: Register, meta: { guestOnly: true } },
  { path: '/profile', name: 'Profile', component: Profile, meta: { requiresAuth: true } },
  { path: '/cart', name: 'Cart', component: Cart, meta: { requiresAuth: true } },
  { path: '/orders', name: 'OrderList', component: OrderList, meta: { requiresAuth: true } },
  { path: '/points', name: 'Points', component: Points, meta: { requiresAuth: true } },
  { path: '/admin/products', name: 'AdminProducts', component: AdminProducts, meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/admin/orders', name: 'AdminOrders', component: AdminOrders, meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/admin/users', name: 'AdminUsers', component: AdminUsers, meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/admin', name: 'AdminDashboard', component: AdminDashboard, meta: { requiresAuth: true, requiresAdmin: true } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

function readUser() {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null')
  } catch {
    return null
  }
}

// 全局路由守卫:
// 1. requiresAuth 页面未登录 -> 跳转 /login 并携带 redirect
// 2. guestOnly 页面已登录 -> 跳转首页
// 3. requiresAdmin 页面非管理员 -> 跳转首页
router.beforeEach(to => {
  const token = localStorage.getItem('token')
  const user = readUser()

  if (to.meta.requiresAuth && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.meta.guestOnly && token) {
    return { path: '/' }
  }

  if (to.meta.requiresAdmin && user?.role !== 'ADMIN') {
    return { path: '/' }
  }

  return true
})

export default router
