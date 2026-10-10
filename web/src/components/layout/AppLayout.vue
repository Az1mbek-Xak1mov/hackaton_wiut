<script setup lang="ts">
import PrototypeStrip from './PrototypeStrip.vue'
import TopBar from './TopBar.vue'
import SideNav from './SideNav.vue'
import AppFooter from './AppFooter.vue'

defineProps<{ mode: 'officer' | 'owner' | 'public'; nav: boolean }>()
</script>

<template>
  <div class="shell">
    <PrototypeStrip />
    <TopBar :mode="mode" />
    <div class="body">
      <SideNav v-if="nav && mode !== 'public'" :mode="mode as 'officer' | 'owner'" />
      <main class="main" :class="mode === 'officer' ? 'officer' : 'owner'">
        <slot />
        <AppFooter />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell { min-height: 100vh; display: flex; flex-direction: column; }
.body { display: flex; flex-wrap: wrap; flex: 1; align-items: stretch; }
.main { flex: 999 1 560px; min-width: 0; padding: 24px 28px 32px; display: flex; flex-direction: column; }
.main.officer { padding: 20px 24px 32px; font-size: 13px; }
@media (max-width: 720px) { .main, .main.officer { padding: 16px 16px 28px; } }
</style>
