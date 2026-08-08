"""Extract the hardcoded seed arrays (pages/books/papers/photos/sections)
from admin.html and write them as JSON for the Flask app's seed step."""
import json
import re
import sys

SRC = "admin.html"
OUT = "data/seed.json"


class JSLiteralError(ValueError):
    pass


def parse_js_literal(text, i):
    """Parse a JS value (object/array/string/number/bool/null) starting at text[i].
    Returns (value, next_index). Keys may be unquoted; strings may be single or double quoted."""
    text = text.lstrip("\r\n")
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text):
        raise JSLiteralError("unexpected end")
    c = text[i]
    if c == "[":
        i += 1
        arr = []
        while True:
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i >= len(text):
                raise JSLiteralError("unterminated array")
            if text[i] == "]":
                return arr, i + 1
            val, i = parse_js_literal(text, i)
            arr.append(val)
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i < len(text) and text[i] == ",":
                i += 1
    elif c == "{":
        i += 1
        obj = {}
        while True:
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i >= len(text):
                raise JSLiteralError("unterminated object")
            if text[i] == "}":
                return obj, i + 1
            if text[i] in "'\"":
                key, i = parse_js_string(text, i)
            else:
                m = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", text[i:])
                if not m:
                    raise JSLiteralError("bad key at %d" % i)
                key = m.group(0)
                i += len(key)
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i < len(text) and text[i] == ":":
                i += 1
            val, i = parse_js_literal(text, i)
            obj[key] = val
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
            if i < len(text) and text[i] == ",":
                i += 1
    elif c in "'\"":
        s, i = parse_js_string(text, i)
        return s, i
    else:
        m = re.match(r"[A-Za-z0-9_+\-.]+", text[i:])
        if not m:
            raise JSLiteralError("unexpected char %r at %d" % (text[i], i))
        tok = m.group(0)
        i += len(tok)
        if tok == "true":
            return True, i
        if tok == "false":
            return False, i
        if tok in ("null", "undefined"):
            return None, i
        try:
            return json.loads(tok), i
        except ValueError:
            raise JSLiteralError("bad number %r" % tok)
    raise JSLiteralError("unreachable")


def parse_js_string(text, i):
    quote = text[i]
    i += 1
    out = []
    while i < len(text):
        ch = text[i]
        if ch == quote:
            return "".join(out), i + 1
        if ch == "\\":
            i += 1
            esc = text[i]
            mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "/": "/", "b": "\b", "f": "\f"}
            if esc == "u":
                out.append(chr(int(text[i + 1:i + 5], 16)))
                i += 5
            else:
                out.append(mapping.get(esc, esc))
                i += 1
        else:
            out.append(ch)
            i += 1
    raise JSLiteralError("unterminated string")


def extract_var(name, anchor=None):
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"const\s+" + name + r"\s*=", text)
    if not m:
        raise SystemExit("could not find const %s" % name)
    i = m.end()
    val, _ = parse_js_literal(text, i)
    return val


def main():
    pages = extract_var("DEFAULT_PAGES")
    books = extract_var("BOOKS_DATA")
    papers = extract_var("PAPERS_DATA")
    photos = extract_var("PHOTOS_DATA")
    sections = extract_var("sectionDefs")
    out = {
        "pages": pages,
        "books": books,
        "papers": papers,
        "photos": photos,
        "sections": sections,
        "settings": {},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for k, v in out.items():
        print(k, len(v))


if __name__ == "__main__":
    sys.exit(main())
