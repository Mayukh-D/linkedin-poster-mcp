# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "httpx>=0.27"]
# ///
"""linkedin-poster-mcp: a small local MCP server that publishes LinkedIn posts with native images,
Page tags, hashtags and reposts.

Uses LinkedIn's official API (Share on LinkedIn product, w_member_social scope):
images are uploaded through the Images API and attached to a post through the
Posts API, so photos appear as real photos, not link previews.

Setup:
  1. Create an app at https://www.linkedin.com/developers, add the products
     "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect",
     and add the redirect URL http://localhost:8765/callback.
  2. Put the credentials in ~/.linkedin-mcp.env:
         LINKEDIN_CLIENT_ID=...
         LINKEDIN_CLIENT_SECRET=...
  3. Sign in once:  uv run --script server.py login
     (tokens last 60 days; run login again when they expire)

Run as an MCP server (stdio):  uv run --script server.py
"""

from __future__ import annotations

import datetime as dt
import http.server
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

ENV_FILE = Path.home() / ".linkedin-mcp.env"
STATE_DIR = Path.home() / ".linkedin-mcp"
TOKEN_FILE = STATE_DIR / "token.json"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = "openid profile w_member_social"
API = "https://api.linkedin.com"


# ---------------------------------------------------------------- config / token

def load_env() -> dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_VERSION"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def save_token(data: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    TOKEN_FILE.chmod(0o600)


def load_token() -> dict:
    if not TOKEN_FILE.exists():
        raise RuntimeError("Not signed in. Run: uv run --script server.py login")
    data = json.loads(TOKEN_FILE.read_text())
    if data.get("expires_at", 0) < dt.datetime.now().timestamp() + 60:
        raise RuntimeError("LinkedIn token expired. Run: uv run --script server.py login")
    return data


# ---------------------------------------------------------------- OAuth login (CLI)

def login() -> None:
    env = load_env()
    cid, secret = env.get("LINKEDIN_CLIENT_ID"), env.get("LINKEDIN_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit(f"Missing LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET in {ENV_FILE}")
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            msg = "Signed in. You can close this tab." if "code" in q else "Sign-in failed. Check the terminal."
            self.wfile.write(f"<h2>{msg}</h2>".encode())

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT_URI,
        "state": state, "scope": SCOPES,
    })
    print("Opening LinkedIn sign-in in your browser...\nIf it doesn't open, visit:\n" + url)
    webbrowser.open(url)
    for _ in range(600):
        if result:
            break
        threading.Event().wait(0.5)
    server.server_close()
    if result.get("state") != state or "code" not in result:
        sys.exit(f"Sign-in failed: {result.get('error_description') or result or 'timed out'}")

    tok = httpx.post("https://www.linkedin.com/oauth/v2/accessToken", data={
        "grant_type": "authorization_code", "code": result["code"],
        "redirect_uri": REDIRECT_URI, "client_id": cid, "client_secret": secret,
    }, timeout=30)
    tok.raise_for_status()
    t = tok.json()
    me = httpx.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {t['access_token']}"}, timeout=30)
    me.raise_for_status()
    info = me.json()
    save_token({
        "access_token": t["access_token"],
        "expires_at": dt.datetime.now().timestamp() + int(t.get("expires_in", 0)),
        "person_urn": f"urn:li:person:{info['sub']}",
        "name": info.get("name", ""),
    })
    exp = dt.datetime.now() + dt.timedelta(seconds=int(t.get("expires_in", 0)))
    print(f"Signed in as {info.get('name')}. Token saved to {TOKEN_FILE} (valid until {exp:%d %b %Y}).")


# ---------------------------------------------------------------- API helpers

class LinkedIn:
    def __init__(self) -> None:
        self.token = load_token()
        self.env = load_env()
        self.version = self.env.get("LINKEDIN_VERSION") or self._detect_version()

    def headers(self, version: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token['access_token']}",
            "LinkedIn-Version": version or self.version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def _detect_version(self) -> str:
        """LinkedIn only serves API versions from roughly the last year; find the newest live one."""
        cache = STATE_DIR / "version"
        if cache.exists():
            return cache.read_text().strip()
        today = dt.date.today()
        for back in range(0, 15):
            y, m = today.year, today.month - back
            while m <= 0:
                y, m = y - 1, m + 12
            v = f"{y}{m:02d}"
            r = httpx.post(f"{API}/rest/images?action=initializeUpload", headers=self.headers(v),
                           json={"initializeUploadRequest": {"owner": self.token["person_urn"]}}, timeout=30)
            if r.status_code != 426 and "NONEXISTENT_VERSION" not in r.text and "VERSION_MISSING" not in r.text:
                STATE_DIR.mkdir(mode=0o700, exist_ok=True)
                cache.write_text(v)
                return v
        raise RuntimeError("Could not find a live LinkedIn API version; set LINKEDIN_VERSION=YYYYMM in ~/.linkedin-mcp.env")

    def upload_image(self, path: str) -> str:
        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Image not found: {p}")
        r = httpx.post(f"{API}/rest/images?action=initializeUpload", headers=self.headers(),
                       json={"initializeUploadRequest": {"owner": self.token["person_urn"]}}, timeout=30)
        r.raise_for_status()
        value = r.json()["value"]
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        up = httpx.put(value["uploadUrl"], content=p.read_bytes(), timeout=120,
                       headers={"Authorization": f"Bearer {self.token['access_token']}", "Content-Type": ctype})
        up.raise_for_status()
        return value["image"]

    def create_post(self, text: str, images: list[tuple[str, str]], visibility: str,
                    mentions: list[tuple[str, str]] | None = None, reshare_of: str | None = None) -> str:
        body: dict = {
            "author": self.token["person_urn"],
            "commentary": to_little_text(text, mentions),
            "visibility": visibility,
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if reshare_of:
            if images:
                raise ValueError("A repost cannot carry its own images")
            body["reshareContext"] = {"parent": reshare_of}
        ids = [(self.upload_image(path), alt) for path, alt in images]
        if len(ids) == 1:
            body["content"] = {"media": {"id": ids[0][0], "altText": ids[0][1]}}
        elif len(ids) > 1:
            body["content"] = {"multiImage": {"images": [{"id": i, "altText": a} for i, a in ids]}}
        r = httpx.post(f"{API}/rest/posts", headers=self.headers(), json=body, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"LinkedIn rejected the post ({r.status_code}): {r.text[:500]}")
        urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id", "")
        return urn

    def delete_post(self, urn: str) -> None:
        r = httpx.delete(f"{API}/rest/posts/{urllib.parse.quote(urn, safe='')}", headers=self.headers(), timeout=30)
        if r.status_code not in (200, 204):
            raise RuntimeError(f"Delete failed ({r.status_code}): {r.text[:500]}")


_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_HASHTAG = re.compile(r"(?<![\w&])#(\w+)")


def to_little_text(text: str, mentions: list[tuple[str, str]] | None = None) -> str:
    """Escape LinkedIn's reserved 'little text' characters, turning #word into a real hashtag
    and the first occurrence of each mention's display text into a tag: (display text, URN)."""
    tokens = {}
    for i, (name, urn) in enumerate(mentions or []):
        if name not in text:
            raise ValueError(f"Mention text not found in post: {name!r}")
        key = f"\x00{i}\x00"
        text = text.replace(name, key, 1)
        tokens[key] = "@[" + name + "](" + urn + ")"
    out, last = [], 0
    for m in _HASHTAG.finditer(text):
        out.append(_RESERVED.sub(r"\\\1", text[last:m.start()]))
        out.append("{hashtag|\\#|" + m.group(1) + "}")
        last = m.end()
    out.append(_RESERVED.sub(r"\\\1", text[last:]))
    result = "".join(out)
    for key, markup in tokens.items():
        result = result.replace(key, markup)
    return result


def post_urn_from(ref: str) -> str:
    """Accept a post URL or URN and return the share/ugcPost URN."""
    m = re.search(r"urn:li:(share|ugcPost|activity):\d+", urllib.parse.unquote(ref))
    if not m:
        raise ValueError(f"Not a LinkedIn post URL or URN: {ref}")
    return m.group(0)


# ---------------------------------------------------------------- MCP server

def serve() -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("linkedin-poster")

    @mcp.tool()
    def whoami() -> str:
        """Show which LinkedIn account is signed in and when the token expires."""
        t = load_token()
        exp = dt.datetime.fromtimestamp(t["expires_at"])
        return f"Signed in as {t.get('name')} ({t['person_urn']}); token valid until {exp:%d %b %Y}."

    @mcp.tool()
    def create_post(text: str, image_paths: list[str] | None = None,
                    alt_texts: list[str] | None = None, visibility: str = "PUBLIC",
                    mention_texts: list[str] | None = None, mention_urns: list[str] | None = None) -> str:
        """Publish a LinkedIn post as the signed-in member, with up to 20 native images.

        Publishing is public and immediate: only call this after the user has approved the exact
        text and images. image_paths are local files (jpg/png/gif); alt_texts match them by index.
        visibility is PUBLIC or CONNECTIONS. #hashtags in the text become real hashtags.
        To tag people or companies, pass mention_texts (exact text in the post to turn into the tag,
        e.g. "Eccoi") and mention_urns (urn:li:person:... or urn:li:organization:...) by index.
        Returns the post URL.
        """
        if visibility not in ("PUBLIC", "CONNECTIONS"):
            raise ValueError("visibility must be PUBLIC or CONNECTIONS")
        paths = image_paths or []
        if len(paths) > 20:
            raise ValueError("LinkedIn allows at most 20 images per post")
        alts = (alt_texts or []) + [""] * len(paths)
        mentions = list(zip(mention_texts or [], mention_urns or []))
        urn = LinkedIn().create_post(text, list(zip(paths, alts[: len(paths)])), visibility, mentions)
        return f"Posted: https://www.linkedin.com/feed/update/{urn}/"

    @mcp.tool()
    def repost(post: str, text: str = "", visibility: str = "PUBLIC",
               mention_texts: list[str] | None = None, mention_urns: list[str] | None = None) -> str:
        """Repost someone else's LinkedIn post (given its URL or URN) with optional commentary.

        Public and immediate: only call after the user has approved the exact commentary.
        """
        if visibility not in ("PUBLIC", "CONNECTIONS"):
            raise ValueError("visibility must be PUBLIC or CONNECTIONS")
        mentions = list(zip(mention_texts or [], mention_urns or []))
        urn = LinkedIn().create_post(text, [], visibility, mentions, reshare_of=post_urn_from(post))
        return f"Reposted: https://www.linkedin.com/feed/update/{urn}/"

    @mcp.tool()
    def delete_post(post: str) -> str:
        """Permanently delete one of the signed-in member's posts, given its URL or URN.

        Irreversible: only call after the user has explicitly confirmed deleting this exact post.
        """
        urn = post_urn_from(post)
        LinkedIn().delete_post(urn)
        return f"Deleted {urn}"

    mcp.run()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        login()
    else:
        serve()
