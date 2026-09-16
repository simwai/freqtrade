<template>
  <div id="app">
    <header>
      <div class="logo">
        <span class="dot"></span>
        <h1>Strategy Lab — Dashboard</h1>
      </div>
      <span class="sub" v-if="stale">Stale</span>
      <span class="sub" v-else-if="builtAt">built {{ builtAt }}</span>
      <JobsModal />
      <UButton color="neutral" variant="ghost" size="sm" @click="manualRefresh">Refresh</UButton>
    </header>

    <nav class="tabs">
      <router-link
        v-for="tab in tabs"
        :key="tab.path"
        :to="tab.path"
        class="tab-btn"
        :class="{ active: currentRoute === tab.path }"
      >{{ tab.label }}</router-link>
    </nav>

    <main>
      <router-view />
    </main>

    <Toaster />
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { checkFreshness, triggerRefresh, startFreshnessLoop, onVisible } from './utils/freshness'
import JobsModal from './components/JobsModal.vue'
import { useToast } from '@nuxt/ui/composables/useToast'

const route = useRoute()
const toast = useToast()
const stale = ref(false)
const builtAt = ref('')
const currentRoute = computed(() => route.path)

const tabs = [
  { path: '/dashboard', label: 'Dashboard' },
  { path: '/strategies', label: 'Strategies' },
  { path: '/benchmark', label: 'Benchmark' },
  { path: '/lab', label: 'Lab' },
  { path: '/hyperopt', label: 'Hyperopt' },
  { path: '/walkforward', label: 'WalkForward' },
  { path: '/history', label: 'History' },
  { path: '/trades', label: 'Trades' },
  { path: '/dryrun', label: 'DryRun' },
]

async function refreshFresh() {
  try {
    const d = await checkFreshness()
    stale.value = !!(d && d.stale)
    builtAt.value = (d && d.built) || ''
    if (d && d.stale) await triggerRefresh()
  } catch (e) {}
}
async function manualRefresh() {
  try {
    await triggerRefresh()
    await refreshFresh()
    toast.add({ title: 'Refreshed', description: 'Data refreshed successfully.', color: 'success', duration: 2000 })
  } catch (e) {
    toast.add({ title: 'Refresh failed', description: 'Could not refresh data.', color: 'error', duration: 3000 })
  }
}
onMounted(() => {
  refreshFresh()
  startFreshnessLoop(() => { triggerRefresh() })
  onVisible(() => { refreshFresh() })
})
onUnmounted(() => {})
</script>