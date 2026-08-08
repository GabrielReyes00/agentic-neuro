# Inbox Workflow

Use when the user asks to check, triage, or process email. No email is ever sent without explicit approval.

## Parameter

Extract the time window. If absent, ask for days back.

## Phase 1: Collect and Categorize

Fetch Exchange inbox mail for the requested window. Keep raw bodies out of main context. Return structured JSON per message: id, subject, sender, date, category, summary, key asks.

Categories: Requires Response, Action Item, Event Invite, Notification, Newsletter.

## Phase 2: Dashboard

Show counts and compact tables by category, most recent first. Hide empty categories.

## Phase 3: Actions

For action items, propose reminders with due date, title, and source email. For events, propose calendar entries with time, location, attendees, and uncertainty. Ask approval before creating reminders or events.

## Phase 4: Draft Replies

Draft replies only for messages the user selects. Never send. Ask explicit approval before any send step.

Gabriel voice:

| Element | Rule |
|---|---|
| Attending/supervisor greeting | `Good [morning/afternoon/evening] Dr. [Last],` |
| Peer first message | `Good [morning/afternoon/evening] [Title] [Last],` |
| Peer ongoing thread | `Hi [Title] [Last],` |
| Personal | `Hi [First],` |
| Structure | greeting, brief contextual opener, answer in first content sentence, support, sign-off |
| Sign-off | `Best, Gabriel`; helper: `Thank you for the help, Gabriel`; formal external: `Best, Gabriel Reyes` |

Forbidden: "I hope this email finds you well", "Please don't hesitate to reach out", "Feel free to reach out", "I wanted to follow up on", "Thank you for your email", "Thank you for reaching out", "I am writing to", restating the sender's question, and over-hedging.

Keep prose short, answer-first, and professional.
