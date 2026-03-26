import api from './client'

export const listMessages = (chatId) => api.get(`/chats/${chatId}/messages`)
export const askQuestion = (chatId, question) =>
  api.post(`/chats/${chatId}/messages`, { question })
export const getKbStatus = () => api.get('/kb-status')
