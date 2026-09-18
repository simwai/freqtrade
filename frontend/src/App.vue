<template>
  <UApp>
    <div id="app" class="layout font-sans">
      <!-- Professional Header -->
      <header class="layout-header panel border-panel" style="background: var(--color-bg-elevated);">
        <div class="flex items-center justify-between gap-4 px-4 py-2.5">
          <!-- Brand -->
          <div class="flex items-center gap-3 flex-shrink-0">
            <div class="w-8 h-8 rounded-sm bg-accent flex items-center justify-center" style="background: linear-gradient(135deg, var(--color-accent) 0%, #1e6be8 100%);">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-white">
                <path d="M18 20V10M12 20V4M6 20v-6"/>
              </svg>
            </div>
            <div>
              <h1 class="text-lg font-semibold tracking-tight text-text">Strategy Lab</h1>
              <span class="text-xs text-muted">Institutional Research Platform</span>
            </div>
          </div>

          <!-- Global Status Bar -->
          <div class="flex items-center gap-4 flex-1 justify-center max-w-md">
            <div class="status-dot status-dot-active" :class="stale ? 'status-dot-warning' : ''">
              <span v-if="stale">Data Stale</span>
              <span v-else-if="builtAt">Updated {{ builtAt }}</span>
              <span v-else>Live</span>
            </div>
            <div class="hidden sm:flex items-center gap-2 text-xs text-muted px-3 py-1.5 rounded-pill bg-panel border border-panel-border">
              <span id="clock" class="font-mono tabular-nums"></span>
              <span class="text-faint">UTC</span>
            </div>
          </div>

          <!-- Actions -->
          <div class="flex items-center gap-2 flex-shrink-0">
            <JobsModal />
            <button 
              class="btn btn-ghost btn-sm btn-icon" 
              @click="manualRefresh"
              :disabled="refreshing"
              title="Refresh data"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ 'animate-spin': refreshing }">
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
          </div>
        </div>
      </header>

      <!-- Navigation Tabs -->
      <nav class="layout-header panel border-panel" style="background: var(--color-panel); border-top: none;">
        <div class="tabs-container overflow-x-auto scrollbar-hide" ref="tabsNav" style="-webkit-overflow-scrolling: touch;">
          <div class="tabs-inner flex gap-1 px-4 py-1.5 min-w-max">
            <router-link
              v-for="tab in tabs"
              :key="tab.path"
              :to="tab.path"
              class="nav-tab px-4 py-2 rounded-md text-sm font-medium text-muted transition-all duration-120 whitespace-nowrap"
              :class="{
                'text-text bg-elevated border border-panel-border': currentRoute === tab.path,
                'hover:text-text hover:bg-hover': currentRoute !== tab.path
              }"
            >{{ tab.label }}</router-link>
          </div>
        </div>
        <!-- Scroll indicator -->
        <div class="scroll-fade-right absolute right-0 top-0 bottom-0 w-8 pointer-events-none" 
             v-if="showScrollIndicator"
             style="background: linear-gradient(to right, transparent, var(--color-panel)); z-index: 10;"></div>
      </nav>

      <!-- Main Content -->
      <main class="layout-main" style="max-width: 100%;">
        <div class="w-full max-w-[1920px] mx-auto px-4 py-4">
          <router-view v-slot="{ Component }">
            <component :is="Component" />
          </router-view>
        </div>
      </main>

      <!-- Footer Status Bar -->
      <footer class="layout-footer panel border-panel border-t" style="background: var(--color-bg-elevated);">
        <div class="flex items-center justify-between px-4 py-1.5 text-xs text-faint">
          <span>Freqtrade Strategy Lab</span>
          <span class="flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-status-active"></span>
            <span>Connected</span>
          </span>
        </div>
      </footer>
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
const refreshing = ref(false)
const clock = ref('')

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
  { path: '/dryrun', label: 'Dry Run' },
]

function formatTime(date: Date): string {
  return date.toISOString().slice(11, 19)
}

async function refreshFresh() {
  try {
    const d = await checkFreshness()
    stale.value = !!(d && d.stale)
    builtAt.value = (d && d.built) || ''
  } catch (e) {}
}

async function manualRefresh() {
  refreshing.value = true
  try {
    await triggerRefresh()
    await refreshFresh()
    // Status shown inline in header instead of toast
  } catch (e) {
    // Error shown inline
  } finally {
    refreshing.value = false
  }
}

function checkScroll() {
  if (!tabsNav.value) return
  const { scrollLeft, scrollWidth, clientWidth } = tabsNav.value
  showScrollIndicator.value = scrollWidth > clientWidth && scrollLeft + clientWidth < scrollWidth - 4
}

function updateClock() {
  clock.value = formatTime(new Date())
}

onMounted(() => {
  refreshFresh()
  startFreshnessLoop(() => { stale.value = true })
  onVisible(() => { refreshFresh() })
  
  updateClock()
  setInterval(updateClock, 1000)
  
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
/* Scrollbar hide utility */
.scrollbar-hide::-webkit-scrollbar { display: none; }
.scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }

/* Tabs container */
.tabs-container { position: relative; }
.tabs-inner { display: flex; gap: 4px; }

/* Nav tabs - professional */
.nav-tab {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
  text-decoration: none;
}
.nav-tab:hover { color: var(--color-text); background: var(--color-bg-hover); }
.nav-tab.active { 
  color: var(--color-text); 
  background: var(--color-bg-elevated); 
  border-color: var(--color-panel-border);
}

/* Scroll fade indicator */
.scroll-fade-right {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 48px;
  pointer-events: none;
  background: linear-gradient(to right, transparent, var(--color-panel));
  z-index: 10;
}

/* Clock */
#clock { font-variant-numeric: tabular-nums; }

/* Animations */
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.animate-spin { animation: spin 1s linear infinite; }

/* Responsive */
@media (max-width: 1024px) {
  .tabs-inner { padding: 0.5rem 0.75rem; }
  .nav-tab { padding: 6px 10px; font-size: var(--text-xs); }
}

@media (max-width: 768px) {
  header .flex { padding: 0.75rem 1rem; }
  h1 { font-size: 1rem; }
  .hidden.sm\\:flex { display: none !important; }
  .tabs-inner { padding: 0.375rem 0.5rem; }
  .nav-tab { padding: 5px 8px; font-size: 11px; }
}

@media (max-width: 480px) {
  .nav-tab { padding: 4px 6px; font-size: 10px; }
}
</style>