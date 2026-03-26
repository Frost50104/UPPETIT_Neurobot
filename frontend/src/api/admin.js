import api from './client'

// Users
export const listUsers = () => api.get('/admin/users')
export const createUser = (data) => api.post('/admin/users', data)
export const updateUser = (id, data) => api.patch(`/admin/users/${id}`, data)
export const resetPassword = (id) => api.post(`/admin/users/${id}/reset-password`)
export const deleteUser = (id) => api.delete(`/admin/users/${id}`)

// Knowledge Base
export const getKBStatus = () => api.get('/admin/kb/status')
export const refreshKB = () => api.post('/admin/kb/refresh')
export const getKBHistory = () => api.get('/admin/kb/history')
export const deleteKBHistory = (id) => api.delete(`/admin/kb/history/${id}`)

// Benchmark
export const startBenchmark = () => api.post('/admin/kb/benchmark')
export const getBenchmarkStatus = () => api.get('/admin/kb/benchmark/status')
