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
    </nav>
    <router-view />
  </div>
</template>
<script setup lang='ts'>
</script>