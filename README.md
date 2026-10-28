# linkedin-poster-mcp

An MCP server that lets Claude (or any MCP client) publish LinkedIn posts with **real photos**, company tags, hashtags and reposts, through LinkedIn's official API.

Most LinkedIn MCPs either drive your logged-in browser session (and can read but not post), or post through automation platforms that quietly drop images and turn your post into a bare link. This one uploads images through LinkedIn's Images API and attaches them natively, so a post looks exactly like one you made by hand.

It's a single Python file, runs locally, and keeps your credentials on your machine.

## Tools

| Tool | What it does |
|---|---|
| `create_post` | Publishes a post with up to 20 native images (with alt text), `#hashtags`, and tags for company or school Pages. Visibility: `PUBLIC` or `CONNECTIONS`. |
| `repost` | Reposts someone else's post, given its URL, with your own commentary. |
| `delete_post` | Deletes one of your posts, given its URL. |
| `whoami` | Shows the signed-in account and when the sign-in expires. |

The tool descriptions tell the model to get your explicit approval of the exact text and images before posting or deleting anything. Keep it that way: posts are public and immediate.

## Install

You need [uv](https://docs.astral.sh/uv/).

1. Get the server:

   ```bash
   curl -fsSLO https://raw.githubusercontent.com/Mayukh-D/linkedin-poster-mcp/main/server.py
   ```

2. Sign in to LinkedIn. A browser tab opens; click **Allow**.

   ```bash
   uv run --script server.py login
   ```

3. Add it to your MCP client. For Claude Code:

   ```bash
   claude mcp add linkedin-poster --scope user -- uv run --quiet --script "$PWD/server.py"
   ```

   For other clients, the command is `uv run --quiet --script /path/to/server.py` over stdio.

That's it. Your access token is saved to `~/.linkedin-mcp/token.json` (readable only by you) and lasts 60 days; run `login` again when it expires.

### How sign-in works

LinkedIn needs an app secret to finish a sign-in, and a secret can't live in public code. So sign-in goes through a small relay (the [`relay/`](relay/) folder, a Cloudflare Worker) that holds the secret, swaps LinkedIn's one-time code for your token, and hands the token straight back to your machine in the URL fragment, which browsers never send to any server. The relay stores nothing. After sign-in, your machine talks to LinkedIn directly. See the [privacy policy](https://mayukhdas.com/linkedin-poster/privacy/).

### Prefer your own LinkedIn app?

If you'd rather not use the relay at all (about 10 minutes):

1. Create an app at [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps). LinkedIn requires every app to be linked to a Company Page; if you don't have one, create a basic Page and verify the app from it (you're its admin, so you approve your own request).
2. On the **Products** tab, add **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. On the **Auth** tab, add the redirect URL `http://localhost:8765/callback`.
4. Put the credentials in `~/.linkedin-mcp.env` (keep it private, never commit it):

   ```
   LINKEDIN_CLIENT_ID=your_client_id
   LINKEDIN_CLIENT_SECRET=your_client_secret
   ```

5. Run `uv run --script server.py login`. With that file present, it signs in with your own app (or force either path with `login --own-app` / `login --relay`).

## Usage

Ask your assistant in plain language, for example:

> Post this to LinkedIn with these two photos, tag Eccoi, visible to anyone: ...

Under the hood, `create_post` takes:

- `text`: the post body. `#words` become real hashtags; LinkedIn's reserved characters are escaped for you.
- `image_paths` / `alt_texts`: local image files and matching alt text.
- `mention_texts` / `mention_urns`: text in the post to turn into a tag, and the Page it points to (`urn:li:organization:<id>`). The first occurrence of each text is tagged.
- `visibility`: `PUBLIC` (default) or `CONNECTIONS`.

## Limits worth knowing

- **Tagging people doesn't work through the API.** LinkedIn only accepts member IDs it issues through that member's own sign-in, not the ID on their profile page. Tag Pages through the API, and add people by editing the post on LinkedIn afterwards.
- **It posts as you, not as a Company Page.** Posting as an organisation needs LinkedIn's Community Management API, which requires a partner review.
- **Sign-ins last 60 days.** There is no refresh token for this product tier.
- **The relay's app shares one set of LinkedIn API limits** across everyone who signs in through it. That's plenty for personal posting; heavy users should bring their own app.
- **Finding a Page's ID:** it's the number in `urn:li:organization:<id>`, which appears in the Page's HTML and in many LinkedIn tools' output.
- The LinkedIn API version is detected automatically (LinkedIn only serves roughly the last year of versions). To pin one, add `LINKEDIN_VERSION=YYYYMM` to `~/.linkedin-mcp.env`.

## How it works

- **Sign-in:** OAuth 2.0 authorisation-code flow, scopes `openid profile w_member_social`, either through the relay or your own app, with a one-shot local server receiving the result.
- **Images:** `POST /rest/images?action=initializeUpload`, then `PUT` the bytes to the returned upload URL.
- **Posts:** `POST /rest/posts` with `content.media` (one image) or `content.multiImage` (several), commentary in LinkedIn's "little text" format, and `reshareContext` for reposts.

## Credits

Built by [Mayukh Das](https://mayukhdas.com) with [Claude Code](https://claude.com/claude-code), Anthropic's coding agent, which co-wrote the server, the relay Worker and this README. More on how it came together: [Why I now post to LinkedIn from my terminal](https://mayukhdas.com/notes/post-from-the-terminal/).

## License

MIT
