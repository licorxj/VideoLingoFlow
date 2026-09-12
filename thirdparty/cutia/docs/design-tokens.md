# Design Tokens — CapCut-inspired UI

Last updated: 2026-09-11

The Cutia editor is styled through a single source of truth: CSS custom
properties defined in `apps/web/src/app/globals.css`. Every panel in the editor
(Timeline / Preview / Properties / Assets / Agent) and every UI primitive
(buttons, dropdowns, scrollbars, resizable handles) consumes these tokens
through Tailwind's `@theme inline` bridge.

## Brand direction

- **Visual reference**: CapCut Web — light airy surface, soft purple accent,
  generous rounded corners, panels "floating" on a quiet canvas.
- **Accent color**: `#7C3AED` (CapCut-style violet, hsl `252 80% 60%`).
- **Typography**: Inter for Latin, `PingFang SC` / `Noto Sans CJK SC` for CJK.
- **Light + dark** are both supported; light is the default for marketing and
  editor surfaces, dark uses slate-tinged neutrals (no pure black).

## Token map

| Token              | Light value               | Dark value                | Role                                |
| ------------------ | ------------------------- | ------------------------- | ----------------------------------- |
| `--background`     | `hsl(240 20% 98%)`        | `hsl(240 12% 9%)`         | Page / editor canvas                |
| `--foreground`     | `hsl(240 15% 12%)`        | `hsl(240 8% 92%)`         | Default text                        |
| `--card`           | `hsl(0 0% 100%)`          | `hsl(240 12% 12%)`        | Panel surface                       |
| `--primary`        | `#7C3AED`                 | `hsl(252 90% 70%)`        | Brand accent / CTA                  |
| `--secondary`      | `hsl(252 100% 96%)`       | `hsl(252 60% 18%)`        | Secondary button / chip             |
| `--accent`         | `hsl(240 20% 95%)`        | `hsl(240 10% 16%)`        | Hover wash                          |
| `--border`         | `hsl(240 12% 90%)`        | `hsl(240 10% 18%)`        | Hairline borders                    |
| `--ring`           | `hsl(252 80% 60%)`        | `hsl(252 90% 70%)`        | Focus ring                          |
| `--destructive`    | `hsl(0 78% 56%)`          | `hsl(0 78% 56%)`          | Destructive actions                 |
| `--constructive`   | `hsl(150 70% 42%)`        | `hsl(150 60% 50%)`        | Success / approved states           |

## Radii & shadows

| Token           | Value                                  | Used for                          |
| --------------- | -------------------------------------- | --------------------------------- |
| `--radius-sm`   | `0.45rem`                              | Pills, badges, small chips        |
| `--radius-md`   | `0.7rem`                               | Buttons, inputs                   |
| `--radius-lg`   | `0.875rem`                             | Panels, dialogs, cards            |
| `--shadow-panel`| layered soft drop                      | Every panel surface               |
| `--shadow-panel-lg` | layered soft + brand glow          | Floating tooltips / dialogs       |

## Surfaces & layout

- **Editor shell**: panels float on the page background with `gap-3` (12 px)
  between them. The panel itself carries `border-border/60` (60 % opacity
  hairline) plus `rounded-xl` and the soft drop shadow.
- **Header**: `h-[3.6rem]` glass toolbar with `border-b border-border/60`,
  rounded-full icon buttons.
- **Resizable handle**: 1 px hairline that turns into a 12 px translucent
  purple wash on hover; a 12 px circular dot fades in centered on the seam.

## Where tokens live

- `apps/web/src/app/globals.css` — root + `.dark` + `.panel` token blocks,
  `@theme inline` bridge to Tailwind, `@layer components` for `.panel-surface`
  and `.glass-toolbar` reusable classes.
- `apps/web/src/components/ui/button.tsx` — CVA variants consuming the
  `--primary` / `--secondary` / `--accent` tokens.
- `apps/web/src/components/ui/resizable.tsx` — handle styles use
  `bg-primary/20` for the hover wash and a circular dot for the grab affordance.

## How to extend

1. Add the new CSS variable in `:root`, `.dark`, and `.panel` blocks in
   `globals.css`.
2. Map it to Tailwind under `@theme inline` (`--color-<name>: var(--<name>)`).
3. Reference via standard Tailwind utilities (`bg-<name>`, `text-<name>`, …).

Never hard-code hex / hsl values inside components — always go through tokens.
