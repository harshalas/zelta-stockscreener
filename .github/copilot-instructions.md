# GitHub Copilot instructions


<!-- github-copilot-toolbox:mcp-skills-awareness-begin -->

### MCP & Skills awareness (GitHub Copilot Toolbox)

_Last synced: 2026-06-22T00:31:57.746Z._

- **Full report:** `.github/copilot-toolbox-mcp-skills-awareness.md` in this workspace (auto-overwritten on each scan). Use it as ground truth for configured servers and skill folders.
- **MCP:** For **live tools**, use **Copilot Chat → Agent** and **trust/start** the right servers in the MCP UI.
- **When the user’s task matches a server** (e.g. “open this Confluence page” and a **Confluence** / **Atlassian** MCP is listed), **prefer that server id** and plan on Agent + MCP for actions—not only file search.
- **Skills:** Folders below contain `SKILL.md`; attach or cite paths in chat when relevant.

#### Workspace MCP

- `c:\git\zelta-stockscreener\.vscode\mcp.json` _(workspace: zelta-stockscreener)_ — _file missing_

_No active workspace servers in mcp.json._

#### User MCP

- `C:\Users\harsh\AppData\Roaming\Code\User\mcp.json` — _file missing_

_No active user-scoped servers in mcp.json._

#### Project skills

_None found (or no workspace open)._

#### User skills

_None found._

<!-- github-copilot-toolbox:mcp-skills-awareness-end -->

<!-- github-copilot-memory-bank:begin -->
# Plan / Act workflow (Cursor-style)

Unless the user clearly opts out (e.g. **"skip plan, implement now"** or **"just fix it"** with no ambiguity), use **two modes**. This matches Cursor’s PLAN → approve → ACT flow.

## Plan mode (default)

- **First line of every Plan-mode response MUST be exactly:** `# Mode: PLAN`
- **Do not modify the repository in any way**, including:
  - No creating, editing, or deleting files (source, config, docs, **including `./memory-bank/**` memory-bank files**).
  - No applying multi-file edits, quick fixes, or patch-style changes.
  - No terminal commands that change the workspace (installs, builds that write outputs you were asked to apply, `git` writes, etc.).
- **Allowed in Plan mode:** Read/search files to understand the codebase, answer questions, list steps, identify risks, and produce a **written plan** (markdown).
- **End Plan-mode responses** by telling the user how to proceed, e.g. **Type `ACT` when you approve this plan** (or ask them to refine the plan first).

## Act mode

- Enter **only** when the user’s message **clearly approves implementation**, e.g. they send **`ACT`**, **`act`**, or phrases like **"go ahead"**, **"implement the plan"**, **"approved"** right after a plan—or they explicitly told you to skip planning and implement.
- **First line of every Act-mode response MUST be exactly:** `# Mode: ACT`
- **Then** you may edit files, run commands, and update **`./memory-bank/`** when appropriate.
- After you finish an Act-mode turn, assume the next user message starts in **Plan mode** again unless they again approve with **`ACT`** (or equivalent) for further edits.

## If the user asks for code changes while you are in Plan mode

- **Do not implement.** Respond with `# Mode: PLAN`, briefly restate or adjust the plan, and ask them to type **`ACT`** when they want you to apply changes.

---

# Memory bank (persistent context)

This repository uses a **memory bank** under `./memory-bank/` — structured markdown that survives sessions, similar to Cursor-style workflows.

Context layers (read deeper files after foundations): **projectbrief** → **productContext** / **systemPatterns** / **techContext** → **activeContext** → **progress**.

## What Copilot should do

1. **Before substantive work**, read **all** of the following under `./memory-bank/` when the task depends on project state (not optional for non-trivial work). In **Plan mode**, reading for the plan is allowed; **do not edit** these files until **Act mode** unless the user only asked for a documentation/memory update with no code change.
   - `projectbrief.md` — scope and goals
   - `productContext.md` — product intent and UX
   - `systemPatterns.md` — architecture and conventions
   - `techContext.md` — stack and constraints
   - `progress.md` — done / pending / known issues
   - `activeContext.md` — current task and decisions

2. **During Act-mode work**, keep `activeContext.md` aligned with the current task (update when focus shifts).

3. **After meaningful milestones** (in Act mode), update `progress.md` and any affected docs in `./memory-bank/`.

4. When the user asks to **update memory bank** (or similar), **open and review every** file in `./memory-bank/`, then update what changed — especially `activeContext.md` and `progress.md`, even if other files are unchanged. Prefer doing heavy memory-bank writes in **Act mode** unless the user asked for documentation-only updates.

5. Prefer **short, factual updates** over long prose. Reference files, symbols, and tickets instead of duplicating code.

Do not delete these files; evolve them as the project changes.
<!-- github-copilot-memory-bank:end -->
