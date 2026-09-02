import request from './request'

// 注册
export function register(data) {
  return request.post('/auth/register', data)
}

// 登录
export function login(data) {
  return request.post('/auth/login', data)
}

// 获取当前登录用户
export function getMe() {
  return request.get('/auth/me')
}
