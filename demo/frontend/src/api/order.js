import request from './request'

// 用户订单
export function createOrder(payload) {
  return request.post('/orders', payload)
}

export function getMyOrders(status) {
  return request.get('/orders', { params: status ? { status } : {} })
}

export function getOrderDetail(id) {
  return request.get(`/orders/${id}`)
}

export function payOrder(id) {
  return request.post(`/orders/${id}/pay`)
}

export function cancelOrder(id) {
  return request.post(`/orders/${id}/cancel`)
}

export function confirmOrder(id) {
  return request.post(`/orders/${id}/confirm`)
}

export function reviewOrder(id, payload) {
  return request.post(`/orders/${id}/review`, payload)
}

// 我的积分流水
export function getPointRecords() {
  return request.get('/points')
}
