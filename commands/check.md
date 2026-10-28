---
name: check
description: Check a file, URL, or pasted text with writing-flow and propose focused rewrites.
argument-hint: <path, URL or pasted text>
---

Run the `writing-flow` CLI through the Bash tool.

- For a file or URL, pass it as an argument: `writing-flow check "$ARGUMENTS"`.
- For pasted text, send it through stdin with a quoted heredoc delimiter. Keep the delimiter in the command quoted so the shell does not expand the text:

  ```sh
  writing-flow check - <<'WRITING_FLOW_TEXT'
  pasted text goes here
  WRITING_FLOW_TEXT
  ```

Group the findings by rule. Propose a rewrite for each blocking finding. Do not edit files unless the user asks.
