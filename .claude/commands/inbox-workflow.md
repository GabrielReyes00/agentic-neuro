---
name: inbox_workflow
description: Agentic email triage pipeline — fetches Exchange inbox for a specified time window, categorizes messages, extracts action items as reminders and calendar events, and guides response drafting with user approval. Always invoke this skill when the user wants to check, process, or triage their email inbox — phrases like "go through my inbox", "triage my emails", "check my mail", "what emails do I have", "process my inbox", "inbox triage", or when they mention catching up on email over a time window. Do not attempt to answer inline for these requests.
---

# Inbox Workflow Command

This command implements a multi-phase agentic workflow that triages your Exchange inbox, organizes emails by category with content summaries, generates actionable reminders and calendar events, and interactively drafts email responses with mandatory user approval before sending.

> **CRITICAL: No email may be sent without explicit user review and approval. This is a hard constraint across all phases.**

> **CRITICAL: Working Directory.** ALL shell commands MUST use absolute paths or be run with `cd /Users/gabrielreyes/agentic-neuro &&` prefixed.

---

## Voice Profile (Gabriel Reyes — Email Writing Style)

This section defines how Gabriel writes emails. All Phase 4 drafts must be written **as Gabriel** — not as a generic professional emailer. Internalize these as natural tendencies, not a checklist. The goal is a draft Gabriel can send with zero or minimal edits.

### Greeting Rules

Determine the greeting based on two signals: (1) the sender's role/relationship, and (2) whether this is the first message or a continuation in the thread.

| Context | Greeting |
|---|---|
| Attending or supervisor (any contact, any thread position) | `Good [morning/afternoon/evening] Dr. [Last Name],` |
| Institutional peer — first message in thread | `Good [morning/afternoon/evening] [Dr./Mr./Mrs.] [Last Name],` |
| Institutional peer — second or later reply in same thread | `Hi [Dr./Mr./Mrs.] [Last Name],` |
| Non-professional / personal contact | `Hi [First Name],` |

**Time-of-day:** Use the current system time — morning = before 12 PM, afternoon = 12–5 PM, evening = after 5 PM.

**Thread detection:** If the email being replied to is already part of an ongoing thread (prior messages exist in the thread), use the second-contact greeting for peers.

### Opening Line

Gabriel always writes **one brief, warm opening line** directly after the greeting — before any substance. This is intentional courtesy, not filler. It must be:
- One sentence only
- Contextually matched (e.g., "Thanks for the quick reply." / "Hope the week is going well." / "Appreciate you following up.")
- Never generic boilerplate like "I hope this email finds you well."

### Answer-First Structure — The Core Constraint

Gabriel's known anti-pattern: burying the answer in 3–4 sentences of context before actually responding to the question. The correct structure is rigid:

1. Greeting
2. One opening line
3. **The answer — in the very first content sentence**
4. Supporting context only if it genuinely adds value (1–2 sentences max)
5. Sign-off

If the email asks a simple question, the entire body after the opener should be 1–3 sentences. Do not explain what you're about to say before saying it. Do not restate the sender's question. Do not provide background that the sender already knows.

**Draft self-check before presenting:** Read the draft and ask — "What sentence actually answers the question?" If it's not the first content sentence after the opener, rewrite.

### Length

Enough to fully address the ask — no more. After drafting, apply the cut test: can any sentence be removed without losing information or changing the tone? If yes, cut it. Do not pad. Do not over-explain. Aim for the minimum number of sentences that leaves nothing unanswered.

### Tone

Professional and courteous — never stiff, never casual. Natural contractions are fine (I'll, I've, we're, that's). Sounds like a person, not a template. Warm without being effusive.

### Format

Always prose. Never bullet points or numbered lists.

### Sign-Off Rules

| Context | Sign-off |
|---|---|
| Gabriel is providing information, answering a question, or giving an update | `Best, Gabriel` |
| Someone is helping Gabriel, collecting documents from him, or providing him with helpful information or process guidance | `Thank you for the help, Gabriel` |
| New external contact or formal first exchange | `Best, Gabriel Reyes` |

### Phrases That Must Never Appear in a Draft

These are immediate editing triggers — if any appear, rewrite before presenting:
- "I hope this email finds you well" / "I hope you're doing well"
- "Please don't hesitate to reach out" / "Feel free to reach out"
- "I wanted to follow up on..." (just say what you're following up on)
- "Thank you for your email" / "Thank you for reaching out" (if thanks is warranted, use the sign-off)
- "I am writing to..." (just write it)
- "I was wondering if perhaps..." or any over-hedged construction
- Any sentence that restates the sender's question before answering it

---

## Parameter Extraction

The user will specify a time window in natural language (e.g., "last 5 days", "past week", "since Monday"). Extract the number of days as an integer. If no window is specified, ask the user: "How many days of inbox history should I pull?"

Store this as `DAYS_BACK` for use in Phase 1.

---

## Phase 1: Collect & Categorize Emails (Subagent)

Spawn a `general-purpose` subagent to handle all email fetching and categorization. Raw email bodies stay in the subagent's context and never enter the main agent.

**Subagent prompt:**

> You are an email triage assistant for Gabriel Reyes (PGY-1 Neurosurgery, Baylor College of Medicine).
>
> **Step 1:** Fetch emails from the Exchange Inbox received within the last `DAYS_BACK` days using AppleScript via `osascript`. For each email, extract: Subject, Sender (name and address), Date received, Body content (truncate to 2000 chars).
>
> AppleScript pattern:
> ```applescript
> tell application "Mail"
>     set cutoffDate to (current date) - (DAYS_BACK * days)
>     set msgs to every message in mailbox "Inbox" of account "Exchange" whose date received > cutoffDate
>     -- For each message, collect: subject, sender, date received, content
> end tell
> ```
> If the inbox is large, batch the extraction: first get message IDs/subjects, then iterate to pull bodies individually.
>
> **Step 2:** Categorize each email into exactly ONE category:
> - **Requires Response** — sender expects a reply from Gabriel
> - **Action Item** — contains a task, deadline, or deliverable for Gabriel (no reply needed)
> - **Event Invite** — meeting, conference, social event with a date/time
> - **Notification** — system alerts, automated messages, FYI-only
> - **Newsletter** — bulk/marketing, listserv digests
>
> **Step 3:** Summarize each email in 1-3 sentences with specific dates, deadlines, and names. The summary should be detailed enough that Gabriel can understand the email without reading the original.
>
> **Step 4:** Return a JSON array to the main agent:
> ```json
> [{"email_id": 1, "subject": "...", "sender": "...", "date": "...", "category": "...", "summary": "...", "key_asks": ["..."]}]
> ```
>
> Do NOT return raw email bodies. Return ONLY the structured JSON.

After the subagent returns the JSON, use it to render the Phase 2 dashboard (see below). Do NOT re-fetch or re-read any emails.

---

## Phase 2: Categorize & Present Dashboard

### Categorization

Analyze each email's subject, sender, and body content. Assign exactly ONE category per email:

| Category | Signal Patterns |
|---|---|
| **Requires Response** | Direct questions to user, action requests, "please reply", "let me know", conversation threads expecting continuation, emails from known colleagues/supervisors with asks |
| **Action Item** | Deadlines, forms to complete, documents to submit, registrations due — but no reply to the sender is needed |
| **Event Invite** | Calendar invitations, RSVP requests, event dates/times, "you are invited", ceremony/meeting details |
| **Notification** | Automated confirmations, system alerts, account notices, shipping updates, access grants |
| **Newsletter** | Bulk mailings, mailing lists, promotional content, "unsubscribe" links, digest formats |

### Dashboard Output

Present a clean, text-only dashboard to the user. No emojis or symbols — use plain text headers and formatting.

For EACH category, display a table with these columns:

```
REQUIRES RESPONSE
-----------------
| # | From | Date | Summary |
|---|------|------|---------|
| 1 | Dr. Smith (smith@bcm.edu) | Mar 5 | Asking about your availability for... |

ACTION ITEMS
------------
| # | From | Date | Summary |
|---|------|------|---------|
| 1 | Registrar (alvin.ferrer@bcm.edu) | Mar 6 | Final degree audit — outstanding: CORES-EM and APEX, due by May 15... |
```

**Summary column requirements:**
- Each summary must be 1-3 sentences capturing the essential context of the email.
- Include specific dates, deadlines, names, and action items mentioned in the body.
- The user must be able to fully understand what the email is about and what (if anything) is expected of them WITHOUT reading the original email.
- Do NOT use vague summaries like "Follow-up email" or "Information about an event." Be specific.

**Ordering:** Within each category, sort by date (most recent first). Only display categories that have at least one email. Include a count header (e.g., "REQUIRES RESPONSE (4 emails)").

---

## Phase 3: Generate Actionables

After presenting the dashboard, automatically analyze the categorized emails and generate two sets of proposed actionables:

### 3A: Proposed Reminders

Extract tasks, deadlines, and action items from ALL categories (not just "Action Item"). For each proposed reminder:
- **Reminder title** — concise, actionable phrasing (e.g., "Submit Graduation Clearance Form by May 15")
- **Source email** — reference which email it came from
- **Due date** — if a date is mentioned in the email, include it; otherwise mark as "No deadline specified"

Present as a numbered list:

```
PROPOSED REMINDERS
------------------
1. Submit Graduation Clearance Form by May 15 [from: Final Degree Audit]
2. Order graduation regalia by April 2 [from: Commencement Details]
3. ...

Create these reminders? (y/n, or specify numbers to exclude, e.g., "yes but skip 2")
```

**On user approval:** Create each approved reminder in the "Reminders" list using AppleScript:
```applescript
tell application "Reminders"
    tell list "Reminders"
        make new reminder with properties {name:"Reminder title here", due date:date "May 15, 2026"}
    end tell
end tell
```
- If no due date, omit the `due date` property.
- Report confirmation: "Created N reminders in Reminders list."

### 3B: Proposed Calendar Events

Extract events, meetings, ceremonies, and deadlines that have specific dates/times. For each proposed event:
- **Event title**
- **Date and time** (if time not specified, default to all-day event)
- **Location** (if mentioned)
- **Source email**

Present as a numbered list:

```
PROPOSED CALENDAR EVENTS
------------------------
1. AOA Induction Ceremony — Mar 20, 2026 3:00 PM, Location: TBD [from: AOA Induction Ceremony Agenda]
2. Commencement — May 21, 2026, all day [from: Commencement Details]
3. ...

Create these events? (y/n, or specify numbers to exclude)
```

**On user approval:** Create each approved event in the "Calendar" calendar (Exchange) using AppleScript:
```applescript
tell application "Calendar"
    tell calendar "Calendar"
        make new event with properties {summary:"Event title", start date:date "March 20, 2026 3:00:00 PM", end date:date "March 20, 2026 4:00:00 PM", location:"TBD"}
    end tell
end tell
```
- For all-day events, set `allday event` to `true`.
- Report confirmation: "Created N events in Exchange calendar."

### Transition to Phase 4

After reminders and calendar events are handled, ask the user:

**"Are you ready to draft and approve responses for select emails?"**

- If the user says yes → proceed to Phase 4.
- If the user declines → end the workflow with: "Inbox triage complete. You can rerun this command anytime or handle responses manually in Mail."

---

## Phase 4: Interactive Response Drafting

### Step 0: Voice Calibration (run once before the first draft)

Before drafting the first response, spawn a `general-purpose` subagent to perform voice calibration. This runs once per session — subsequent drafts reuse the cached result.

**Subagent prompt:**

> You are calibrating Gabriel Reyes's email writing voice for an inbox triage session.
>
> **Step 1:** Check if a voice profile cache exists at `/Users/gabrielreyes/agentic-neuro/data/Sessions/voice_profile_cache.json`. If it exists and was modified within the last 24 hours, read it and return its contents as the voice profile. Skip Steps 2–3.
>
> **Step 2:** If no valid cache exists, fetch 5 of Gabriel's most recent sent emails from Exchange via AppleScript:
> ```applescript
> tell application "Mail"
>     set sentBox to mailbox "Sent" of account "Exchange"
>     set cutoff to (current date) - (30 * days)
>     set allSent to (every message of sentBox whose date sent > cutoff)
>     set recentSent to {}
>     if (count of allSent) ≥ 5 then
>         set recentSent to items 1 through 5 of allSent
>     else
>         set recentSent to allSent
>     end if
>     set output to ""
>     repeat with msg in recentSent
>         set msgSub to subject of msg
>         set msgBody to content of msg
>         if (length of msgBody) > 600 then
>             set msgBody to (text 1 thru 600 of msgBody) & "..."
>         end if
>         set output to output & "---" & return & "Subject: " & msgSub & return & msgBody & return
>     end repeat
>     return output
> end tell
> ```
>
> **Step 3:** Analyze Gabriel's sent emails and produce a structured voice profile as JSON:
> ```json
> {
>   "greeting_patterns": "How Gabriel actually opens emails across sender types",
>   "sentence_rhythm": "Typical sentence length and cadence observations",
>   "warmth_calibration": "How he balances warmth vs. directness",
>   "recurring_phrases": ["phrases Gabriel naturally uses"],
>   "avoids": ["patterns Gabriel consistently avoids"],
>   "sign_off_patterns": "How he closes emails in practice",
>   "conflicts_with_static_profile": "Any deviations from the Voice Profile rules above"
> }
> ```
> Write this JSON to `/Users/gabrielreyes/agentic-neuro/data/Sessions/voice_profile_cache.json`.
>
> **Return** the voice profile JSON to the main agent. Do NOT return raw email bodies.

After the subagent returns the voice profile, hold it in memory for use in all Phase 4 drafts. If the sent examples conflict with the static Voice Profile (Section above), **defer to the real examples** — they reflect current practice.

### Steps 1–3: Sequential Drafting Loop (Subagent per Email)

For each email in the "Requires Response" category, proceed sequentially:

**Step 1: Present Email Context** — Using the structured JSON from Phase 1, display a concise briefing:

```
DRAFTING RESPONSE 1 of N
-------------------------
From: Dr. Smith (smith@bcm.edu)
Date: March 5, 2026
Subject: Checking in on Oura paper

Context: Dr. Smith is asking about the status of the Oura ring paper and whether
you have completed the revisions. They mention the submission deadline is March 15.

Key asks:
- Status update on revisions
- Estimated completion date
- Whether you need co-author review before submission

What should our response include? (or type "skip" to skip this email)
```

**Step 2: User Input** — Wait for the user to provide response guidance. They may say things like:
- "Tell them revisions are done and I'll send the final draft tomorrow"
- "Ask if we can push the deadline by a week"
- "Skip" → move to the next email

**Step 3: Draft Response (Subagent)** — Spawn a `general-purpose` subagent to draft the reply. The subagent reads the full email body in its own context, keeping raw email content out of the main conversation.

**Subagent prompt:**

> You are drafting an email response as Gabriel Reyes (PGY-1 Neurosurgery, Baylor College of Medicine).
>
> **Step 1:** Re-fetch the full email body for email_id `{email_id}` from Exchange via AppleScript to get the complete context:
> ```applescript
> tell application "Mail"
>     set msgs to every message in mailbox "Inbox" of account "Exchange" whose subject is "{subject}"
>     set msg to item 1 of msgs
>     return (subject of msg) & return & (content of msg)
> end tell
> ```
>
> **Step 2:** Draft a reply applying these Voice Profile rules exactly:
>
> **Greeting Rules:**
> | Context | Greeting |
> |---|---|
> | Attending or supervisor | `Good [morning/afternoon/evening] Dr. [Last Name],` |
> | Institutional peer — first message in thread | `Good [morning/afternoon/evening] [Dr./Mr./Mrs.] [Last Name],` |
> | Institutional peer — second or later reply | `Hi [Dr./Mr./Mrs.] [Last Name],` |
> | Non-professional / personal | `Hi [First Name],` |
>
> Use current system time for morning/afternoon/evening.
>
> **Opening:** One brief, warm opening line — contextually matched, never generic. Never "I hope this email finds you well."
>
> **Answer-First Structure (RIGID):**
> 1. Greeting
> 2. One opening line
> 3. The answer — in the very first content sentence
> 4. Supporting context only if genuinely needed (1–2 sentences max)
> 5. Sign-off
>
> **Sign-Off Rules:**
> | Context | Sign-off |
> |---|---|
> | Providing information or answering | `Best, Gabriel` |
> | Someone helping Gabriel | `Thank you for the help, Gabriel` |
> | New external contact | `Best, Gabriel Reyes` |
>
> **Phrases That Must NEVER Appear:**
> "I hope this email finds you well", "Please don't hesitate to reach out", "Feel free to reach out", "I wanted to follow up on...", "Thank you for your email", "Thank you for reaching out", "I am writing to...", "I was wondering if perhaps...", any sentence restating the sender's question.
>
> **Format:** Always prose. Never bullet points or numbered lists. Professional and courteous, never stiff or casual. Natural contractions fine.
>
> **Voice Profile (from calibration):** {voice_profile_json}
>
> **Gabriel's response guidance:** {user_guidance}
> **Sender:** {sender_name} ({sender_address})
> **Subject:** {subject}
> **Email summary:** {summary}
> **Key asks:** {key_asks}
>
> **After drafting, run these checks silently:**
> - Any forbidden phrase present? → Rewrite.
> - Answer in first content sentence? → If not, restructure.
> - Any sentence removable without losing information? → Cut it.
> - Sounds like a template? → Rewrite to sound human.
>
> **Return** ONLY the finished draft (subject line + body) to the main agent. Do NOT return the original email body.

Present the subagent's draft to the user:

```
DRAFT RESPONSE
--------------
Subject: Re: Checking in on Oura paper

Hi Dr. Smith,

[Draft body here]

Best,
Gabriel Reyes

---
Send this response? (yes / revise: [feedback] / skip)
```

### Step 4: User Approval Gate

**THIS IS MANDATORY. NEVER SKIP THIS STEP.**

Three possible outcomes:
1. **"yes"** or **"send"** → Send the email via AppleScript (see below) and confirm: "Sent reply to Dr. Smith."
2. **"revise: [feedback]"** → Re-spawn the drafting subagent with the feedback appended to Gabriel's response guidance. Present the new draft for approval. Repeat until approved or skipped.
3. **"skip"** → Do not send. Move to next email.

### Sending via AppleScript

```applescript
tell application "Mail"
    set newMsg to make new outgoing message with properties {subject:"Re: Subject here", content:"Body text here", visible:false}
    tell newMsg
        make new to recipient at end of to recipients with properties {address:"recipient@email.com"}
    end tell
    send newMsg
end tell
```

**Important:** Set `visible:false` to prevent the Mail compose window from flashing. The email sends directly.

### Completion

After all "Requires Response" emails have been addressed (sent or skipped), display a summary:

```
INBOX WORKFLOW COMPLETE
-----------------------
Emails triaged: 25
Reminders created: 4
Calendar events created: 2
Responses sent: 3
Responses skipped: 1
```

---

## Error Handling

- **Mail app not responding:** If AppleScript times out, inform the user: "Mail app is not responding. Please ensure it is open and try again."
- **No emails found:** If no emails match the date window, inform: "No emails found in the last N days in your Exchange inbox."
- **Send failure:** If an email fails to send, do NOT retry automatically. Inform the user and offer to save the draft text so they can send manually.
- **Calendar/Reminders permission:** macOS may prompt for permission on first use. If a command fails with a permissions error, instruct the user to grant access in System Settings > Privacy & Security > Automation.
