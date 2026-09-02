import request from './request'

// 修改个人资料(昵称/手机号)
export function updateProfile(payload) {
  return request.put('/users/profile', payload)
}

// 修改密码(需原密码)
export function changePassword(payload) {
  return request.put('/users/password', payload)
}
