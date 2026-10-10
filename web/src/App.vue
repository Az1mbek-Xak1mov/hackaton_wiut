<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import { useAuth } from '@/stores/auth'
import { useApp } from '@/stores/app'
import { surface } from '@/surface'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const app = useApp()

// The surface (hostname) decides the app; the session only decides whether navigation is shown.
const mode = computed<'officer' | 'owner' | 'public'>(() => (surface === 'bank' ? 'officer' : auth.loggedIn ? 'owner' : 'public'))
const nav = computed(() => auth.loggedIn && !route.meta.bare)

onMounted(() => app.loadVersion())

watch(
  () => auth.loggedIn,
  (logged) => {
    if (logged && surface === 'bank') {
      app.loadLlm()
      app.loadOfficerCounts()
    }
    if (logged && surface === 'owner') app.loadOwner()
    if (!logged && route.meta.auth) router.push({ path: '/login', query: { next: route.fullPath } })
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
