"""One-shot Spotify OAuth flow — produces the SPOTIFY_REFRESH_TOKEN the backend needs.

Why this exists: spotify.py uses the OAuth refresh-token flow. That requires a
refresh token, which can only be minted by completing an interactive
authorization once. This script does that dance for you:

1. Reads SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET from env or the repo `.env`.
2. Starts a local server on http://127.0.0.1:8888/callback and opens your browser
   to Spotify's authorization page.
3. Captures the code, exchanges it for tokens, and writes SPOTIFY_REFRESH_TOKEN
   into the repo `.env`.
4. Verifies the whole pipeline by hitting the Spotify API through spotify.py.

Before running:
  * Create an app at https://developer.spotify.com/dashboard (Spotify Dashboard →
    your app → Settings) and note the Client ID / Client Secret.
  * Add the redirect URI  http://127.0.0.1:8888/callback  under your app's
    Redirect URIs. IMPORTANT: use `127.0.0.1`, not `localhost` — Spotify stopped
    accepting `localhost` aliases in Nov 2025. Loopback IP literals are the only
    HTTP redirect URIs allowed.
  * Put the client id/secret in `.env` at the repo root (see .env.example):

        SPOTIFY_CLIENT_ID=...
        SPOTIFY_CLIENT_SECRET=...

Then run:  python scripts/spotify_oauth.py

Once it succeeds, also paste the printed SPOTIFY_REFRESH_TOKEN into the Render
dashboard (Environment) so the deployed site works too.
"""
import http.server
import os
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from urllib.request import Request, urlopen

# ── paths ──────────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
REDIRECT_PORT = 8888
REDIRECT_URI = "http://127.0.0.1:%d/callback" % REDIRECT_PORT

SCOPES = "user-read-currently-playing user-read-playback-state user-top-read"

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


# ── minimal .env helpers ───────────────────────────────────────────────────────
def load_env():
    data = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def save_env(pairs):
    lines = []
    if os.path.exists(ENV_PATH):
        lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    for key, value in pairs:
        found = False
        for i, line in enumerate(lines):
            if re.match(r"^\s*" + re.escape(key) + r"\s*=", line):
                lines[i] = "%s=%s" % (key, value)
                found = True
                break
        if not found:
            lines.append("%s=%s" % (key, value))
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


# ── local callback server ──────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):  # noqa: N802
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        error = qs.get("error")
        Handler.code = qs.get("code", [None])[0]
        body = (
            "<html><body style='font-family:sans-serif;text-align:center;margin-top:15%'>"
            + ("<h2>Authorized! You can close this tab.</h2>"
               if Handler.code and not error
               else "<h2>Authorization failed: %s</h2>" % (error or ["missing code"]))
            + "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        # stop serving after the first request
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):  # silence request logging
        pass


def main():
    env = load_env()
    env.update({k: v for k, v in os.environ.items() if k.startswith("SPOTIFY_")})
    client_id = env.get("SPOTIFY_CLIENT_ID")
    client_secret = env.get("SPOTIFY_CLIENT_SECRET")

    if not (client_id and client_secret):
        print("Missing Spotify credentials.\n")
        print("1. Create an app at https://developer.spotify.com/dashboard")
        print("2. Under your app's Settings, copy the Client ID and Client Secret")
        print("3. Add the Redirect URI:  %s" % REDIRECT_URI)
        print("4. Create a `.env` file in the repo root with:\n")
        print("      SPOTIFY_CLIENT_ID=<your client id>")
        print("      SPOTIFY_CLIENT_SECRET=<your client secret>\n")
        print("Then re-run this script. (.env.example shows the layout.)")
        return 1

    # pick a free port, defaulting to the one registered in the Spotify app
    server = None
    for port in [REDIRECT_PORT] + list(range(REDIRECT_PORT + 1, REDIRECT_PORT + 8)):
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        print("Could not bind a local server. Close something using port 8888 and retry.")
        return 1
    if server.server_port != REDIRECT_PORT:
        print("Port %d busy; using http://127.0.0.1:%d/callback instead." % (REDIRECT_PORT, server.server_port))
        print("If Spotify rejects it, add that exact URI to your app's Redirect URIs.")

    uri = "http://127.0.0.1:%d/callback" % server.server_port
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": uri,
        "scope": SCOPES,
        "show_dialog": "true",
    })
    url = AUTHORIZE_URL + "?" + params

    print("Opening your browser to authorize Spotify access...")
    print("If it doesn't open automatically, visit:\n  %s\n" % url)
    webbrowser.open(url)

    server.timeout = 300  # give up after 5 minutes
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1
    code = Handler.code
    server.server_close()

    if not code:
        print("No authorization code received.")
        return 1

    print("Exchanging code for tokens...")
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=30) as resp:
            token_data = json_loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("Token exchange failed: %s" % exc)
        return 1

    refresh = token_data.get("refresh_token")
    if not refresh:
        print("No refresh_token in response: %s" % (token_data or {}))
        return 1

    save_env([
        ("SPOTIFY_CLIENT_ID", client_id),
        ("SPOTIFY_CLIENT_SECRET", client_secret),
        ("SPOTIFY_REFRESH_TOKEN", refresh),
    ])
    print("\nOK - wrote SPOTIFY_REFRESH_TOKEN to .env")

    print("\nPaste this value into Render (Dashboard → your service → Environment):")
    print("  SPOTIFY_REFRESH_TOKEN=%s" % refresh)

    print("\nVerifying the pipeline through spotify.py...")
    sys.path.insert(0, ROOT)
    try:
        import spotify

        time.sleep(0.5)
        print("  now-playing:", spotify.now_playing())
        stats = spotify.top_stats()
        print("  top-stats:  %d artists, %d tracks" % (len(stats["artists"]), len(stats["tracks"])))
        print("\nAll good. The Flask backend will now report live Spotify data.")
    except Exception as exc:  # noqa: BLE001
        print("Verification failed (backend code issue, not your creds): %s" % exc)
    return 0


def json_loads(text):
    import json

    return json.loads(text)


if __name__ == "__main__":
    sys.exit(main())
