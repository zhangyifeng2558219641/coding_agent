import request from './request'

export function getCart() {
  return request.get('/cart')
}

export function addToCart(productId, quantity = 1) {
  return request.post('/cart', { productId, quantity })
}

export function updateCartItem(cartItemId, quantity) {
  return request.put(`/cart/${cartItemId}`, { quantity })
}

export function removeCartItem(cartItemId) {
  return request.delete(`/cart/${cartItemId}`)
}

export function clearCart() {
  return request.delete('/cart')
}
