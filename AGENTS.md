# AGENTS.md

Personal site ("white" / Ricardo's Corner), deployed via GitHub Pages at `GrumpyAvo.github.io`.

## No build system
Pure static HTML/CSS/JS. No package.json, no bundler, no tests, no lint. There is no build or test command — verify by opening the HTML in a browser (or `python -m http.server`). Pages only work fully with network access (CDN + backend calls).

## Content lives in Supabase, not the HTML
Editing an `.html` file does **not** change site content. Every page loads data at runtime from:
- Supabase project `https://wzvmdpkiwwfhnisjudeo.supabase.co` (publishable key `sb_publishable_...` is hardcoded in each page)
- A separate Vercel backend `https://spotify-backend-lyart.vercel.app` for the "now playing" widget and hit counter (`/api/now-playing`, `/api/visitors?page=<slug>`)

Tables used: `tabs`, `posts`, `books`, `music`, `photos`, `links`, `guestbook_entries`, `sections`, `site_settings`, `pending_users`.

To change posts/books/music/photos/links/nav/settings, use `admin.html` (Supabase email/password auth) or the Supabase dashboard. The HTML files are templates/views only. `admin.html` also contains an "Import Data" seeder that backfills pages, books, study papers, and photos from hardcoded arrays.

## Page architecture
- **Standalone pages**: `index.html`, `about`, `life`, `studies`, `links`, `books`, `music`, `pics`, `guestbook`, plus secret pages `ballas.html` and `borat.html` (ballas is hidden from nav via `visible:false`).
- **`page.html`**: generic template — reads `?slug=` (or derives from filename) and renders rows from the `sections` table. Its JS is near-identical to the standalone pages.
- Rendering branches key off `page_type` on the `tabs` row (`books`, `photos`, `music`, `links`, `guestbook`, `standard`). Posts feed pages like `life`/`studies`; `studies` posts are seeded from `papers/*.pdf`.
- `currentSlug()` in each page decides routing; nav is rebuilt dynamically from the `tabs` table by `buildNav()`.

## Big gotcha: duplicated code everywhere
There is no shared CSS/JS file — the whole stylesheet and script block are copy-pasted into every page (several variants exist). Shared functions like `esc`, `md`, `buildNav`, `loadNowPlaying`, `renderPostCard`, the `renderSection` switch, dark-mode toggle, and the "nese" easter egg each exist in multiple files. If you change shared behavior, replicate it in **all** pages that carry it. `page.html` even has a comment reminding that its `@font-face` blocks must be copied from `index.html`.

## Site quirks to preserve
- **Easter egg**: typing `nese` toggles a secret font via `data-font2` (sessionStorage `rf2active`). Don't remove it.
- **Dark mode**: `localStorage['theme']` + `data-theme` attribute on `<html>`, set by a pre-paint script in `<head>`.
- **Fonts**: custom fonts (RicardoNese, SupremeDonuts, FluxDemo, Blowpis) are embedded as base64 `data:` URLs inside `index.html`'s `<style>` — huge lines, don't reformat.
- **Assets**: local photos are `photos/*.jpeg` (note `.jpeg`, not `.jpg`); `papers/*.pdf` back the studies posts. `index.html` references `me.jpg` for the avatar, but that file does not exist in the repo (known broken image).
