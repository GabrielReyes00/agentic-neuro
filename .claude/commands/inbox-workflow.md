---
name: inbox_workflow
description: Agentic email triage pipeline — fetches Exchange inbox for a specified time window, categorizes messages, extracts action items as reminders and calendar events, and guides response drafting with user approval. Always invoke this skill when the user wants to check, process, or triage their email inbox — phrases like "go through my inbox", "triage my emails", "check my mail", "what emails do I have", "process my inbox", "inbox triage", or when they mention catching up on email over a time window. Do not attempt to answer inline for these requests.
---

# Inbox Workflow

Multi-phase email triage: fetch Exchange inbox, categorize, generate reminders/events, draft responses with mandatory approval.

> **CRITICAL: No email sent without explicit user approval. Zero exceptions.**

---

## Voice Profile (Gabriel Reyes)

All Phase 4 drafts written AS Gabriel. Internalize as natural tendencies.

**Greetings:**
| Context | Greeting |
|---|---|
| Attending/supervisor (any thread) | `Good [morning/afternoon/evening] Dr. [Last],` |
| Peer — first in thread | `Good [morning/afternoon/evening] [Dr./Mr./Mrs.] [Last],` |
| Peer — reply in thread | `Hi [Dr./Mr./Mrs.] [Last],` |
| Personal | `Hi [First],` |

Time: morning <12PM, afternoon 12-5PM, evening >5PM.

**Opening**: One brief, warm, contextual line after greeting. Never generic.

**Answer-First Structure (RIGID)**: Greeting → opening → **answer in first content sentence** → support (1-2 max) → sign-off. Never restate sender's question. Never explain what you're about to say before saying it.

**Sign-off**: Providing info → `Best, Gabriel`. Someone helping Gabriel → `Thank you for the help, Gabriel`. New external → `Best, Gabriel Reyes`.

**Length**: Minimum sentences that leaves nothing unanswered. Apply cut test.

**Format**: Always prose. Never bullets/lists. Professional, never stiff. Contractions fine.

**BANNED phrases**: "I hope this email finds you well", "Please don't hesitate to reach out", "Feel free to reach out", "I wanted to follow up on...", "Thank you for your email", "Thank you for reaching out", "I am writing to...", "I was wondering if perhaps...", any question restatement.

---

## Parameter Extraction

Extract `DAYS_BACK` from natural language. If unspecified, ask.

## Phase 1: Collect & Categorize (Subagent, `model: "haiku"`)

> Fetch emails from Exchange Inbox for last `DAYS_BACK` days via AppleScript (`osascript`). Extract: Subject, Sender, Date, Body (truncate 2000 chars).
> Categorize each: **Requires Response** | **Action Item** | **Event Invite** | **Notification** | **Newsletter**.
> Summarize each in 1-3 specific sentences (dates, deadlines, names). Return structured JSON only — no raw bodies.

## Phase 2: Dashboard

Present categorized tables by category (most recent first). Each has columns: #, From, Date, Summary. Summary must be specific enough to understand without reading original.

## Phase 3: Actionables

### 3A: Reminders
Extract tasks/deadlines from ALL categories. Present numbered list with title, source, due date. On approval, create via AppleScript (`tell application "Reminders"`).

### 3B: Calendar Events
Extract events with dates/times. Present numbered list. On approval, create via AppleScript (`tell application "Calendar"`, Exchange calendar).

Then ask: "Ready to draft responses?"

## Phase 4: Response Drafting

### Voice Calibration (once per session, subagent `model: "sonnet"`)

> Check `data/Sessions/voice_profile_cache.json` (<24h). If valid, return cached. Otherwise fetch 5 recent sent emails from Exchange via AppleScript, analyze writing patterns, produce voice profile JSON, cache it. Return profile only — no raw email bodies.

### Sequential Drafting Loop

For each "Requires Response" email:

1. **Present context**: From, Date, Subject, Context summary, Key asks. Offer "skip".
2. **User input**: Response guidance.
3. **Draft (subagent, `model: "sonnet"`)**: Re-fetch full email body via AppleScript. Draft reply applying Voice Profile rules (greeting, answer-first, sign-off, banned phrases). Self-check: forbidden phrases? Answer in first sentence? Removable sentences? Sounds human? Return finished draft only.
4. **Approval gate (MANDATORY)**: "yes" → send via AppleScript. "revise: [feedback]" → re-draft. "skip" → next email.

### Sending
```applescript
tell application "Mail"
    set newMsg to make new outgoing message with properties {subject:"Re: ...", content:"...", visible:false}
    tell newMsg
        make new to recipient at end of to recipients with properties {address:"..."}
    end tell
    send newMsg
end tell
```

### Completion Summary
Emails triaged, reminders created, events created, responses sent/skipped.

## Error Handling
- Mail not responding → inform user
- No emails → inform user
- Send failure → do NOT retry, offer to save draft text
- Permission errors → instruct user to grant Automation access
