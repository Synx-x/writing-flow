---
description: Show what the harness changed about what you read.
argument-hint: "[--limit N]"
---

Show what the harness changed about what you read.

Arguments: $ARGUMENTS

## What this command does

Prints the rewrite log as before-and-after pairs. A display-only rewrite
never reaches the saved transcript, so this listing is the only record of
the difference between what the model wrote and what reached your screen.

## Step 1: Print the log

Run:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plain_log.py" $ARGUMENTS
```

Pass `--limit N` to change how many records appear. The default is 20.

## Step 2: Report

Show the output as it stands. Do not summarise it. The point of the listing
is the exact before and after text.
