# publish-to-confluence

## What it does

publish-to-confluence is a Claude Code skill that publishes a markdown file as a Confluence page, then updates that same page each time you publish the file again. It uploads the images your file uses, and every web link in it shows on the page as a smart-link card. Reviewers' inline comments stay attached when you republish. If someone edited the page on Confluence since your last publish, you choose whether to merge their edits into your file or overwrite them.

## What you need

- Claude Code on a Mac.
- The Atlassian MCP server, connected to Claude Code. MCP is the standard way Claude Code connects to other apps, and Atlassian's MCP server lets it read and edit Confluence pages with your Atlassian account. The setup below adds the server if it's missing, and you log in once through `/mcp`.
- Python 3 and git. Both come with Apple's command line developer tools. If Claude says git or Python 3 is missing, ask it to run `xcode-select --install`, which opens Apple's installer. When the install finishes, paste the [setup prompt](#set-it-up) again.
- A Confluence page or folder you can add pages to.
- Optional: an Atlassian API token, for images, cards and keeping comments attached (see [The token file](#the-token-file)).

## Set it up

Paste this into Claude Code and answer its questions. Have your Confluence page or folder open in your browser, so you can copy its address from the address bar.

```text
Set up the publish-to-confluence skill for me. I'm not a developer, so run each step
yourself and tell me in plain words what you did.

1. If the folder "~/Code/Publish to Confluence" doesn't exist, clone
   https://github.com/jkarnik/publish-to-confluence.git into it. If it already exists,
   run git pull in it instead.
2. Make "~/.claude/skills/publish-to-confluence" a symbolic link to that folder, so
   Claude Code loads it as a personal skill. Create "~/.claude/skills" first if needed.
3. Check whether the Atlassian MCP server is set up in Claude Code. If it isn't, add it
   for all my projects:
   claude mcp add --transport http --scope user atlassian "https://mcp.atlassian.com/v2/mcp?tools=all"
   If it's set up but its address doesn't end in ?tools=all, change its address to the
   one above, keeping its name and scope.
4. If the folder has no SETUP.md, copy SETUP.example.md to SETUP.md. If its Parent:
   line still holds the placeholder text in parentheses, ask me for the address of the
   Confluence page or folder my pages should go under, and replace that text with it.
5. If the folder has no atlassian-api.env, tell me that an Atlassian API token lets the
   skill upload images, turn links into cards and keep comments attached, and ask
   whether I want to set one up now. If I do:
   - copy atlassian-api.env.example to atlassian-api.env and make it readable only
     by me (chmod 600)
   - ask for my Atlassian email and put it after ATLASSIAN_EMAIL=
   - tell me to open https://id.atlassian.com/manage-profile/security/api-tokens,
     select "Create API token" (not the one with scopes) and copy the token
   - open atlassian-api.env in TextEdit, so I can paste the token after
     ATLASSIAN_API_TOKEN= and save
   Never ask me to paste the token into this chat, and never show the file's contents.
6. Tell me to restart Claude Code, then type /mcp and log in to the Atlassian MCP
   server if it isn't logged in yet.
```

When Claude says it's done, restart Claude Code. If the Atlassian MCP server isn't logged in yet, type `/mcp`, select it, press Enter and choose "Authenticate".

### Set it up by hand

Run these in Terminal. They do the same as the prompt.

1. Get the files. If you already have the folder, run `git -C "$HOME/Code/Publish to Confluence" pull` instead.

   ```sh
   git clone https://github.com/jkarnik/publish-to-confluence.git "$HOME/Code/Publish to Confluence"
   ```

2. Link the folder as a personal skill:

   ```sh
   mkdir -p "$HOME/.claude/skills"
   ln -sfn "$HOME/Code/Publish to Confluence" "$HOME/.claude/skills/publish-to-confluence"
   ```

3. Run `claude mcp list`. If it lists no server with an `https://mcp.atlassian.com` address, add the Atlassian MCP server:

   ```sh
   claude mcp add --transport http --scope user atlassian "https://mcp.atlassian.com/v2/mcp?tools=all"
   ```

   The `?tools=all` ending makes the server offer all its tools, including the page history and comment tools the skill uses. If the list shows the server with an address that doesn't end that way, run `claude mcp remove atlassian` (with the name the list shows, if it isn't `atlassian`), then the command above.

4. Make your SETUP.md. When it opens in TextEdit, replace the text in parentheses after `Parent:` with your page or folder address, so the line reads like `Parent: https://example.atlassian.net/wiki/spaces/ABC/pages/123456/Product+notes`, and save.

   ```sh
   cp -n "$HOME/Code/Publish to Confluence/SETUP.example.md" "$HOME/Code/Publish to Confluence/SETUP.md"
   open -e "$HOME/Code/Publish to Confluence/SETUP.md"
   ```

5. Optional: make the token file and fill it in as [The token file](#the-token-file) describes.

   ```sh
   cp -n "$HOME/Code/Publish to Confluence/atlassian-api.env.example" "$HOME/Code/Publish to Confluence/atlassian-api.env"
   chmod 600 "$HOME/Code/Publish to Confluence/atlassian-api.env"
   open -e "$HOME/Code/Publish to Confluence/atlassian-api.env"
   ```

6. Restart Claude Code, and log in to the Atlassian MCP server through `/mcp` as described after the prompt.

## Publish a document

In Claude Code, type the command with the path to your markdown file:

```text
/publish-to-confluence path/to/file.md
```

The first publish creates a new page inside the page or folder from your SETUP.md, and later publishes of that file update the same page. The page title comes from the file's first `#` heading.

## The token file

An Atlassian API token lets the skill upload your images, turn links into cards and keep reviewers' comments attached when you republish. The skill reads it from `atlassian-api.env` in `~/Code/Publish to Confluence`, which the setup makes from `atlassian-api.env.example`, readable only by you. Git ignores this file, so it can't end up in the repo.

To create a token:

1. Open https://id.atlassian.com/manage-profile/security/api-tokens, the API tokens page under Security in your Atlassian account settings. Atlassian may email you a one-time code to confirm it's you.
2. Select "Create API token", not "Create API token with scopes": the skill can't use a token with scopes.
3. Give it a name, pick an expiry date (a year at most) and select "Create".
4. Select "Copy to clipboard". Atlassian won't show the token again.
5. Fill in both lines of `atlassian-api.env`, your Atlassian login email and the token, without spaces or quotes:

   ```text
   ATLASSIAN_EMAIL=you@example.com
   ATLASSIAN_API_TOKEN=your-token
   ```

Without a working token, your text still publishes through the Atlassian MCP server, but the skill asks before every publish and says what that publish will lose. A page can't be republished without the token if it holds images, or if someone added an info panel or any other panel, an expand section, an excerpt, a table of contents, or a Jira issue or Jira list with Confluence's Jira macro. The skill says so before changing anything. A page with cards from an earlier publish still republishes, and its cards turn back into plain links.

Uploading images also needs permission to add attachments in the page's space.

## Good to know

- Before each republish, the skill checks the page for edits made on Confluence since your last publish. It shows any it finds section by section, then asks whether to merge them into your file, overwrite them with your file, or stop.
- A merge shows exactly how your file will change and waits for your yes. It keeps a copy of your old file.
- With a working token, the skill turns panels, Jira macros and the like that someone added on Confluence into plain content before republishing, since Confluence won't take the update otherwise. A merge brings their content into your file: a panel as a quote, an expand section or an excerpt as its content, a Jira issue as a link that becomes a card, and a Jira list as a line like `Jira list: project = ABC`. It leaves out a table of contents, and the merge preview names each one.
- To keep your own words on a link instead of a card, add "plain" after the address: `[the epic](https://example.atlassian.net/browse/ABC-123 "plain")`. Write "block" there for a bigger card, or "embed" for an embedded view. If someone changes a link's look on Confluence, a merge writes the matching word after that link's address in your file ("plain", "block", "embed", or "embed wide" for a wide embedded view), so later publishes keep that look. Without a working token, links stay plain whatever you write there, and the word shows when someone hovers over the link.
- With a working token, when you reword the text a comment highlights, the comment moves with it, as long as the text is still recognizable. A comment on one or two words stays only while those exact words are there. A comment comes loose when the text it highlights is deleted, reworded past recognition, or matches more than one place, so the skill can't tell where it belongs. The skill asks before any publish that would do that.
- When you edit several look-alike list items or table rows in one publish, a comment on one of them may come loose instead of moving with the text it highlights (the skill asks first).
- Comments stay attached when the text they highlight has bold words, code or a link in it. A comment on a link's words stays on the card that replaces them. Resolved comments stay attached too while the text they highlight is still there, and the skill never asks about them.
- Each publish adds one version for your text to the page history, plus up to two minor versions for the skill's own changes, such as images, cards and comments.
- Mermaid diagrams show as code.

## Updating

Ask Claude to update the publish-to-confluence skill, or run `git pull` in the folder:

```sh
git -C "$HOME/Code/Publish to Confluence" pull
```

## Troubleshooting

| What you see | What to do |
|---|---|
| The skill says the token was rejected (401) | The token expired, was revoked or was mistyped. Create a new token as [The token file](#the-token-file) describes, then ask Claude to open `~/Code/Publish to Confluence/atlassian-api.env` in TextEdit. Replace the old token after `ATLASSIAN_API_TOKEN=` with the new one and save. Never paste it into the chat. |
| An image upload fails with a 403 | You don't have permission to add attachments in that space. Ask a space admin for it. |
| Claude can't reach Confluence | The Atlassian MCP server isn't connected, or needs you to log in again. Type `/mcp`, select the Atlassian MCP server and log in. If `/mcp` doesn't list it, paste the [setup prompt](#set-it-up) again; it adds the server and keeps your settings. |
| The skill says your organization blocks API tokens | Your text still publishes through the Atlassian MCP server, with the limits [The token file](#the-token-file) describes, and the skill asks before each publish. For images, cards and keeping comments attached, ask your Atlassian admin whether API tokens can be allowed for you. |
| You want your old file back after a merge | It's in `~/.claude/publish-to-confluence/backups/`, named after your file plus the date and time (UTC) of the merge. Finder hides that folder, so ask Claude to open it, or press Shift-Command-G in Finder and paste the folder's path. |
