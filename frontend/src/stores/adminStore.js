import { create } from 'zustand'

export const useAdminStore = create((set) => ({
  token: localStorage.getItem('admin_token') || '',
  setToken: (token) => {
    localStorage.setItem('admin_token', token)
    set({ token })
  },
}))
