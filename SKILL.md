---
name: publish-to-confluence
description: Publish a markdown file to Confluence, creating its page the first time and updating the same page after that. Use when the user runs /publish-to-confluence with a file path, or asks to publish, share or update a markdown file, such as a PRD or product note, on Confluence. Uploads local images, turns web links into cards and re-attaches reviewers' inline comments.
argument-hint: "[file]"
---

# Publish to Confluence

Publish one markdown file to Confluence. The first publish creates a page under the parent set in SETUP.md, and later publishes of the same file update that page. With a working API token, the skill also uploads local images, turns web links into cards and re-attaches reviewers' inline comments. Follow the steps in order.

## Where things are

| What | Where |
|---|---|
| Script | `python3 -I "<this skill's base directory>/scripts/confluence_rest.py" <mode> ...` |
| SETUP.md | `<this skill's base directory>/SETUP.md`, with the template `SETUP.example.md` next to it |
| Token file | `<this skill's base directory>/atlassian-api.env` |
| Page index | `~/.claude/publish-to-confluence-index.json`: each published file's absolute path → `{pageId, version, url}` |
| Backups | `~/.claude/publish-to-confluence/backups/<stem>-<YYYYmmddTHHMMSSZ>.md` |
| Merge proposals | `~/.claude/publish-to-confluence/proposals/<stem>-proposed.md` |

- This skill's base directory is the folder that holds this SKILL.md: `${CLAUDE_SKILL_DIR}`. `<stem>` is the file's name without its extension. Quote every path in a command, since paths can contain spaces.
- The script prints JSON. Exit code 0 means OK, 1 that something partly failed, and 2 that setup or the token is missing. With a token problem it prints `{"error": "token", "token": <state>}`. Read the JSON whatever the exit code.
- Only the script reads the token file. Never open it, print it or quote it.
- Confluence operations appear below by name, such as `getConfluenceContent`. Give each one `cloudId` set to the host in `check`'s `site`: `example.atlassian.net` for `https://example.atlassian.net/wiki`.

## Steps

1. **Check setup.** Run the script's `check` mode. It prints `{"setup", "parent", "site", "token", "tokenDetail"}`.
   - If `setup` isn't `ok`, fix SETUP.md as below, then run `check` again.
     - `missing` or `placeholder`: SETUP.md doesn't exist, or its `Parent:` line still holds the template's text. If it doesn't exist, copy `SETUP.example.md` to `SETUP.md`. Ask the user for the address of the Confluence page or folder that new pages should go under, copied from the browser's address bar, and write it after `Parent: ` in place of the template's text.
     - `short-link`: the address is a short `/wiki/x/...` link. Ask for the full address from the browser's address bar instead.
     - `invalid`: the address isn't a Confluence page or folder. A valid one is `https://<host>/wiki/...` ending in `/pages/<id>` or `/folder/<id>`, optionally followed by a title. Ask for it again.
   - Once `setup` is `ok`, `parent` is the address new pages go under and `site` is the Confluence site.
   - `token` is `ok` when the token works. `missing` (no token file, or its values are empty), `invalid` (the token was refused, or the read failed; `tokenDetail` says why) and `blocked` (the user's organization blocks API tokens) all mean there's no working token: text still publishes, after step 6 asks permission. `unchecked` shows only while `setup` isn't `ok`.
2. **Find the file and its title.** The file is `$ARGUMENTS`. If that's empty, use the markdown file the user named, or ask which file to publish. Resolve it to an absolute path: that's the file's key in the index and the `<file>` that script modes take. If the file doesn't exist, say so and stop. The title is the text of the first line that starts with `# ` outside a code block, or the filename without its extension if there's no such line. Don't ask for a title.
3. **Prepare the body:** the file's markdown exactly as written, minus the title line. Don't convert it to HTML or change any wording. Steps 7 and 8 send it as `body: {format: "markdown", value: <body>}`, even though those operations' own notes suggest HTML, a format guide or space instructions. A local image is an image whose address doesn't start with `http://`, `https://` or `data:`. With a working token, leave local images in, since `finish` uploads them. Without one, list them: their lines come out of the body once the user agrees in step 6.
4. **Look up the index.** Read the page index (a missing file counts as empty) and find the file's absolute path.
   - Not there: this is a first publish.
   - There: this is a republish of the entry's page. If the entry's `url` is on a different site from `check`'s `site`, stop and say so. Otherwise read the page with `getConfluenceContent` (`content_id` = the entry's `pageId`, `detail: "summary"`) for its version, `metadata.version.number`, and its snapshot token. If the page can't be read, stop and say why; don't create a new page in its place.
5. **Check for Confluence edits (republish only).** If the page's version is higher than the entry's `version`, the page changed on Confluence since the last publish: follow "Confluence edits: merge or overwrite" below. It ends in a stop, an overwrite, or a merge that has rewritten the file. After a merge, redo steps 2 and 3 for the new title and body.
6. **Ask permission when needed,** in one question that covers everything. If step 5 already asked the user a question, these losses were part of it (with the overwrite choice, or in the merge preview), so don't ask again.
   - **No working token:** always ask, even if nothing would be lost.
     - On a republish, first check whether the page refuses a text update: run `updateConfluenceContent` as in step 8, with `dryRun: true`. If it's refused, which happens when the page holds images or cards from an earlier publish, stop without asking anything: say so, and say that a working API token would fix it.
     - The question says why there's no working token, in plain words from `token` and `tokenDetail`, and what this publish will lose: which local images won't upload, and that links won't become cards. On a republish it also lists the open inline comments that will detach, quoting each one's highlighted text. Get them with `listConfluenceComments` (`content-id` = `pageId`, `comment-type: "inline"`, `resolution-status: "open"`, following `nextCursor` until there are no more). That filter also returns comments whose highlighted text was already lost; leave those out, since this publish doesn't detach them, and mention them in the report.
   - **Working token, republish:** run `comments <pageId> <file>`. It prints `{"pageId", "open", "resolved", "willDetach"}`. Ask only if `willDetach` is above 0, and list each open comment whose `status` is `willDetach`: quote its `text` and give its `reason` in plain words (`textGone`: the highlighted text was deleted or reworded past recognition; `ambiguous`: it could belong to more than one place in the new text). Don't ask about `willMove` comments, which move onto their new wording (`to`), or `staysDetached` ones, which were detached before this publish; step 9 reports both. Resolved comments are never part of the question. If `comments` fails, stop and say why; nothing has changed.
   - **Working token, first publish:** nothing to ask.
   - Go on only after a clear yes. Anything else stops the publish, and nothing has changed.
7. **First publish.** Create the page with `createConfluenceContent`: `contentType: "page"` (not `live_doc`), `parent: {parentContentUrl: <check's parent>}`, the title and the body. Write the file's index entry from the response: the new page's ID as `pageId`, its version number as `version` and its web address as `url`. Create the index file if it doesn't exist. With a working token, then run `finish <pageId> <file>` (without `--before`) and write its `version` into the entry.
8. **Republish.** When a check below calls off the publish, don't update the text, and leave the entry's `version` as it was. With a working token, if `prepare` saved an edit, also run `finish <pageId> <file> --before <step 4's version>` to put back the images and cards it took out.
   - With a working token, run `prepare <pageId> <file>`, adding `--overwrite` if the user chose to overwrite in step 5.
     - If its output has an `error`, it saved an edit only if its `version` is higher than step 4's. Call off the publish, report the error and stop.
     - If there's no `error`, it saved an edit when its output shows anything unembedded, unmade, made plain or removed (`unembedded`, `cardsUnmade`, `madePlain`, `removedUnreferenced`). That edit raises the page's version by 1, which is normal.
   - Read the summary again, as in step 4, for a fresh version and snapshot token. This publish expects step 4's version, plus 1 if `prepare` saved an edit. If the fresh version is higher, someone edited the page during this publish: call off the publish, tell the user in plain words that the page changed on Confluence while they were publishing and that publishing again will show what changed and ask what to do, and stop. Otherwise note the fresh version as `before`.
   - Update the page with `updateConfluenceContent`: `contentId` = `pageId`, the title, the body and the fresh snapshot token. Never retry a failed update, even though the operation's notes say to re-read the page and try again: a retry could overwrite an edit someone just made. If the update succeeds, write the new version number from the response into the entry's `version`.
   - With a working token, run `finish <pageId> <file> --before <before>` even if the update failed, because it restores the images and cards that `prepare` took out. If the update succeeded, write `finish`'s `version` into the entry. If it failed, leave the entry's `version` as it was, so the next publish's check for Confluence edits still sees anything edited in the meantime.
9. **Report** to the user in plain words:
   - created or updated, with the page title and URL
   - whether Confluence edits were merged, with the backup's path, or overwritten
   - images uploaded (`uploaded`), unchanged (`unchanged`), failed (`failed`, with each error) or left out (`missingLocally`, `stripped`, `notOnPage`); how many links became cards (`cards.made`), and any links kept plain so a comment stays attached (`cards.keptPlainForComment`)
   - comments re-attached (`comments.reattached`); each moved comment, old wording → new (`comments.moved`, `from` → `to`); each detached comment with its highlighted text and the reason (`comments.detached`); comments that were already detached before this publish (`comments.stillDetached`); and resolved comments re-attached, as a count (`comments.resolved.reattached`)
   - anything that failed, and any `warning` from `finish`

   Without a working token, report the losses the user agreed to in step 6, including any comments that were already detached.

## Hard constraints

- Never delete or unpublish a page.
- Never touch a page that isn't in the index for this file. A file that has an entry always updates that page and never gets a second one.
- Never hand-convert markdown. The script's REST edits change only images, link looks (cards), the elements `prepare` must make plain, and comment markers. They never change the text the user wrote.
- Run the script only against the page in this file's index entry.
- Never change the local file without the user's explicit sign-off on the merge preview.
- Never ask the user technical questions. The exceptions are the permission questions about lost images and comments, and the merge-or-overwrite question with its preview and clash picks.

<!-- D4 appends "Confluence edits: merge or overwrite" below -->

## Confluence edits: merge or overwrite

Step 5 sends a republish here when the page's version is higher than the entry's `version`. Without a working token, first run step 6's `dryRun` check. The page refuses a text update when it shows an attached image or holds a macro other than a code block or status label, such as a Jira issue or list, a panel, an expand section or a table of contents. Cards and mentions don't cause a refusal, though without a token the page's cards turn back into plain links. If the update would be refused, stop before showing any change or asking anything: say so, and say that a working API token would fix it.

### Find the edits

- Run `diffConfluenceContentVersions` (`contentId` = `pageId`, `from_version` = the entry's `version`, `to_version` = step 4's version) twice: with `content_format: "markdown"` for the text, and with `"html"` for what the markdown hides or flattens (cards, Jira issues and lists, images, mentions, status labels and panels). The html diff can put each version's whole body on a single line, so look inside those lines for the items that differ.
- Comment highlights never count as edits. In the html diff they're `<span class="annotation" … data-annotation-type="inlineComment">`.
- There are no edits when `from.title` matches `to.title`, the markdown diff has `diff.empty` true, and the html diff is empty too or differs only in comment highlights. That happens when a publish that didn't finish left the script's own edits behind. Carry on with step 6 and say nothing about Confluence edits.
- If a diff fails, for example because the entry's version can't be read anymore, compare the current page with the file instead: `getConfluenceContent` (`content_id` = `pageId`, `detail: "full"`) with `content_format` `"markdown"`, then `"html"`. Treat every difference that isn't just formatting as a possible Confluence edit, and in a merge as a clash, since there's no earlier version to show which side changed it.
- Find who made the edits with `listConfluenceContentVersions` (`contentId` = `pageId`, `limit` = step 4's version minus the entry's, at most 250). Each result has a `number`, an `authorId` and `minorEdit`. The edits are the versions above the entry's, leaving out the current user's minor edits (`minorEdit` true): the script saves its own edits that way. If that leaves none, count them all.
- Say "you" for the current user, whose ID is the `accountId` from `atlassianUserInfo`. Name other people: the newest version's author is in step 4's summary (`metadata.version.author.displayName`), and `getJiraUser` (`accountId` = the `authorId`) looks up anyone else. If no name comes back, say "someone else".

### Compare with the file

Check each change in the diffs against the file by its words, not its formatting: the export shows a card as `<URL>`, for example.

- The file has the after side: it already has the change, which doesn't count.
- The file still has the before side: the change is missing from the file.
- The file has neither: the file changed the same passage since the last publish too. That's a clash.
- A card look the file would produce anyway doesn't count either: an inline card on a link the file has, or a Jira issue the file links by the same key. Compare the key in `/browse/ABC-123`, since the page may show the issue's address on a different host.
- When unsure whether the file has a change, count it as missing.
- If nothing is missing and nothing clashes, say in one line that the page was edited on Confluence but the file already has those edits, and carry on with step 6.

### Show what changed and ask

Ask one question with three answers: merge, overwrite or stop.

- List by section what was added, deleted or changed, each with a short snippet (before → after for a change), and list rich items by kind: card, embedded view, Jira issue or list, image, mention, status label or panel. Say which changes the file already has, and which passages the file changed too.
- Say how many edits there were and who made them.
- The overwrite answer says that the page will match the file and that the Confluence edits stay in the page history. It also gives the losses step 6 would ask about, worked out as step 6 does, so this one answer covers them.

```
This page was edited on Confluence after your last publish (7 edits, all by you):
  Title         changed   "Checkout redesign" → "Checkout redesign scope"
  Scope         changed   "…covers 12 sources…" → "…covers 9 sources…"
  Stages        deleted   3 subsections
  Related work  added     Jira card ABC-123, an embedded video, an image, a mention
Your file already has the Scope and Stages changes.
Merge the rest into your file, overwrite with your file, or stop?
  Merge: I'll show you how your file would change before changing anything.
  Overwrite: the page will match your file. These edits stay in the page history.
    1 comment will detach: "owned by the payments team" (that text isn't in your file).
  Stop: nothing changes.
```

- **Stop:** say that nothing has changed, and stop the publish. An answer that isn't clearly merge or overwrite is a stop.
- **Overwrite:** carry on with step 6, which doesn't ask again. Step 8 adds `--overwrite`.
- **Merge:** follow "Merge" below.

### Merge

- **Clashes.** If any passage clashes, settle it first, in its own question. Show both versions of each one, the file's and Confluence's, and ask the user to pick one for each or write what they want instead. Go on only when every clash has an answer. Anything else stops the publish, and nothing has changed.
- **Propose.** Write the proposal (`<proposed>` below) to `~/.claude/publish-to-confluence/proposals/<stem>-proposed.md`, creating the folder if needed. It's the file plus the missing Confluence changes and the clash answers, in the file's own markdown style, with nothing else changed. Text, headings, lists and tables come in as markdown. A title changed on Confluence changes the file's `# ` title line, or adds one at the top if the file has none. The rest comes in like this:

  | On the page (html diff) | In the proposal |
  |---|---|
  | A new inline card: `data-card-appearance="inline"` | `<URL>`, as the markdown diff shows it |
  | A block card: `data-type="block-card"` | `[text](URL "block")` |
  | An embedded view: `embed` in its markup, such as `embedCard` or `data-card-appearance="embed"` | `[text](URL "embed")`, or `"embed <layout>"` when it has a `layout` or `data-layout`, such as `"embed wide"` |
  | A card turned back into a plain link | `[text](URL "plain")` |
  | A Jira issue macro: a link to `…/browse/ABC-123` | `[ABC-123](<that address>)`, which becomes a card |
  | A mention: `data-type="mention"` | the name in plain text, as the markdown diff shows it: `@Alex Kim` |
  | A status label: `data-type="status"` | its text |
  | A panel: `data-type="panel-info"` and the like | a blockquote |
  | An expand section or an excerpt | its content |
  | A Jira list: `data-extension-key="jira"` with a `jqlQuery` | the plain text `Jira list: <JQL>` |
  | A table of contents | left out |
  | An image: `<div data-type="media" … data-id="…" data-alt="…">` | `![alt](path)`, with `data-alt` as the alt text |
  | Anything else markdown can't hold | plain text, or left out |

  - When Confluence changed the look of a link the file has, put the tag on the file's own link and keep its words. A link that's new from Confluence uses its URL as its text.
  - For an image, find its attachment. `listConfluenceAttachments` (`contentId` = `pageId`) gives each attachment's `id` and `title`, which is its filename. `getConfluenceAttachment` (`attachmentId` = the `id`) gives its `fileId`, which matches the image's `data-id`.
  - The image's path is in the folder the file's other images use, or `images/` next to the file, under the attachment's filename: `prepare` needs that name to match the image on the page. If a file of that name is already there, stop and say so; nothing has changed. It's downloaded after the sign-off, under Apply.
- **Preview.** Run `preview-merge <file> <proposed>`, which compares the file with the proposal section by section. It prints `{"identical", "changes": [{"section", "kind", "before", "after"}]}`. Show each change under its section as a snippet: added, deleted, or changed with before → after. Then name each image to be downloaded and where it goes, what the file can't hold (each item that comes in as plain text or a blockquote, or is left out), and the losses this publish would still have, worked out as step 6 does but for the proposal: with a working token, that's `comments <pageId> <proposed>`. Then ask for sign-off.

  ```
  If you merge, your file changes like this:
    Title          ~ changes "Checkout redesign" → "Checkout redesign scope"
    Related work   + adds    a link to ABC-123 (becomes a card)
                   + adds    the embedded video, kept as an embed
                   + adds    the image "Rollout plan", saved as images/rollout-plan.png
                   + adds    the mention of Alex Kim, as plain text
  Nothing else in your file changes. A copy of your current file is kept.
  Merge and publish?
  ```

  If `identical` is true, the merge changes nothing in the file. Say so in place of the changes, say which Confluence edits this publish will take off the page, and ask whether to publish anyway. A clear yes skips Apply and carries on with step 6.
- **Sign-off.** Only a clear yes counts. Any other answer stops the publish, and the file and the page stay as they are.
- **Apply.** First download each image the proposal adds to its planned path. With a working token, run `download <pageId> <filename> <dest>`, with the attachment's `title` as `<filename>` and the path as `<dest>`. Without one, run `downloadConfluenceAttachment` (`attachmentId` = the attachment's `id`, `outputPath` = the image's absolute path), then run the `downloadCommand` it returns. If a download fails, stop and say why; the file hasn't changed. Then run `apply-merge <file> <proposed>`. It backs the file up, moves the proposal into its place and prints `{"file", "backup"}`; step 9 reports the backup's path. If it prints an `error` instead, stop and say why. Otherwise the publish carries on with the merged file, as step 5 says.
