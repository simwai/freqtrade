<template>
  <div>
    <h3>Grade Tuner</h3>
    <label>Min Profit</label>
    <input type="number" :value="minProfit" v-on:input="onProfit($event)" />
    <label>Min Trades</label>
    <input type="number" :value="minTrades" v-on:input="onTrades($event)" />
  </div>
</template>
<script setup lang='ts'>
defineProps<{ minProfit: number, minTrades: number }>()
const emit = defineEmits<{ (e: 'update:minProfit', v: number): void, (e: 'update:minTrades', v: number): void }>()
function onProfit(ev: any) {
  emit('update:minProfit', Number(ev.target.value) || 0)
}
function onTrades(ev: any) {
  emit('update:minTrades', Number(ev.target.value) || 0)
}
</script>
