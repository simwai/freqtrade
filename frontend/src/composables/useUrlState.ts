import { ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export interface UseUrlStateOptions<T> {
  key: string
  defaultValue: T
  parse: (value: string | null) => T
  serialize: (value: T) => string
  replace?: boolean
}

export function useUrlState<T>(options: UseUrlStateOptions<T>): Ref<T> {
  const route = useRoute()
  const router = useRouter()
  const replace = options.replace ?? true

  const raw = route.query[options.key]
  const initialValue = options.parse(typeof raw === 'string' ? raw : null)
  const value = ref<T>(initialValue)

  watch(
    value,
    (v) => {
      const serialized = options.serialize(v)
      if (route.query[options.key] === serialized) return
      if (replace) {
        router.replace({ query: { ...route.query, [options.key]: serialized } })
      } else {
        router.push({ query: { ...route.query, [options.key]: serialized } })
      }
    },
    { deep: true }
  )

  watch(
    () => { const q = route.query[options.key]; return typeof q === 'string' ? q : undefined },
    (q) => {
      const parsed = options.parse(q ?? null)
      if (parsed !== value.value) {
        value.value = parsed
      }
    }
  )

  return value as Ref<T>
}
