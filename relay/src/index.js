// Sign-in relay for linkedin-poster-mcp.
//   GET /start?state=<nonce>.<port>   -> redirect to LinkedIn's consent screen
//   GET /callback?code=..&state=..     -> swap the code for a token, then send the browser to
//                                        http://127.0.0.1:<port>/done#access_token=...
// The token travels in the URL fragment, which browsers never send to any server, and goes
// only to the user's own machine. Nothing is stored or logged here.

const STATE_RE = /^([A-Za-z0-9_-]{16,64})\.(\d{4,5})$/;

function page(title, body, status = 200) {
  return new Response(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title><style>body{background:#010203;color:#d8e4dc;font:16px/1.5 ui-monospace,Menlo,monospace;
display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:34rem;padding:24px}h1{color:#00ff41;font-size:1.2rem}</style>
<main><h1>${title}</h1><p>${body}</p></main>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "referrer-policy": "no-referrer" } }
  );
}

function parseState(state) {
  const m = STATE_RE.exec(state || "");
  if (!m) return null;
  const port = Number(m[2]);
  return port >= 1024 && port <= 65535 ? { nonce: m[1], port } : null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const redirectUri = `${url.origin}/callback`;

    if (url.pathname === "/start") {
      const state = url.searchParams.get("state");
      if (!parseState(state)) return page("Bad request", "This link must be opened by linkedin-poster-mcp's login command.", 400);
      const auth = new URL("https://www.linkedin.com/oauth/v2/authorization");
      auth.search = new URLSearchParams({
        response_type: "code", client_id: env.LINKEDIN_CLIENT_ID, redirect_uri: redirectUri,
        state, scope: env.SCOPES,
      }).toString();
      return Response.redirect(auth.toString(), 302);
    }

    if (url.pathname === "/callback") {
      const state = parseState(url.searchParams.get("state"));
      if (!state) return page("Sign-in failed", "The sign-in state was missing or malformed. Run the login command again.", 400);
      const err = url.searchParams.get("error_description") || url.searchParams.get("error");
      const code = url.searchParams.get("code");
      const back = `http://127.0.0.1:${state.port}/done`;
      if (err || !code) {
        return Response.redirect(`${back}#error=${encodeURIComponent(err || "no code returned")}&state=${state.nonce}`, 302);
      }
      const r = await fetch("https://www.linkedin.com/oauth/v2/accessToken", {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "authorization_code", code, redirect_uri: redirectUri,
          client_id: env.LINKEDIN_CLIENT_ID, client_secret: env.LINKEDIN_CLIENT_SECRET,
        }),
      });
      if (!r.ok) {
        return Response.redirect(`${back}#error=${encodeURIComponent(`token exchange failed (${r.status})`)}&state=${state.nonce}`, 302);
      }
      const t = await r.json();
      const frag = new URLSearchParams({ access_token: t.access_token, expires_in: String(t.expires_in || 0), state: state.nonce });
      return new Response(null, { status: 302, headers: { location: `${back}#${frag}`, "cache-control": "no-store", "referrer-policy": "no-referrer" } });
    }

    if (url.pathname === "/") {
      return page("linkedin-poster-mcp sign-in relay",
        'Used by <a style="color:#00ff41" href="https://github.com/Mayukh-D/linkedin-poster-mcp">linkedin-poster-mcp</a> to sign you in to LinkedIn. It stores nothing. <a style="color:#00ff41" href="https://mayukhdas.com/linkedin-poster/privacy/">Privacy</a>.');
    }
    return page("Not found", "Nothing here.", 404);
  },
};
