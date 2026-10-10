import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getAuth, login as clientLogin, logout as clientLogout, onAuthChange, register as clientRegister, type RegisterPayload, type Role } from '@/api/client'

export const useAuth = defineStore('auth', () => {
  const state = ref(getAuth())
  onAuthChange((a) => (state.value = a))

  const role = computed<Role | null>(() => state.value?.role ?? null)
  const loggedIn = computed(() => !!state.value?.access)
  const name = computed(() => state.value?.name || '')
  const initials = computed(() => {
    const n = name.value.split('@')[0].replace(/[._-]+/g, ' ').trim()
    if (!n) return role.value === 'owner' ? 'OW' : 'OF'
    const parts = n.split(/\s+/)
    return ((parts[0]?.[0] || '') + (parts[1]?.[0] || parts[0]?.[1] || '')).toUpperCase()
  })

  async function login(email: string, password: string) {
    await clientLogin(email, password)
  }
  async function register(p: RegisterPayload) {
    await clientRegister(p)
  }
  function logout() {
    clientLogout()
  }

  return { state, role, loggedIn, name, initials, login, register, logout }
})
