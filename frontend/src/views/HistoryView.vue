<template>
  <div>
    <h2>History</h2>
    <div v-if="store.loading">Loading...</div>
    <div v-else>
      <select v-model="strategy">
        <option v-for="name in names" :key="name" :value="name">{{ name }}</option>
      </select>
      <VChart :option="histOption" autoresize  style="height:400px" />
    </div>
  </div>
</template>
<script setup lang='ts'>
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { useDashboardStore } from '../stores/dashboard'
import type { ECOption } from '../utils/echarts'
import '../utils/echarts'
const store = useDashboardStore()
const strategy = ref('')
const names = computed(() => Object.keys(store.history))
const series = computed(() => store.history[strategy.value] || { dates: [], profit: [] })
const histOption = computed((): ECOption => ({
  xAxis: { type: 'category', data: series.value.dates },
  yAxis: { type: 'value' },
  series: [{ type: 'line', data: series.value.profit }]
}))
onMounted(async () => {
  await store.fetchAll()
  if (strategy.value == '') {
    if (names.value.length) {
      strategy.value = names.value[0]
    }
  }
})
</script>
