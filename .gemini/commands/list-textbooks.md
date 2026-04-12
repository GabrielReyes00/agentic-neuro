---
name: list_textbooks
description: Query the LanceDB inventory and list all ingested textbooks/sources with chunk counts. Use whenever user asks what books/sources are loaded.
---

# List Textbooks Command

Use shell prefix:

```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate"
eval "$RUN" && python3 src/lance_retriever.py list_textbooks
```

Present output as a clean inventory table (title/source + chunk count).
