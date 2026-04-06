import api from './client'

export const submitFeedback = (messageId, feedbackType) =>
  api.post(`/messages/${messageId}/feedback`, { feedback_type: feedbackType })

export const removeFeedback = (messageId) =>
  api.delete(`/messages/${messageId}/feedback`)
