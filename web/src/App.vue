<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'

const route = useRoute()
const auth = useAuth()
const app = useApp()

// Layout mode follows the route's role; public pages use the visitor's session if there is one.
const mode = computed<'officer' | 'owner' | 'public'>(() => {
  if (route.meta.role) return route.meta.role
  if (route.path === '/login' || route.path === '/kit') return 'public'
  return auth.role ?? 'public'
})
const nav = computed(() => mode.value !== 'public' && route.path !== '/login')

onMounted(() => app.loadVersion())

watch(
  () => [auth.role, auth.loggedIn] as const,
  ([role, logged]) => {
    if (logged && role === 'officer') {
      app.loadLlm()
      app.loadOfficerCounts()
    }
    if (logged && role === 'owner') app.loadOwner()
  },
  { immediate: true },
)
</script>

<template>
  <AppLayout :mode="mode" :nav="nav">
    <RouterView v-slot="{ Component, route: r }">
      <component :is="Component" :key="r.path" />
    </RouterView>
  </AppLayout>
</template>
