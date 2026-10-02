# 09-design-guidelines

Design Guidelines — owned by BabaDesigner. Loaded when BabaDesigner is active. Frontend work should route through DESIGN_PLAN before implementation so UI choices are decided in one place, not invented during PATCH.

Greenfield projects adopt these as binding conventions; existing projects apply them through `STYLE_POLICY.md` (`preserve-local` or `upgrade-house-style`). Override per project via the `Stack/Style:` field or `STYLE_POLICY.md`. Accessibility and SEO rules are governed by the existing rubric IDs `S21`-`S24`; this section does not duplicate them.

## Palettes

Preferred palettes: **Catppuccin Mocha** and **Dracula**. Choose one palette per project; do not mix palettes within a single interface. Palette selection is recorded in `STYLE_POLICY.md` or the `Stack/Style:` field.

## CSS variables

Define theme tokens as CSS custom properties on `:root`:

- `--color-*` for foreground, background, border, and accent colors
- `--font-*` for font families, sizes, and weights
- `--spacing-*` for consistent spacing scale
- `--radius-*` for border radius
- `--shadow-*` for elevation and depth

Require dark/light switching via a `.dark` class or `prefers-color-scheme`. Forbid hard-coded theme colors in component styles; always reference the CSS variable instead.

## Typography

Preferred font stacks:

- **Headings**: Montserrat
- **Body**: Inter, Onest, or Roboto
- **Terminal / code**: Consolas, Cascadia Code, or Fira Code

Require `font-display: swap` on all web font loads. Forbid custom font files unless explicitly approved in the `Stack/Style:` field.

## Iconography

Preferred icon sets by stack:

- **Web frontend**: Lucide
- **Vue component libraries**: Nuxt UI icons
- **React component libraries**: Radix Icons
- **Pine Script / terminal UIs**: Unicode symbols only

Require `aria-hidden="true"` on decorative icons and accessible names on meaningful icons. Forbid icon fonts.

## Component libraries

Preferred component libraries by stack:

- **Vue**: Nuxt UI
- **React**: Radix UI

The chosen library must support the project's palette, typography, and motion rules. Forbid mixing multiple component libraries in one project without explicit rationale.

## Cards

Cards are the default grouping primitive for dashboards, settings pages, and content feeds.

- One card per concern.
- Consistent padding and radius via CSS variables.
- Shadow and elevation via CSS variable token.
- Use cards for grouping related actions, content, or navigation.
- Avoid card nesting deeper than two levels without explicit rationale.

## Gradients

At most one gradient per viewport or major section. Use gradients for background, accent, or CTA only. Forbid stacked or multi-gradient backgrounds and gradient text unless explicitly approved. Require accessible contrast on gradient-to-text transitions.

## Motion and animations

Animation is optional. When used, keep it purposeful and tied to user action or state change.

Common pitfalls:

- Over-animating: too many animations competing for attention
- Animating properties that trigger layout or paint
- Forgetting `prefers-reduced-motion`
- Using motion to hide slow performance

Tips:

- Animate `transform` and `opacity` only
- Keep durations short
- Use easing that feels physical
- Test with reduced motion enabled
- Reserve motion for emphasis and feedback, not decoration

## Decorative backgrounds

Approved element types: subtle grids, abstract shapes, low-opacity doodles, wave dividers, grain or noise texture.

Performance rules:

- CSS-only preferred
- SVG for vector shapes
- Canvas only when necessary
- Keep asset count low

Placement rules:

- Background only
- Never over readable content
- Respect content contrast

Motion rules:

- Static by default
- Animation only if it respects `prefers-reduced-motion`

Anti-patterns:

- Full-page busy backgrounds
- Animated backgrounds over text
- Heavy particle systems
- Decorative elements that compete with CTAs

Decorative layers must never interfere with readability or a11y contrast.

## Hero sections

Every top-level page must have a hero section. The hero must include one unique visual or interactive element not repeated elsewhere on the page. The hero is the only approved location for the single allowed gradient and the single allowed subtle animation. The hero must establish the page's purpose in under 3 seconds.

## Input preservation

Never lose user input by default. Preserve form values, selections, and scroll position across navigation and re-renders.

Explicit exception: search fields may clear input after submission when the UX pattern requires it for fast repeated searches. Document any exception in the component's docstring or comment.

Temporary user state not yet committed to backend storage must be persisted in `localStorage`. Scope: draft form values, unsaved selections, in-progress multi-step flows, and transient UI preferences. Exclusions: never store secrets, tokens, passwords, or sensitive PII in `localStorage`. Require a clear expiration or cleanup strategy when the state is no longer relevant. Document the storage key naming convention in the component or feature README.

## Bring your own

This section provides defaults, not immutable laws. Projects with established design systems keep their local conventions under `preserve-local`. When `upgrade-house-style` is selected, the plan's `Conventions:` field names the specific design rules being applied.

## Design principles

Use these questions as a first filter for any UI:

- **Purpose**: What is this screen for, and does the design serve it?
- **Agency**: Can people explore, skip, and recover from mistakes?
- **Responsibility**: Are permissions, data use, and intent transparent?
- **Familiarity**: Do patterns match the platform and stay consistent?
- **Flexibility**: Does it work across sizes, inputs, text sizes, and abilities?
- **Simplicity**: Has every element earned its place?
- **Craft**: Spacing, alignment, wording, animation: is it finished?
- **Delight**: Is there a feeling here, and is it the right one? Don't mistake delight for decoration.

## Design review lenses

Review UI changes through these five lenses, in order:

1. **Accessibility** - text scales, contrast meets minimums, controls are reachable, nothing is color-only, motion is optional
2. **Platform conventions** - navigation matches platform patterns, actions live in the right places, search is discoverable, sheets/modals have clear exits
3. **Visual design and craft** - color has role, typography has scale, alignment is consistent, icons share one language, motion is purposeful
4. **Interaction** - loading states appear immediately, feedback lives in the interface, destructive actions warn and allow undo, modals have obvious exits
5. **Content and writing** - labels say what happens, capitalization is consistent, errors say what went wrong and how to fix it, names come from user vocabulary

## Craft checks

Before approving a design, ask:

- **Does it have a point of view?** Name the one thing this design would be remembered by. If nothing stands out, note it.
- **Is it a template?** A palette, type pairing, or layout that arrives with no reason rooted in the product is a default, not a choice.
- **Does the typography carry personality**, or is it a neutral delivery vehicle? System type is right for navigation and controls; brand can live in display text, content, and moments.
- **Does structure encode information?** Numbering, eyebrows, dividers, and labels should say something true about the content.
- **Is the boldness spent in one place?** One signature element, everything around it quiet.
- **Remove one accessory.** Ask what can go without loss. If nothing can, say the design is already lean.

The tension between "feels at home on the platform" and "couldn't be mistaken for anyone else" is real. Resolve it by keeping system components for navigation and controls, and letting identity live in color, type, imagery, tone of voice, and a few defining moments.
