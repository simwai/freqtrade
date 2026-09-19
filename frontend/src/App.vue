<template>
  <UApp>
    <div id="app" class="flex flex-col min-h-screen bg-bg">
      <!-- Header -->
      <header class="flex items-center gap-3 px-6 py-3.5 bg-bg-soft border-b border-border flex-wrap">
        <div class="logo flex items-center gap-3">
          <span class="dot w-3 h-3 rounded-full bg-lavender-deep shadow-[0_0_12px_var(--color-lavender)]" />
          <h1 class="text-base font-semibold tracking-wide">Strategy Lab — Dashboard</h1>
        </div>
        <span v-if="stale" class="text-text-faint text-xs">Stale</span>
        <span v-else-if="builtAt" class="text-text-faint text-xs">built {{ builtAt }}</span>
        <UButton color="neutral" variant="ghost" size="sm" @click="manualRefresh">Refresh</UButton>
      </header>

      <!-- Navigation Tabs -->
      <nav class="tabs overflow-x-auto snap-x scrollbar-hide" ref="tabsNav" style="-webkit-overflow-scrolling: touch;">
        <div class="tabs-inner flex gap-1 px-6 py-2.5 min-w-max snap-start">
          <router-link
            v-for="tab in tabs"
            :key="tab.path"
            :to="tab.path"
            class="tab-btn bg-transparent border border-transparent text-text-dim px-4 py-2 rounded-button text-sm font-medium cursor-pointer hover:text-lavender hover:bg-card-hover transition-colors"
            :class="{ 'bg-lavender-ink text-white': currentRoute === tab.path }"
          >{{ tab.label }}</router-link>
        </div>
        <div class="scroll-indicator fixed right-0 top-0 w-6 h-full bg-gradient-to-r from-transparent to-bg-soft pointer-events-none z-10" v-if="showScrollIndicator" />
      </nav>

      <!-- Main Content -->
      <main class="flex-1 w-full max-w-[1500px] mx-auto px-6 py-6">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>

      <!-- Jobs Modal Trigger (fixed top-right via component CSS) -->
      <JobsModal />
    </div>
  </UApp>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { checkFreshness, triggerRefresh, startFreshnessLoop, onVisible } from './utils/freshness'
import JobsModal from './components/JobsModal.vue'

const route = useRoute()
const stale = ref(false)
const builtAt = ref('')
const currentRoute = computed(() => route.path)
const tabsNav = ref<HTMLElement | null>(null)
const showScrollIndicator = ref(false)

const tabs = [
  { path: '/dashboard', label: 'Dashboard' },
  { path: '/strategies', label: 'Strategies' },
  { path: '/benchmark', label: 'Benchmark' },
  { path: '/lab', label: 'Lab' },
  { path: '/backtest/history', label: 'Backtest History' },
  { path: '/analysis/recursive', label: 'Recursive Analysis' },
  { path: '/analysis/lookahead', label: 'Lookahead Analysis' },
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
  } catch (e) {}
}

async function manualRefresh() {
  try {
    await triggerRefresh()
    await refreshFresh()
  } catch (e) {
    // error suppressed
  }
}

function checkScroll() {
  if (!tabsNav.value) return
  const { scrollLeft, scrollWidth, clientWidth } = tabsNav.value
  showScrollIndicator.value = scrollWidth > clientWidth && scrollLeft + clientWidth < scrollWidth - 4
}

onMounted(() => {
  refreshFresh()
  startFreshnessLoop(() => { stale.value = true })
  onVisible(() => { refreshFresh() })
  const nav = tabsNav.value
  if (nav) {
    nav.addEventListener('scroll', checkScroll)
    window.addEventListener('resize', checkScroll)
    checkScroll()
  }
})

onUnmounted(() => {
  const nav = tabsNav.value
  if (nav) {
    nav.removeEventListener('scroll', checkScroll)
    window.removeEventListener('resize', checkScroll)
  }
})
</script>

<style scoped>
.tabs::-webkit-scrollbar { display: none; }
.tabs { scrollbar-width: none; -ms-overflow-style: none; }
.tabs-inner { display: flex; gap: 4px; }
.scroll-indicator {
  position: sticky;
  right: 0;
  top: 0;
  width: 24px;
  height: 100%;
  background: linear-gradient(to right, transparent, var(--color-bg-soft));
  pointer-events: none;
  z-index: 10;
}

@media (max-width: 768px) {
  header { flex-wrap: wrap; gap: 8px; }
  header h1 { font-size: 1rem; }
  .tabs-inner { padding: 0.5rem 0.625rem; }
  .tab-btn { padding: 0.375rem 0.625rem; font-size: 0.75rem; }
}
@media (max-width: 480px) {
  .tab-btn { padding: 0.3125rem 0.5rem; font-size: 0.6875rem; }
}
</style>
