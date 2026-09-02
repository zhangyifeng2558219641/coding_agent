<template>
  <div class="admin-page">
    <div class="head">
      <h2>📦 商品管理</h2>
      <button class="btn" @click="openCreate">+ 新增商品</button>
    </div>

    <div class="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>名称</th>
            <th>分类</th>
            <th>价格</th>
            <th>库存</th>
            <th>销量</th>
            <th>评分</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in products" :key="p.id">
            <td>{{ p.id }}</td>
            <td class="name-cell" :title="p.description">{{ p.name }}</td>
            <td>{{ p.category }}</td>
            <td>¥{{ p.price }}</td>
            <td>
              <span :class="{ 'low-stock': p.stock <= 5 }">{{ p.stock }}</span>
              <span v-if="p.stock <= 5" class="low-tag">库存不足</span>
            </td>
            <td>{{ p.sales }}</td>
            <td>{{ p.avgRating != null ? p.avgRating : '—' }}</td>
            <td>
              <span class="status" :class="p.status === 'ON_SALE' ? 'on' : 'off'">
                {{ p.status === 'ON_SALE' ? '在售' : '已下架' }}
              </span>
            </td>
            <td class="ops">
              <button class="link" @click="openEdit(p)">编辑</button>
              <button class="link" :class="p.status === 'ON_SALE' ? 'danger' : 'ok'"
                      @click="toggleStatus(p)">
                {{ p.status === 'ON_SALE' ? '下架' : '上架' }}
              </button>
            </td>
          </tr>
          <tr v-if="products.length === 0">
            <td colspan="9" class="empty-row">暂无商品</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 新增/编辑弹窗 -->
    <div v-if="dialog.show" class="mask" @click.self="closeDialog">
      <div class="dialog card">
        <h3>{{ dialog.editing ? '编辑商品' : '新增商品' }}</h3>
        <label>名称 *</label>
        <input v-model="form.name" placeholder="商品名称" />
        <label>分类</label>
        <input v-model="form.category" placeholder="如: 数码 / 服饰 / 生活 / 食品" />
        <label>描述</label>
        <textarea v-model="form.description" rows="2" placeholder="商品描述"></textarea>
        <label>价格 *</label>
        <input v-model.number="form.price" type="number" min="0" step="0.01" placeholder="0.00" />
        <label>库存 *</label>
        <input v-model.number="form.stock" type="number" min="0" placeholder="0" />
        <label>状态</label>
        <select v-model="form.status">
          <option value="ON_SALE">上架</option>
          <option value="OFF_SHELF">下架</option>
        </select>
        <div class="dialog-ops">
          <button class="btn btn-ghost" @click="closeDialog">取消</button>
          <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中...' : '保存' }}</button>
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
import { getAdminProducts, createProduct, updateProduct, updateProductStatus } from '../api/admin'

const products = ref([])
const loading = ref(false)
const saving = ref(false)
const toast = reactive({ show: false, text: '', type: 'success' })
let toastTimer = null

const dialog = reactive({ show: false, editing: false, id: null })
const emptyForm = () => ({ name: '', category: '', description: '', price: 0, stock: 0, status: 'ON_SALE' })
const form = reactive(emptyForm())

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
    products.value = await getAdminProducts()
  } catch (e) {
    showToast(e.response?.data?.error || '加载商品失败', 'error')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, emptyForm())
  dialog.editing = false
  dialog.id = null
  dialog.show = true
}

function openEdit(p) {
  Object.assign(form, {
    name: p.name,
    category: p.category || '',
    description: p.description || '',
    price: Number(p.price),
    stock: p.stock,
    status: p.status
  })
  dialog.editing = true
  dialog.id = p.id
  dialog.show = true
}

function closeDialog() {
  dialog.show = false
}

async function save() {
  if (!form.name.trim()) {
    showToast('请填写商品名称', 'error')
    return
  }
  saving.value = true
  try {
    if (dialog.editing) {
      await updateProduct(dialog.id, { ...form })
      showToast('商品已更新')
    } else {
      await createProduct({ ...form })
      showToast('商品已创建')
    }
    dialog.show = false
    load()
  } catch (e) {
    showToast(e.response?.data?.error || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function toggleStatus(p) {
  const next = p.status === 'ON_SALE' ? 'OFF_SHELF' : 'ON_SALE'
  try {
    await updateProductStatus(p.id, next)
    p.status = next
    showToast(next === 'ON_SALE' ? '已上架' : '已下架')
  } catch (e) {
    showToast(e.response?.data?.error || '操作失败', 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.table-wrap {
  overflow-x: auto;
  padding: 8px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

th,
td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
}

th {
  color: #999;
  font-weight: normal;
  background: #fafafa;
}

.name-cell {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.low-stock {
  color: #e74c3c;
  font-weight: bold;
}

.low-tag {
  font-size: 11px;
  background: #fdecea;
  color: #e74c3c;
  padding: 1px 6px;
  border-radius: 8px;
  margin-left: 6px;
}

.status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
}

.status.on {
  background: #f0f9eb;
  color: #67c23a;
}

.status.off {
  background: #f4f4f5;
  color: #909399;
}

.ops {
  display: flex;
  gap: 10px;
}

.link {
  border: none;
  background: none;
  color: #409eff;
  cursor: pointer;
  font-size: 13px;
}

.link.danger {
  color: #e74c3c;
}

.link.ok {
  color: #67c23a;
}

.empty-row {
  text-align: center;
  color: #999;
  padding: 30px;
}

.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.dialog {
  width: 420px;
  max-width: 92vw;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dialog h3 {
  margin-bottom: 6px;
}

.dialog label {
  font-size: 13px;
  color: #666;
  margin-top: 4px;
}

.dialog input,
.dialog select,
.dialog textarea {
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
  outline: none;
  font-family: inherit;
}

.dialog-ops {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
}

.btn-ghost {
  background: #fff;
  color: #409eff;
  border: 1px solid #409eff;
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
