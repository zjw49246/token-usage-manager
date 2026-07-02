import axios from 'axios'
import { useAuthStore } from '../stores/authStore.js'

const api = axios.create({ baseURL: '/' })

// 注入 JWT access token
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token && !config._skipAuth) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

// 401 时用 refresh token 换新 access token 后重试一次
let refreshing = null
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const { response, config } = error
    if (response?.status === 401 && config && !config._retry && !config._skipAuth) {
      const { refreshToken, setTokens, logout } = useAuthStore.getState()
      if (!refreshToken) { logout(); return Promise.reject(error) }
      try {
        refreshing = refreshing || axios.post('/auth/refresh', { refresh_token: refreshToken })
        const { data } = await refreshing
        refreshing = null
        setTokens(data)
        config._retry = true
        config.headers['Authorization'] = `Bearer ${data.access_token}`
        return api(config)
      } catch (e) {
        refreshing = null
        logout()
        return Promise.reject(e)
      }
    }
    return Promise.reject(error)
  }
)

// ── Auth ──
export const register = (data) => api.post('/auth/register', data, { _skipAuth: true }).then(r => r.data)
export const login = (data) => api.post('/auth/login', data, { _skipAuth: true }).then(r => r.data)
export const fetchMe = () => api.get('/auth/me').then(r => r.data)

// ── Orgs ──
export const listOrgs = () => api.get('/orgs').then(r => r.data)
export const createOrg = (data) => api.post('/orgs', data).then(r => r.data)
export const listMembers = (orgId) => api.get(`/orgs/${orgId}/members`).then(r => r.data)
export const addMember = (orgId, data) => api.post(`/orgs/${orgId}/members`, data).then(r => r.data)
export const updateMemberRole = (orgId, userId, data) => api.patch(`/orgs/${orgId}/members/${userId}`, data).then(r => r.data)
export const removeMember = (orgId, userId) => api.delete(`/orgs/${orgId}/members/${userId}`)

// ── Keys (org 隔离) ──
export const listKeys = (orgId) => api.get(`/orgs/${orgId}/keys`).then(r => r.data)
export const getKey = (orgId, id) => api.get(`/orgs/${orgId}/keys/${id}`).then(r => r.data)
export const createKey = (orgId, data) => api.post(`/orgs/${orgId}/keys`, data).then(r => r.data)
export const updateKey = (orgId, id, data) => api.patch(`/orgs/${orgId}/keys/${id}`, data).then(r => r.data)
export const deleteKey = (orgId, id) => api.delete(`/orgs/${orgId}/keys/${id}`)
export const getKeyUsage = (orgId, id, params) => api.get(`/orgs/${orgId}/keys/${id}/usage`, { params }).then(r => r.data)

// ── Stats (org 隔离) ──
export const getOverview = (orgId) => api.get(`/orgs/${orgId}/stats/overview`).then(r => r.data)
export const getTrend = (orgId, params) => api.get(`/orgs/${orgId}/stats/trend`, { params }).then(r => r.data)
export const getKeyShares = (orgId) => api.get(`/orgs/${orgId}/stats/key-shares`).then(r => r.data)

// ── Credits / Billing ──
export const getCredits = (orgId) => api.get(`/orgs/${orgId}/credits`).then(r => r.data)
export const topupCredits = (orgId, data) => api.post(`/orgs/${orgId}/credits`, data).then(r => r.data)

// ── Catalog ──
export const listCatalogModels = (params) => api.get('/catalog/models', { params }).then(r => r.data)

export default api
