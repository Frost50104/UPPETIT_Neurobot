import api from './client'

export const login = (username, password) => api.post('/auth/login', { username, password })
export const logout = () => api.post('/auth/logout')
export const refreshToken = () => api.post('/auth/refresh')
export const changePassword = (current_password, new_password) =>
  api.post('/auth/change-password', { current_password, new_password })
export const getMe = () => api.get('/auth/me')
