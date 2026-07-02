import { create } from 'zustand'

// JWT + 当前用户 + 当前组织；持久化到 localStorage
export const useAuthStore = create((set, get) => ({
  accessToken: localStorage.getItem('access_token') || '',
  refreshToken: localStorage.getItem('refresh_token') || '',
  user: null,
  orgs: [],
  currentOrgId: Number(localStorage.getItem('current_org_id')) || null,

  setTokens: ({ access_token, refresh_token }) => {
    localStorage.setItem('access_token', access_token)
    localStorage.setItem('refresh_token', refresh_token)
    set({ accessToken: access_token, refreshToken: refresh_token })
  },

  setUser: (user) => set({ user }),

  setOrgs: (orgs) => {
    let cur = get().currentOrgId
    if (!cur || !orgs.find((o) => o.id === cur)) {
      cur = orgs[0]?.id ?? null
      if (cur) localStorage.setItem('current_org_id', String(cur))
    }
    set({ orgs, currentOrgId: cur })
  },

  setCurrentOrg: (id) => {
    localStorage.setItem('current_org_id', String(id))
    set({ currentOrgId: id })
  },

  currentOrg: () => get().orgs.find((o) => o.id === get().currentOrgId) || null,

  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('current_org_id')
    set({ accessToken: '', refreshToken: '', user: null, orgs: [], currentOrgId: null })
  },

  isAuthed: () => !!get().accessToken,
}))
