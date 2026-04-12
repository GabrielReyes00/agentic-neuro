---
name: inbox_workflow
description: Agentic inbox triage pipeline — fetch, categorize, extract action items, propose reminders/events, and draft replies with explicit approval gates.
---

# Inbox Workflow Command

Multi-phase: fetch + categorize → dashboard → reminders/events → draft replies.

**No email sent without explicit user approval. Zero exceptions.**

## Working Rules

1. Raw email bodies stay in sub-task context; main context holds structured JSON only
2. Never bypass approval gate
3. Use deterministic `message_id` for refetching and replying

## Voice Profile (Gabriel Style)

### Greetings
| Context | Greeting |
|---|---|
| Attending/supervisor | `Good [morning/afternoon/evening] Dr. [Last],` |
| Peer, first message | `Good [morning/afternoon/evening] [Title] [Last],` |
| Peer, ongoing thread | `Hi [Title] [Last],` |
| Personal | `Hi [First],` |

### Structure (Answer-First, Rigid)

Greeting → one warm opener → **answer in first content sentence** → support (1-2 max) → sign-off. Never restate sender's question.

### Sign-Off

Standard: `Best, Gabriel` | Recipient helping: `Thank you for the help, Gabriel` | Formal external: `Best, Gabriel Reyes`

### Forbidden Phrases

"I hope this email finds you well", "Please don't hesitate to reach out", "Feel free to reach out", "I wanted to follow up on...", "Thank you for your email/reaching out", "I am writing to...", over-hedged constructions, restating sender's question.

## Parameter Extraction

Parse time window from input. If absent, ask for days-back value.

## Phase 1: Collect + Categorize (Sub-task)

Delegate: fetch Exchange inbox for `DAYS_BACK`. Return structured JSON per email: `email_id`, `message_id`, `subject`, `sender`, `date`, `category`, `summary`, `key_asks`. Categories: `Requires Response` | `Action Item` | `Event Invite` | `Notification` | `Newsletter`. No raw bodies in main context.

## Phase 2: Dashboard

Category tables (most recent first): index, sender, date, specific summary. Show counts, hide empty categories.

## Phase 3: Actionables

**3A Reminders**: Extract tasks/deadlines → present numbered list → on approval, create via AppleScript.
**3B Calendar Events**: Extract events with date/time → present → on approval, create via AppleScript.

Then ask: proceed to response drafting?

## Phase 4: Interactive Response Drafting

### Step 0: Voice Calibration (once)

Sub-task: check cache (<24h), else sample recent sent emails → voice profile JSON → cache. Profile: greeting_patterns, sentence_rhythm, warmth, recurring phrases, avoids, sign_offs, conflicts with static profile.

### Steps 1-3: Sequential Draft Loop

Per "Requires Response" email:
1. Present context (From, Date, Subject, Key asks). Offer skip.
2. Capture user guidance
3. Sub-task: refetch by `message_id`, draft applying voice profile + answer-first + forbidden phrases. Prose only.

### Step 4: Approval Gate (Mandatory)

`yes/send` → send via AppleScript + confirm | `revise: ...` → redraft + re-present | `skip` → next. Never auto-send.

## Completion

Summarize: emails triaged, reminders created, events created, responses sent/skipped.

```bash
rm -f /Users/gabrielreyes/agentic-neuro/data/Sessions/voice_profile_cache.json
```

## Error Handling

Mail unavailable → report + stop safely. No emails → report. Send failure → no auto-retry. Permissions → instruct macOS Automation settings.
