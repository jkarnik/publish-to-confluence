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
- The script prints JSON. Read it whatever the exit code. Exit code 0 means OK. 1 means something partly failed, or that the command was wrong: `{"error": "usage: ..."}` means nothing ran, so correct the command and run it again. 2 means setup or the token is missing: `{"error": "setup", "setup": <state>}` or `{"error": "token", "token": <state>}`. `check` prints its own output with exit 2 too; step 1 says what each state means.
- Run `finish` once per publish. If it prints an `error` other than a usage error (which means nothing ran, as above), report it and don't run it again, even if the error says to: a rerun could hide someone else's edit from the next publish's check for Confluence edits.
- Only the script reads the token file. Never read it, print it or quote it. Opening it in TextEdit when the user asks is fine, since that doesn't show its contents to you.
- Confluence operations appear below by name, such as `getConfluenceContent`. Give each one `cloudId` set to the host in `check`'s `site`: `example.atlassian.net` for `https://example.atlassian.net/wiki`. If the Atlassian connection lists only tools that find and run operations, such as `discover` and `execute`, call each operation through `execute` by its name, with `cloudId` at the top level and the other parameters in `inputs`.

## Steps

1. **Check setup.** Run the script's `check` mode. It prints `{"setup", "parent", "site", "token", "tokenDetail"}`.
   - If `setup` isn't `ok`, fix SETUP.md as below, then run `check` again.
     - `missing` or `placeholder`: SETUP.md doesn't exist, or its `Parent:` line still holds the template's text. If it doesn't exist, copy `SETUP.example.md` to `SETUP.md`. Ask the user for the address of the Confluence page or folder that new pages should go under, copied from the browser's address bar, and write it after `Parent: ` in place of the template's text.
     - `short-link`: the address is a short `/wiki/x/...` link. Ask for the full address from the browser's address bar instead.
     - `invalid`: the address isn't a Confluence page or folder. A valid one is `https://<host>/wiki/...` ending in `/pages/<id>` or `/folder/<id>`, optionally followed by a title. Ask for it again.
   - Once `setup` is `ok`, `parent` is the address new pages go under and `site` is the Confluence site.
   - Decide on `token`, never on the wording of `tokenDetail`, which only explains it in plain words. `ok` means the token works. `missing` (no token file, or its values are empty), `invalid` (the token was refused, or the test read failed) and `blocked` (the user's organization blocks API tokens) all mean there's no working token: text still publishes, after step 6 asks permission. `unchecked` means the token file is filled in but wasn't tested, because `setup` isn't `ok`; the next `check` tests it.
2. **Find the file and its title.** The file is `$ARGUMENTS`. If that's empty, use the markdown file the user named, or ask which file to publish. Resolve it to an absolute path: that's the file's key in the index and the `<file>` that script modes take. If the file doesn't exist, say so and stop. The title is the text of the first line that starts with `# ` outside a code block, or the filename without its extension if there's no such line. Don't ask for a title.
3. **Prepare the body:** the file's markdown exactly as written, minus the title line. Don't convert it to HTML or change any wording. Steps 6, 7 and 8 send it as `body: {format: "markdown", value: <body>}`, even though those operations' own notes suggest HTML, a format guide or space instructions. A local image is an image whose address doesn't start with `http://`, `https://` or `data:`. With a working token, leave local images in, since `finish` uploads them. Without one, list them: their lines come out of the body once the user agrees in step 6, or in step 5's question.
4. **Look up the index.** Read the page index (a missing file counts as empty) and find the file's absolute path.
   - Not there: this is a first publish.
   - There: this is a republish of the entry's page. If the host in the entry's `url` isn't the host in `check`'s `site`, the page is on a different site from the one in SETUP.md: stop and say so. Otherwise read the page with `getConfluenceContent` (`content_id` = the entry's `pageId`, `detail: "summary"`) for its version, `metadata.version.number`, and its snapshot token.
   - If the page can't be read, stop, and never create a new page in its place. If Confluence says it isn't found or isn't allowed, say that the page may have been archived, deleted or hidden from the user, and that once it's restored on Confluence, publishing again updates it. For any other failure, say what went wrong.
5. **Check for Confluence edits (republish only).** If the page's version is higher than the entry's `version`, the page changed on Confluence since the last publish: follow "Confluence edits: merge or overwrite" below. It ends in a stop; an overwrite; a merge that has rewritten the file, after which you redo steps 2 and 3 for the new title and body; a yes to publishing the file as it is when a merge would change nothing in it; or, when there's nothing to merge, carrying on with no question.
6. **Ask permission when needed,** in one question that covers everything. If step 5 asked the user a question, its answer already covers these losses (they were in the overwrite choice or the merge preview), so skip this step.
   - **No working token:**
     - On a republish, first check whether the page refuses a text update, unless step 5 already did: run `updateConfluenceContent` with `dryRun: true`, `contentId` = `pageId`, the title, the body without its local image lines, and step 4's snapshot token. Confluence refuses a text update while the page shows an attached image or holds any macro other than a code block or status label, such as a Jira issue or list, a panel, an expand section or a table of contents. If it's refused, stop without asking anything: say why, and say that a working API token would fix it.
     - Then always ask, even if nothing would be lost. The question says why there's no working token (`tokenDetail` says it in plain words) and what this publish will lose: which local images won't upload and that links won't become cards. On a republish it adds that any cards on the page turn back into plain links, and lists every open inline comment as one that will come loose, quoting its highlighted text (`inlineOriginalSelection`): without a token there's no telling which comments are still attached, and a text update loosens them all. Get them with `listConfluenceComments` (`content-id` = `pageId`, `comment-type: "inline"`, `resolution-status: "open"`, `limit: 250`), passing each response's `nextCursor` back as `cursor` until a response has none.
   - **Working token, republish:** run `comments <pageId> <file>`. It prints `{"pageId", "open", "resolved", "willDetach"}`, and gives each open comment a `status`: `willReattach` (its text is still there), `willMove` (it moves onto its reworded text, `to`), `willDetach` (it will come loose) or `staysDetached` (it was already loose before this publish). Ask only if `willDetach` is above 0, and list only the `willDetach` comments: quote each one's `text` and give its `reason` in plain words (`textGone`: the highlighted text was deleted or reworded past recognition; `ambiguous`: it could belong to more than one place in the new text). Never ask about the other statuses or about resolved comments; step 9 reports them. If `comments` prints an `error`, stop and say why; nothing has changed.
   - **Working token, first publish:** nothing to ask.
   - Go on only after a clear yes. Anything else stops the publish, and nothing has changed.
7. **First publish.** Create the page with `createConfluenceContent`: `contentType: "page"` (not `live_doc`), `parent: {parentContentUrl: <check's parent>}`, the title and the body. Never retry it.
   - If Confluence refuses it and says why, such as no permission or a title already in use, say why and stop; no page was created.
   - If it fails any other way, such as a timeout or a server or connection error, or its result is unclear, the page may exist. Look for it before anything else, so that publishing again can't make a second one: list the parent's direct children with `getConfluenceContentDescendants` (`contentId` = the number after `/pages/` or `/folder/` in `parent`, `depth: 1`, `limit: 250`, and while a response has a `_links.next`, the `cursor` from it), and look for a page with exactly this title.
     - None: say that no page has appeared yet, and that the user should wait a few minutes and check the parent page before publishing again, since a slow create can still land. Stop.
     - One or more: read each as in step 4. If exactly one is at version 1 with the current user as its author (the summary's `metadata.version.author`; the user's ID is the `accountId` from `atlassianUserInfo`), it's the page this publish created: use its ID, version and web address in place of the response's below. Otherwise, such as a page at a higher version (it was there before this publish) or two or more that fit, leave them alone, say so, give the pages' addresses and stop.
   - Write the file's index entry from the response: the new page's ID as `pageId`, its version number as `version` and its web address as `url`. Create the index file if it doesn't exist.
   - With a working token, then run `finish <pageId> <file>` (without `--before`) and write its `version` into the entry. If it prints an `error` instead, the entry keeps the version from the create; step 9 reports the error.
8. **Republish.** When a check below calls off the publish, don't update the text, and leave the entry's `version` as it was. With a working token, if `prepare` saved an edit, run `finish <pageId> <file> --before <step 4's version>` to put back the images it swapped out. Then give step 9's short report.
   - With a working token, run `prepare <pageId> <file>`, adding `--overwrite` if step 5 ended in an overwrite, a merge or a yes to publishing the file as it is. The file is then what the page becomes, so `prepare` also takes off the page every embedded image the file doesn't use; the attachments stay on the page.
     - `prepare` makes plain, in one minor edit, what would make Confluence refuse the text update. It prints `{"pageId", "version", "unembedded", "madePlain", "removedUnreferenced"}`, plus `error` if it failed. `unembedded` counts images it turned back into placeholders and `removedUnreferenced` the embedded images it took off. `madePlain` counts what it made plain by kind: `jira` for Jira issues turned into links, `jiraList` for Jira lists turned into their query as text, or a macro's name, such as `info`, `expand` or `toc`, for one replaced by its content. `madePlain.unresolved`, a list, not a count, names Jira issues it couldn't turn into links.
     - It saved an edit if `unembedded`, `removedUnreferenced` or any count in `madePlain` (not `unresolved`) is above 0. That raises the page's version by 1, which is normal. An output with an `error` saved nothing, whether or not it has a `version`: its counts are 0 or missing.
     - If it prints an `error`, call off the publish and report the error.
     - If `madePlain.unresolved` lists any Jira issue, that issue is still on the page as a Jira issue macro, and Confluence refuses a text update while the page holds one: call off the publish. Name each issue, and say that the page can be published once those issues are removed from it on Confluence.
   - Read the summary again, as in step 4, for a fresh version and snapshot token. If the read fails, call off the publish and say why. This publish expects step 4's version, plus 1 if `prepare` saved an edit. If the fresh version is higher, someone edited the page during this publish: call off the publish, and tell the user in plain words that the page changed on Confluence while they were publishing and that publishing again will show what changed and ask what to do. Otherwise note the fresh version as `before`.
   - Update the page with `updateConfluenceContent`: `contentId` = `pageId`, the title, the body and the fresh snapshot token. Leave out `minorEdit`: the text update is a normal edit. The script asks for its own edits to be minor, though Confluence records them as normal versions. Never retry a failed update, even though the operation's notes say to re-read the page and try again: a retry could overwrite an edit someone just made. If the update succeeds, write the new version number from the response into the entry's `version`.
   - With a working token, run `finish <pageId> <file> --before <before>`, even if the update failed, because it puts back the images that `prepare` swapped out. If the update succeeded, write `finish`'s `version` into the entry, unless `finish` printed an `error`. If its output has `"editedDuringPublish": true`, keep the version from the text update's response instead, and tell the user that someone edited the page during this publish, so the next publish will show their edit. If the update failed, leave the entry's `version` as it was, so the next publish's check for Confluence edits still sees anything edited in the meantime.
9. **Report** to the user in plain words:
   - created or updated, with the page title and URL
   - whether Confluence edits were merged, with the backup's path, or overwritten
   - what `prepare` made plain so Confluence would accept the update, by kind (`madePlain`), such as "2 Jira issues turned into links, an info panel into plain text, and a table of contents taken out", and how many embedded images it took off because the file doesn't use them (`removedUnreferenced`; the attachments stay on the page)
   - images uploaded (`uploaded`), unchanged (`unchanged`), failed (`failed`, with each error) or left out (`missingLocally`: the file isn't where the markdown points; `stripped`: it couldn't upload, so it was taken off the page; `notOnPage`: the page had no place for it); how many links became cards (`cards.made`, which includes the bigger cards and embedded views that `cards.tagged` counts), and any links kept plain so a comment stays attached (`cards.keptPlainForComment`)
   - comments re-attached (`comments.reattached`); each moved comment, old wording → new (`comments.moved`, `from` → `to`); each detached comment with its highlighted text and the reason (`comments.detached`, `text` and `reason`: `textGone`, its text was deleted or reworded past recognition; `ambiguous`, it could belong to more than one place; `noBefore`, the page's earlier version couldn't be read, so only an exact match was tried); comments that were already loose before this publish (`comments.stillDetached`); and, as a count, resolved comments that couldn't be re-attached because their text is gone (`comments.resolved.notFound`). Resolved comments that re-attached aren't mentioned.
   - anything that failed, and any `warning` from `finish`

   Without a working token, report the losses the user agreed to in step 6, or in step 5's question.

   When the text wasn't updated, because step 8 called off the publish or the update failed, give a short report instead: that the text on Confluence didn't change, and why; and, if they ran, what `prepare` made plain, which stays that way on the page, and what `finish` put back (`embedded` images), and anything it couldn't (`error`, `failed`), since those images stay as placeholders until the next publish.

## Hard constraints

- Never delete or unpublish a page.
- Never touch a page that isn't in the index for this file. A file that has an entry always updates that page and never gets a second one.
- Never hand-convert markdown. The script's REST edits change only images, link looks (cards), the elements `prepare` must make plain, and comment markers. They never change the text the user wrote.
- Run the script only against the page in this file's index entry.
- Never change the local file without the user's explicit sign-off on the merge preview.
- Never ask the user technical questions. The exceptions are the permission questions about what a publish will lose, and the merge-or-overwrite question with its preview and clash picks.

## Confluence edits: merge or overwrite

Step 5 sends a republish here when the page's version is higher than the entry's `version`. Without a working token, run step 6's `dryRun` check first; step 6 then doesn't run it again. If the page refuses the update, stop as step 6 says, before showing any change or asking anything. A page that passes shows no attached image, so without a token a merge never downloads one.

### Find the edits

- Run `diffConfluenceContentVersions` (`contentId` = `pageId`, `from_version` = the entry's `version`, `to_version` = step 4's version) twice: with `content_format: "markdown"` for the text, and with `"html"` for what the markdown hides or flattens (cards, images, mentions, Jira issues and lists, status labels, panels, expand sections, excerpts and tables of contents). The html diff can put each version's whole body on a single line, so look inside those lines for the items that differ.
- Comment highlights never count as edits. In the html diff they're `<span class="annotation" … data-annotation-type="inlineComment">`.
- There are no edits when `from.title` matches `to.title`, the markdown diff has `diff.empty` true, and the html diff is empty too or differs only in comment highlights and editor leftovers with no words (see "Compare with the file"). That happens when a publish that didn't finish left the script's own edits behind. Carry on with step 6 and say nothing about Confluence edits.
- If a diff fails, for example because the entry's version can't be read anymore, compare the current page with the file instead: `getConfluenceContent` (`content_id` = `pageId`, `detail: "full"`) with `content_format` `"markdown"`, then `"html"`. Treat every difference that isn't just formatting as a possible Confluence edit, and in a merge as a clash, since there's no earlier version to show which side changed it. Leave out differences that are only formatting, such as bold or a heading level: the formatting rule under "Compare with the file" doesn't apply here.
- Find who made the edits with `listConfluenceContentVersions` (`contentId` = `pageId`, `limit: 250`). It lists versions newest first, each with a `number`, an `authorId` and a `message`. Until the results cover every version above the entry's, pass each response's next-page cursor back as `cursor`, and stop if a response has none. The edits are the versions above the entry's, leaving out the current user's versions whose message starts with "Finished the update:" or ends with "before republishing": those are the script's own. If a version has no message, count it.
- Say "you" for the current user, whose ID is the `accountId` from `atlassianUserInfo` (no parameters, not even `cloudId`). Name other people: the newest version's author is in step 4's summary (`metadata.version.author.displayName`), and `getJiraUser` (`accountId` = the `authorId`) looks up anyone else. If that lookup fails or isn't allowed, or gives no name, say "someone else" and carry on.

### Compare with the file

Find each change's passage in the file by its words, since the export writes some things its own way, such as a card as `<URL>`. Then check it against the file:

- The file has the after side: it already has the change, which doesn't count.
- The file still has the before side: the change is missing from the file.
- The file has neither: the file changed the same passage since the last publish too. That's a clash.
- Changes with no words and nothing a reader would see, such as empty paragraphs, trailing spaces and `data-local-id` attributes, aren't edits; leave them out.
- A change whose before and after have the same words is a formatting edit, such as bold, a heading level, a list, a panel or a status label's colour. The file has it only if it has that formatting too, written its own way (a panel as a blockquote, for example); otherwise it's missing.
- A card look the file would produce anyway doesn't count either: an inline card on a link the file has, or a Jira issue the file links by the same key. Compare the key in `/browse/ABC-123`, since the page may show the issue's address on a different host.
- When unsure whether the file has a change, count it as missing.
- If nothing is missing and nothing clashes, say in one line that the page was edited on Confluence but the file already has those edits, and carry on with step 6.

### Show what changed and ask

Ask one question with three answers: merge, overwrite or stop.

- List by section what was added, deleted or changed, each with a short snippet (before → after for a change, or what a formatting edit did, such as "made bold"), and list rich items by kind: card, embedded view, Jira issue or list, image, mention, status label, panel, expand section, excerpt or table of contents. Say which changes the file already has, and which passages the file changed too.
- Say how many edits there were and who made them.
- The overwrite answer says that the page will match the file and that the Confluence edits stay in the page history. It also gives what step 6's question would, so this one answer covers it: the losses, worked out as step 6 does, and without a working token, why there's none (`tokenDetail`).

```
This page was edited on Confluence after your last publish (7 edits, all by you):
  Title         changed   "Checkout redesign" → "Checkout redesign scope"
  Scope         changed   "…covers 12 sources…" → "…covers 9 sources…"
  Stages        deleted   3 subsections
  Related work  added     Jira card ABC-123, a Jira list, an embedded video, an image, a mention
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

- **Clashes.** If any passage clashes, settle it first, in its own question. Show both versions of each one, the file's and Confluence's, and ask the user to pick one for each or write what they want instead. If the answer settles only some of them, ask again about the others. Go on once every clash has an answer. An answer that settles none of them stops the publish, and nothing has changed.
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
  | An expand section or an excerpt | its title, if it has one, as a bold line, then its content |
  | A Jira list: `data-extension-key="jira"` with a `jqlQuery` | the plain text `Jira list: <JQL>` |
  | A table of contents | left out |
  | An image: `<div data-type="media" … data-id="…" data-alt="…">` | `![alt](path)`, with `data-alt` as the alt text |
  | Anything else markdown can't hold | plain text, or left out |

  - When Confluence changed the look of a link the file has, put the tag on the file's own link and keep its words. A link that's new from Confluence uses its URL as its text.
  - For an image, find its attachment. `listConfluenceAttachments` (`contentId` = `pageId`, `limit: 250`) gives each attachment's `id` and `title`, which is its filename; while a response has a next-page cursor, pass it back as `cursor` for the rest. `getConfluenceAttachment` (`attachmentId` = the `id`) gives its `fileId`, which matches the image's `data-id`. If no attachment matches, leave the image out, and the preview names it as something the file can't hold.
  - The image's path is in the folder the file's other images use, or `images/` next to the file, under the attachment's filename: `prepare` needs that name to match the image on the page. In the markdown, write each space in the path as `%20`, such as `![Launch timeline](images/Launch%20timeline.png)`. If a file of that name is already there, stop and say so; nothing has changed. It's downloaded after the sign-off, under Apply.
- **Preview.** Run `preview-merge <file> <proposed>`, which compares the file with the proposal section by section. It prints `{"identical", "changes": [{"section", "kind", "before", "after"}]}`. If it prints an `error` instead, stop and say why; nothing has changed. Show each change under its section as a snippet: added, deleted, or changed with before → after. `preview-merge` calls the `# ` title line and the text under it, up to the next heading, `Title`: show a change to the `# ` line as the title, and any other change there as the opening text. `(top)` is text before the title; call it the start of the file. Then name each image to be downloaded and where it goes, and each item the file can't hold and what it becomes: plain text, a blockquote, a bold title and its content, or left out. Add the losses this publish would still have, worked out as step 6 does but for the proposal: with a working token, that's `comments <pageId> <proposed>`; without one, also say why there's none (`tokenDetail`). Then ask for sign-off.

  ```
  If you merge, your file changes like this:
    Title          ~ changes "Checkout redesign" → "Checkout redesign scope"
    Related work   + adds    a link to ABC-123 (becomes a card)
                   + adds    the Jira list, as the text "Jira list: project = ABC"
                   + adds    the embedded video, kept as an embed
                   + adds    the image "Rollout plan", saved as images/rollout-plan.png
                   + adds    the mention of Alex Kim, as plain text
  Nothing else in your file changes. A copy of your current file is kept.
  Merge and publish?
  ```

  If `identical` is true, the merge changes nothing in the file. Say so in place of the changes, say which Confluence edits this publish will take off the page, give the losses as above, and ask whether to publish the file as it is. A clear yes skips Apply and carries on with step 6, and step 8 adds `--overwrite`.
- **Sign-off.** Only a clear yes counts. Any other answer stops the publish, and the file and the page stay as they are.
- **Apply.** First download each image the proposal adds, once per attachment: run `download <pageId> <filename> <dest>`, with the attachment's `title` as `<filename>`, quoted like the paths, and the image's absolute path, with real spaces (the `%20` form is only for the markdown), as `<dest>`. It prints `{"pageId", "filename", "saved", "bytes"}`. Then run `apply-merge <file> <proposed>`. It backs the file up, moves the proposal into its place and prints `{"file", "backup"}`; step 9 reports the backup's path. If a download or `apply-merge` prints an `error` instead, delete the images this Apply already saved (each `saved` path), so they can't block the next merge, then stop and say why (after a failed download, also that the file hasn't changed). Otherwise the publish carries on with the merged file, as step 5 says, and step 8 adds `--overwrite`.
