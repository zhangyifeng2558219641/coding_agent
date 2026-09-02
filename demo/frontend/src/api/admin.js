import request from './request'

// 管理端:全部商品(含下架)
export function getAdminProducts() {
  return request.get('/admin/products')
}

export function createProduct(data) {
  return request.post('/admin/products', data)
}

export function updateProduct(id, data) {
  return request.put(`/admin/products/${id}`, data)
}

export function updateProductStatus(id, status) {
  return request.put(`/admin/products/${id}/status`, { status })
}

// 管理端:数据看板统计
export function getAdminStats() {
  return request.get('/admin/stats')
}

// 管理端:全部订单 + 发货(可 status 筛选、keyword 按订单号/昵称/邮箱搜索、startDate/endDate 日期筛选)
export function getAdminOrders(status, keyword, startDate, endDate) {
  return request.get('/admin/orders', {
    params: {
      status: status || undefined,
      keyword: keyword || undefined,
      startDate: startDate || undefined,
      endDate: endDate || undefined
    }
  })
}

export function getAdminOrderDetail(id) {
  return request.get(`/admin/orders/${id}`)
}

export function shipOrder(id) {
  return request.put(`/admin/orders/${id}/ship`)
}

// 管理端:用户列表 + 调整积分 + 查看任意用户积分明细
export function getUsers() {
  return request.get('/admin/users')
}

export function getUserPointRecords(id) {
  return request.get(`/admin/users/${id}/points`)
}

export function adjustUserPoints(id, points, remark) {
  return request.put(`/admin/users/${id}/points`, { points, remark })
}
