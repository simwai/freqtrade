<template>
  <div>
    <nav>
      <router-link to='/dashboard'>Dashboard</router-link>
      <router-link to='/strategies'>Strategies</router-link>
      <router-link to='/benchmark'>Benchmark</router-link>
      <router-link to='/lab'>Lab</router-link>
    </nav>
    <router-view />
  </div>
</template>
<script setup lang='ts'>
</script>