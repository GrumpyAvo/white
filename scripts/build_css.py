"""Build static/css/style.css from the existing pages.

Strategy: start with index.html's full <style> block verbatim (fonts + layout +
components), then append only the component rules that index.html does NOT
already define, sourced verbatim from page.html (books/music/photos/links/
guestbook/text/hero/paper), books.html (rating toggle + page wrapper), and
pics.html (album tabs, gallery, lightbox).
"""
import re

OUT = "static/css/style.css"

index = open("index.html", encoding="utf-8").read()
page = open("page.html", encoding="utf-8").read()
books = open("books.html", encoding="utf-8").read()
pics = open("pics.html", encoding="utf-8").read()

def style_block(src):
    m = re.search(r"<style>(.*?)</style>", src, re.S)
    return m.group(1) if m else ""

index_css = style_block(index)
page_css = style_block(page)
books_css = style_block(books)
pics_css = style_block(pics)

# Selector names already defined by index.html — we won't re-add those blocks.
# (block = a CSS rule; approximate grouping by matching selector at start of rule)
index_selectors = set(re.findall(r"^([^{}]+)\{", index_css, re.M))

def extra_blocks(css, wanted):
    """Return contiguous rule blocks whose selector mentions any of `wanted`.
    Preserves them verbatim, including media-query wrapping.
    """
    chunks = []
    depth = 0
    start = None
    scan = 0
    for m in re.finditer(r"[{}]", css):
        i, ch = m.start(), m.group(0)
        if ch == "{":
            depth += 1
            if depth == 1:
                start = i
        else:
            depth -= 1
            if depth == 0 and start is not None:
                chunks.append((css[scan:start].strip(), css[start:i + 1]))
                scan = i + 1
                start = None
    out = []
    for sel, body in chunks:
        if any(w in sel for w in wanted):
            out.append(sel + body)
    return "\n".join(out)

# Components that page.html adds on top of index.html
extra_components = [
    ".books-grid", ".book-card", ".book-cover", ".book-info", ".book-title-text",
    ".book-author", ".book-stars", ".music-grid", ".music-card", ".music-cover",
    ".music-info", ".music-title-text", ".music-artist", ".music-type",
    ".photos-grid", ".photo-item", ".photo-caption", ".links-list", ".link-item",
    ".link-desc", ".link-category", ".links-category-header", ".text-block",
    ".gb-form", ".gb-entries", ".gb-entry-card", ".gb-name", ".gb-date",
    ".gb-message", ".gb-msg-ok", ".gb-msg-err", ".gb-closed", ".form-group",
    ".gb-submit", ".hero-section", ".paper-card", ".section-loading", ".empty-notice",
    "#lightbox",
]
page_extra = extra_blocks(page_css, extra_components)
# books.html: page wrapper, rating toggle, dark-mode for its cards
books_extra = extra_blocks(books_css, [
    ".page-wrap", ".page-header-row", ".page-title", ".toggle-wrap", ".toggle-label",
    ".toggle-btn", ".rating-badge", ".card-meta", ".page-btn",
])
# pics.html: album tabs + gallery grid
pics_extra = extra_blocks(pics_css, [".album-tab", ".gallery"])

css = (
    "/* Generated from the static site's inline styles — see scripts/build_css.py */\n"
    "/* --- index.html --- */\n" + index_css + "\n\n"
    "/* --- page.html components --- */\n" + page_extra + "\n\n"
    "/* --- books.html components --- */\n" + books_extra + "\n\n"
    "/* --- pics.html components --- */\n" + pics_extra + "\n"
)

# Rename books-specific page-title to avoid clashing with header-meta classes is
# unnecessary; keep verbatim for fidelity.
open(OUT, "w", encoding="utf-8", newline="\n").write(css)
print("wrote", OUT, len(css), "bytes")
print("index selectors:", len(index_selectors))
