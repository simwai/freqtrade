import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
import { sortableTable, syncScrollStack } from './utils/sortable'
app.directive('sortable', { mounted(el: any) { if (el.tagName === 'TABLE') sortableTable(el) }, updated(el: any) { if (el.tagName === 'TABLE') sortableTable(el) } })
app.directive('sync-scroll', {
  mounted(el: any) { syncScrollStack(el) },
  updated(el: any) { syncScrollStack(el) }
})
app.mount('#app')
