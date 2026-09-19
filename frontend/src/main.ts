import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import ui from '@nuxt/ui/vue-plugin'
import ColumnToggle from './components/ColumnToggle.vue'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ui)
app.component('ColumnToggle', ColumnToggle)
import { sortableTable, syncScrollStack } from './utils/sortable'
app.directive('sortable', { mounted(el: HTMLTableElement) { if (el.tagName === 'TABLE') sortableTable(el) }, updated(el: HTMLTableElement) { if (el.tagName === 'TABLE') sortableTable(el) } })
app.directive('sync-scroll', {
  mounted(el: HTMLElement) { syncScrollStack(el) },
  updated(el: HTMLElement) { syncScrollStack(el) }
})
app.mount('#app')
