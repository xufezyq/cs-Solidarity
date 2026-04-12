# Glassmorphism Web Panel Redesign

## Overview

Redesign the cs-Solidarity web control panel from a flat dark theme to a modern Glassmorphism (glass morphism) aesthetic. The goal is to make the UI feel premium, modern, and visually polished while preserving all existing functionality.

## Scope

- Single file: `web/static/index.html` (731 lines, ~35 KB)
- No new dependencies except optional icon library (`@mdi/font` CDN)
- All business logic, API calls, and component structure remain unchanged
- Dark theme preserved; background upgraded to gradient + ambient light spots

## Design Tokens

Replace current flat tokens with Glassmorphism equivalents:

```
--bg:         #0a0a1a          (deeper base)
--bg-grad1:   #0a0a1a          (gradient start)
--bg-grad2:   #1a1035          (gradient end)
--glass-bg:   rgba(255,255,255,0.05)
--glass-border: rgba(255,255,255,0.08)
--glass-hover: rgba(255,255,255,0.08)
--blur:       20px
--blur-heavy: 24px
--radius:     16px
--radius-sm:  10px
--accent:     #7c6cff          (keep indigo family)
--accent2:    #5a4fd6
--glow:       rgba(124,108,255,0.3)
--text:       #e8e8f0
--text2:      #8888a8
--green:      #4ade80
--red:        #f87171
--yellow:     #fbbf24
--blue:       #60a5fa
```

## Visual Elements

### Background
- `body`: linear-gradient diagonal (`#0a0a1a` → `#1a1035`)
- 3 ambient light spots via `body::before` pseudo-element: overlapping `radial-gradient` circles (purple, blue, indigo), blurred at 120px, animated with slow CSS drift (20s alternate infinite)
- No images required; all pure CSS

### Glass Cards (`.card`, `.login-box`, sidebar)
- `background: var(--glass-bg)`
- `backdrop-filter: blur(var(--blur))`
- `border: 1px solid var(--glass-border)`
- `border-radius: var(--radius)`
- `box-shadow: 0 8px 32px rgba(0,0,0,0.3)`
- On hover: border brightens to `rgba(255,255,255,0.15)`, slight `translateY(-2px)`, shadow deepens

### Sidebar
- Glass background with `backdrop-filter: blur(24px)`
- Active nav item: pill shape with accent glow (`box-shadow: 0 0 12px var(--glow)`)
- Brand name with gradient text effect
- User info section separated by glass-style divider

### Login Page
- Centered glass card (max-width 400px, more padding)
- Background: full-page gradient with animated light spots
- Title with gradient text
- Inputs: glass background, glow border on focus
- Button: gradient fill (`--accent` → `--accent2`), glow on hover

### Buttons
- Primary (`.btn-sm`): gradient background, `border-radius: 8px`, glow on hover
- Success: green gradient
- Danger: red gradient
- Warning: yellow gradient (dark text)
- All buttons: subtle scale(1.02) on hover, smooth transition

### Tables
- Header row: semi-transparent background `rgba(255,255,255,0.03)`
- Rows: transparent, hover highlight `rgba(255,255,255,0.04)`
- Remove hard borders, use subtle bottom separator `rgba(255,255,255,0.05)`

### Inputs & Forms
- Glass background `rgba(255,255,255,0.04)`
- Focus: accent glow border + subtle outer glow
- Select: styled dropdown matching glass theme

### Status Indicators (Dashboard)
- Stat numbers: gradient text (accent → blue)
- Status dots: colored circles with matching glow (`box-shadow`)
- Replace emoji with CSS-rendered indicators where possible

### Toast Notifications
- Glass background card
- Slide-in from right with spring animation
- Color-coded left border (green/red) instead of solid fill
- Auto-dismiss 3s

### Log Viewer
- Terminal-style container with glass background
- Monospace font preserved
- Level colors: red for ERROR, yellow for WARNING (keep)

## Animations

- **Page transitions**: fade-in 0.2s
- **Card entrance**: stagger animation (cards appear sequentially with 50ms delay)
- **Toast**: slide-in from right with overshoot (cubic-bezier)
- **Background light spots**: slow CSS drift animation (20s alternate)
- **Hover effects**: all transitions 0.2s ease

## Icons

Replace emoji navigation icons with Material Design Icons (CDN):
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/css/materialdesignicons.min.css">
```

Usage: `<i class="mdi mdi-view-dashboard"></i>` instead of `📊`

Icon mapping:
- 仪表盘: `mdi-view-dashboard`
- 实例管理: `mdi-puzzle`
- 配置编辑: `mdi-cog`
- Steam: `mdi-steam`
- 日志: `mdi-file-document`
- 控制: `mdi-play-circle`
- 用户管理: `mdi-account-group`
- 修改密码: `mdi-lock`
- 退出: `mdi-logout`

## Responsive Behavior

- Keep existing breakpoint at 769px
- Mobile: sidebar becomes top nav bar (glass style), cards stack vertically
- Desktop: 220px sidebar (slightly wider for icon + text), scrollable main area

## Implementation Constraint

- ALL changes confined to `web/static/index.html`
- No structural changes to Vue template logic (v-if, v-for, etc.)
- Only CSS class additions/replacements and style block rewrite
- Login page vanilla JS untouched
- Business logic untouched
