---
name: list_textbooks
description: Queries the RAG vector database and displays a formatted inventory of all ingested textbooks and sources with per-source chunk counts. Always invoke this skill when the user asks what textbooks, books, or sources are available — "what textbooks do you have", "list the books", "what's loaded", "inventory". Do not attempt to answer inline for these requests.
---

# List Textbooks Command

This command retrieves a list of all textbooks currently ingested in the local vector database (`neurosurgery_v4 (LanceDB)`) and presents them to the user as a clean inventory table.

> **CRITICAL: Working Directory.** ALL shell commands in this command MUST be prefixed with `cd /Users/gabrielreyes/agentic-neuro &&`. The CLI may be running from `~`, not from `~/agentic-neuro/`.

## Step 1: Fetch the Inventory

Run the following command to retrieve the textbook inventory directly from the local RAG database:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/lance_retriever.py list_textbooks
```

## Step 2: Present the Output

The script outputs a Rich table summarizing the contents of the database (textbook title and total number of chunks). Present this information cleanly to the user. You can simply display the output of the script or re-format it into a Markdown table for an even cleaner look.
