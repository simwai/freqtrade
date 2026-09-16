<template>
  <div>
    <span>{{ strategy.name }}</span>
    <span>{{ strategy.grade }}</span>
    <span>Trades: {{ strategy.trades }}</span>
  </div>
</template>
<script setup lang="ts">
defineProps<{ strategy: any }>()
</script>
