# Stack: Frontend (Vue / general)

- Use semantic HTML5.
- Prefer utility-first class naming in kebab-case.
- Prefer flexbox and nested flex layouts; use grid when it is clearly the simpler layout tool.
- Prefer gap and padding over margin for layout spacing.
- For interactive elements in app UIs, prefer stable `data-testid` values in kebab-case when the project uses Playwright or similar tooling.
- Vue 3 composition API with `<script setup lang="ts">`; props typed via `defineProps<{ ... }>()`; emits typed via `defineEmits<{ ... }>()`.
- CSS: scoped styles; CSS custom properties for theming; no inline styles except for dynamic values.
- State: Pinia (Vue); never component-to-component mutation through props drilling more than one level.
- HTTP client: **got** (typed, modern).
- Accessibility: ARIA only when semantic HTML cannot express the relationship; keyboard navigation for every interactive element; `prefers-reduced-motion` respected.
- SEO: See `09-design-guidelines.md` and rubrics S21-S24.
