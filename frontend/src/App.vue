<template>
  <div>
    <nav>
      <router-link to='/dashboard'>Dashboard</router-link>
      <router-link to='/strategies'>Strategies</router-link>
      <router-link to='/benchmark'>Benchmark</router-link>
      <router-link to='/lab'>Lab</router-link>
      <router-link to='/hyperopt'>Hyperopt</router-link>
      <router-link to='/walkforward'>WalkForward</router-link>
      <router-link to='/history'>History</router-link>
      <router-link to='/trades'>Trades</router-link>
      <router-link to='/dryrun'>DryRun</router-link>
    </nav>
    <span v-if="stale">Stale</span>
    <span v-else>built {{ builtAt }}</span>
    <button v-on:click="manualRefresh">Refresh</button>
    <router-view />
  </div>
</template>
<script setup lang='ts'>
import { ref, onMounted, onUnmounted } from 'vue'
import { checkFreshness, triggerRefresh, startFreshnessLoop, onVisible } from './utils/freshness'
const stale = ref(false)
const builtAt = ref('')
async function refreshFresh() {
  try {
    const d = await checkFreshness()
    stale.value = !!(d && d.stale)
    builtAt.value = (d && d.built) || ''
    if (d && d.stale) await triggerRefresh()
  } catch (e) {}
}
async function manualRefresh() {
  await triggerRefresh()
  await refreshFresh()
}
onMounted(() => {
  refreshFresh()
  startFreshnessLoop(() => { triggerRefresh() })
  onVisible(() => { refreshFresh() })
})
onUnmounted(() => {})
</script>
