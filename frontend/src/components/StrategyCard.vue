<template>
  <div>
    <span>{{ strategy.name }}</span>
    <span>{{ strategy.grade }}</span>
    <span>Trades: {{ strategy.trades }}</span>
  </div>
</template>
<script setup lang='ts'>
defineProps<{ strategy: any }>()
function gradeColor(grade: string) {
  const colors: Record<string, string> = { A: 'green', B: 'blue', C: 'yellow', D: 'orange', F: 'red' }
  return colors[grade] || 'gray'
}
</script>
