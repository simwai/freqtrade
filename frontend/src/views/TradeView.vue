<template>
  <section>
    <div class="section-head">
      <h2>Trades</h2>
    </div>

    <div v-if="store.loading" class="card">Loading...</div>
    <div v-else class="card">
      <div class="table-wrap table-stack">
        <div class="thead-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col" v-on:click="sortBy('strategy')">Strategy <span class="arrow" v-if="sortKey==='strategy'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('source')">Source <span class="arrow" v-if="sortKey==='source'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th scope="col" v-on:click="sortBy('n_trades')" class="num">Trades <span class="arrow" v-if="sortKey==='n_trades'">{{ sortAsc ? '▲' : '▼' }}</span></th>
                <th>File</th>
              </tr>
            </thead>
          </table>
        </div>
        <div class="table-wrap" ref="tradesTableWrap">
          <table>
            <tbody>
              <tr v-for="r in sortedRuns" :key="r.key">
                <td><router-link :to="'/trades/' + r.key">{{ r.strategy }}</router-link></td>
                <td>{{ r.source }}</td>
                <td class="num">{{ r.n_trades }}</td>
                <td><a :href="'/trades/' + r.key + '.json'" target="_blank">JSON</a></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const store = useDashboardStore()
const sortKey = ref('strategy')
const sortAsc = ref(true)
const tradesTableWrap = ref<HTMLElement | null>(null)

const sortedRuns = computed(() => {
  const arr = [...store.trade_runs]
  arr.sort((a: any, b: any) => {
    let av = a[sortKey.value]
    let bv = b[sortKey.value]
    if (av === undefined && bv === undefined) return 0
    if (av === '' || av === undefined || av === null) return sortAsc.value ? 1 : -1
    if (bv === '' || bv === undefined || bv === null) return sortAsc.value ? -1 : 1
    const an = Number(av), bn = Number(bv)
    const useNum = !isNaN(an) && !isNaN(bn)
    const r = useNum ? an - bn : String(av).localeCompare(String(bv))
    return sortAsc.value ? r : -r
  })
  return arr
})

function sortBy(key: string) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = true }
}

onMounted(async () => {
  await store.fetchAll()
  await nextTick()
  if (tradesTableWrap.value) {
    tradesTableWrap.value.addEventListener('scroll', () => {
      const tw = tradesTableWrap.value!
      tw.classList.toggle('scroll-left', tw.scrollLeft > 0)
      tw.classList.toggle('scroll-right', tw.scrollLeft + tw.clientWidth < tw.scrollWidth - 1)
    })
  }
})
</script>