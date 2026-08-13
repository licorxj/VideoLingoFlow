# Mobile Editor Design Spec

## Overview

Add full mobile editing support to the editor page (`/editor/[project_id]`) using a separate component tree (Approach A). Desktop and mobile share the same EditorCore, stores, and services — only the view layer is independent.

## Scope

- Editor page only (`app/[locale]/editor/[project_id]/`)
- Landing page and project list already have basic responsive support — not in scope
- Full editing capability — no feature cuts

## Layout Architecture

### Entry Point

In `page.tsx`, branch on `useIsMobile()`:

```
isMobile ? <MobileEditorLayout /> : <DesktopEditorLayout />
```

Both layouts consume the same `EditorCore` singleton and Zustand stores.

### Mobile Layout (Portrait)

```
┌──────────────────────────┐
│ MobileHeader             │  44px
│ [← Back] [Name] [↻ ⋮]   │
├──────────────────────────┤
│                          │
│   MobilePreview          │  flex-1 (adaptive), min 30vh
│   (canvas + play overlay)│
│                          │
├──────────────────────────┤
│ MobileTimeline           │  fixed 180px
│ ┌──────────────────────┐ │
│ │ 🎥 Video track ←←→→  │ │  horizontal scroll
│ │ 🔤 Text track        │ │  pinch to zoom
│ │ 🎵 Audio track       │ │  playhead centered
│ └──────────────────────┘ │
├──────────────────────────┤
│ MobileToolbar            │  56px + safe-area
│ [Assets][Text][Sticker][Audio][AI] │
└──────────────────────────┘
```

### Drawer System

Toolbar tabs open a bottom drawer (vaul Drawer), max 60vh:

- Only one drawer open at a time (mutually exclusive)
- Selecting a timeline element auto-opens the properties drawer
- Deselecting auto-closes
- Drag down to dismiss (native vaul behavior)
- Preview area shrinks but stays visible when drawer is open

## Interaction Design

### Timeline Gestures

| Gesture | Behavior |
|---------|----------|
| Single-finger horizontal drag | Scroll timeline (playhead stays centered, content moves) |
| Two-finger pinch | Zoom timeline precision (px-per-frame) |
| Long press on clip (300ms) | Enter drag mode (vibration feedback), reorder / cross-track move |
| Tap clip | Select → auto-open properties drawer |
| Double-tap clip | Enter trim mode (drag handles appear at clip edges) |
| Drag clip edge | Adjust clip duration (in/out points) |
| Tap empty area | Deselect, close drawer |

### Trim Mode

Double-tap a clip enters a dedicated trim UI:

```
┌──────────────────────────┐
│   Preview (current frame) │
├──────────────────────────┤
│ ◀ ┃██████████████┃ ▶    │  draggable handles
│         [✓ OK] [✗ Cancel]│
└──────────────────────────┘
```

### Preview Canvas Gestures

| Gesture | Behavior |
|---------|----------|
| Tap canvas | Play / Pause |
| Two-finger pinch | Zoom canvas view |
| Two-finger drag | Pan canvas |
| Long press on element | Select element, show transform handles |
| Drag selected element | Move element position |
| Two-finger rotate on element | Rotate element |

### Header

```
[← Back]  [Project Name]  [↻ Undo] [↻ Redo] [⋮ More]
                                               ├─ Export
                                               ├─ Project Settings
                                               ├─ Fullscreen Preview
                                               └─ Shortcuts Help
```

### Toolbar

```
[Assets]  [Text]  [Sticker]  [Audio]  [AI]
```

Active tab highlighted. Tap active tab again to close drawer.

### Safe Area

- Bottom toolbar: `pb-[env(safe-area-inset-bottom)]`
- Top header: `pt-[env(safe-area-inset-top)]`
- Viewport meta: `viewport-fit=cover`

## Technical Strategy

### Shared vs Independent

```
Shared (unchanged):
  EditorCore, Zustand stores, services/, hooks/actions/,
  types/, constants/, lib/

Desktop view (unchanged):
  components/editor/*

Mobile view (new):
  components/editor/mobile/*
```

### No New Dependencies

Touch gesture system built on native Touch API:

```typescript
useTouchGestures({
  onPan,        // single-finger drag
  onPinch,      // two-finger scale
  onLongPress,  // 300ms threshold
  onDoubleTap,  // 300ms interval
  onRotate,     // two-finger rotation
})
```

### File Structure

```
components/editor/mobile/
├── mobile-editor-layout.tsx
├── mobile-header.tsx
├── mobile-preview.tsx
├── mobile-timeline/
│   ├── mobile-timeline.tsx
│   ├── mobile-track.tsx
│   ├── mobile-playhead.tsx
│   └── mobile-timeline-gestures.tsx
├── mobile-toolbar.tsx
├── mobile-drawer/
│   ├── mobile-assets-drawer.tsx
│   ├── mobile-properties-drawer.tsx
│   ├── mobile-text-drawer.tsx
│   ├── mobile-sticker-drawer.tsx
│   ├── mobile-audio-drawer.tsx
│   └── mobile-ai-drawer.tsx
└── hooks/
    ├── use-touch-gestures.ts
    ├── use-timeline-scroll.ts
    └── use-mobile-drawer.ts
```

### Timeline Mobile Differences

- **Playhead centered**: content scrolls left, playhead stays at screen center (CapCut style)
- **Larger track height**: 48px (vs desktop TRACK_HEIGHTS) for touch-friendly targets
- **Bigger snap threshold**: 15px (vs desktop 5px)
- **Thumbnails**: reuse `timeline-thumbnail` service, sized for mobile track height

### Properties Panel Reuse

Desktop property components render inside a `MobileDrawerContainer` wrapper that:

- Enforces min touch target size (44px)
- Increases spacing
- Applies CSS overrides where needed

### Performance

- Mobile components loaded via `React.lazy()` — desktop never loads mobile code
- Timeline scrolling via `translateX` with `will-change: transform` (GPU-accelerated)
- Touch handlers registered with `{ passive: true }`
- Canvas/video elements shared, not duplicated

### Not Changing

- No new stores
- No new services
- No EditorCore modifications
- No new third-party gesture libraries
- No changes to existing desktop component props/API
