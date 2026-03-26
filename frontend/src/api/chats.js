import api from './client'

export const listChats = () => api.get('/chats')
export const createChat = (title = 'Новый чат') => api.post('/chats', { title })
export const renameChat = (id, title) => api.patch(`/chats/${id}`, { title })
export const deleteChat = (id) => api.delete(`/chats/${id}`)
