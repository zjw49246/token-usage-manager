import axios from 'axios'

const api = axios.create({ baseURL: '/' })

// 注入 admin token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

// Keys
export const listKeys = () => api.get('/admin/keys').then(r => r.data)
export const getKey = (id) => api.get(`/admin/keys/${id}`).then(r => r.data)
export const createKey = (data) => api.post('/admin/keys', data).then(r => r.data)
export const updateKey = (id, data) => api.patch(`/admin/keys/${id}`, data).then(r => r.data)
export const deleteKey = (id) => api.delete(`/admin/keys/${id}`)
export const getKeyUsage = (id, params) => api.get(`/admin/keys/${id}/usage`, { params }).then(r => r.data)

// Stats
export const getOverview = () => api.get('/admin/stats/overview').then(r => r.data)
export const getTrend = (params) => api.get('/admin/stats/trend', { params }).then(r => r.data)
export const getKeyShares = () => api.get('/admin/stats/key-shares').then(r => r.data)
