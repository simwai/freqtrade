<template>
  <div v-on:click="close"></div>
  <div>
    <button v-on:click="close">Close</button>
    <h2>{{ strategy.strategy }}</h2>
    <div>Grade: {{ strategy.score.grade }}</div>
    <table>
      <tr v-for="(g, k) in strategy.score.grades" :key="k">
        <td>{{ k }}</td><td>{{ g }}</td>
      </tr>
    </table>
    <h3>Recent runs</h3>
    <ul>
      <li v-for="r in runs" :key="r.source">{{ r.source }} {{ r.profit_total }}</li>
    </ul>
  </div>
</template>
<script setup lang='ts'>
import { computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
const props = defineProps<{ name: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const store = useDashboardStore()
const strategy = computed(() => store.canonical.find((s: any) => s.strategy === props.name) || { strategy: props.name, score: { grade: '?', grades: {} } })
const runs = computed(() => store.backtests.filter((b: any) => b.strategy === props.name).slice(0, 10))
function close() {
  emit('close')
}
</script>
