import request from './request'

// 商品列表(仅上架),params: { category, keyword, sort, order }
export function getProducts(params) {
  return request.get('/products', { params })
}

export function getCategories() {
  return request.get('/products/categories')
}

export function getProduct(id) {
  return request.get(`/products/${id}`)
}

// 商品评价列表
export function getProductReviews(id) {
  return request.get(`/products/${id}/reviews`)
}
