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

## Setup (about 10 minutes)

You need [uv](https://docs.astral.sh/uv/) and a free LinkedIn developer app.

1. **Create the app** at [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps). LinkedIn requires every app to be linked to a Company Page; if you don't have one, create a basic Page for yourself and verify the app from it (you're its admin, so you approve your own request).
2. On the **Products** tab, add **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**. Both are self-serve.
3. On the **Auth** tab, add the redirect URL `http://localhost:8765/callback`.
4. Put the app's credentials in `~/.linkedin-mcp.env` (keep this file private, never commit it):

   ```
   LINKEDIN_CLIENT_ID=your_client_id
   LINKEDIN_CLIENT_SECRET=your_client_secret
   ```

5. Sign in once. A browser window opens; click **Allow**.

   ```bash
   uv run --script server.py login
   ```

   Your access token is saved to `~/.linkedin-mcp/token.json` (mode 600). It lasts 60 days; run `login` again when it expires.

6. Add the server to your MCP client. For Claude Code:

   ```bash
   claude mcp add linkedin-poster --scope user -- uv run --quiet --script /path/to/server.py
   ```

   For other clients, the command is `uv run --quiet --script /path/to/server.py` over stdio.

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
- **Finding a Page's ID:** it's the number in `urn:li:organization:<id>`, which appears in the Page's HTML and in many LinkedIn tools' output.
- The LinkedIn API version is detected automatically (LinkedIn only serves roughly the last year of versions). To pin one, add `LINKEDIN_VERSION=YYYYMM` to `~/.linkedin-mcp.env`.

## How it works

- **Sign-in:** standard OAuth 2.0 authorisation-code flow with a one-shot local callback server on port 8765, scopes `openid profile w_member_social`.
- **Images:** `POST /rest/images?action=initializeUpload`, then `PUT` the bytes to the returned upload URL.
- **Posts:** `POST /rest/posts` with `content.media` (one image) or `content.multiImage` (several), commentary in LinkedIn's "little text" format, and `reshareContext` for reposts.

## License

MIT
