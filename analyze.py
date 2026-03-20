#!/usr/bin/env python3
"""
Linear Sales — Gong Call Analyzer v5
======================================
Architecture:
  0. Load internal Gong user IDs
  1. Fetch calls + metadata (trailing 30 days)
  2. Fetch transcripts
  3. Claude (Haiku, parallel) — extract ALL prospect questions from full transcripts
  4. Claude (Sonnet) — stratified sample → discover categories from data
  4b. Claude (Sonnet) — generate one-sentence description per category
  5. Claude (Sonnet, parallel) — classify every question
  6. Claude (Sonnet, map-reduce) — cluster within each category
  7. Match clusters to resources (Linear docs + Notion internal)
  8. Write two-panel interactive HTML report

Checkpointing:
  extracted_questions.json  — skip step 3 with --use-cache
  classified_questions.json — skip steps 3-5 with --use-classified-cache
"""

import os, sys, json, re, time, threading, random
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import requests
import anthropic

# Auto-load .env
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Gong credentials (loaded from .env) ───────────────────────────────────────
GONG_BASE = "https://us-25690.api.gong.io"
GONG_AUTH = (
    os.environ.get("GONG_ACCESS_KEY", ""),
    os.environ.get("GONG_ACCESS_SECRET", ""),
)

NOW       = datetime.now(timezone.utc)
FROM_DATE = (NOW - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
TO_DATE   = NOW.strftime("%Y-%m-%dT23:59:59Z")

# ── Linear public docs (curated — used for external resource matching) ─────────
LINEAR_DOCS = [
    # Getting started & core concepts
    {"title": "Getting Started",               "url": "https://linear.app/docs/start-guide"},
    {"title": "Conceptual Model",              "url": "https://linear.app/docs/conceptual-model"},
    {"title": "How to Use Linear",             "url": "https://linear.app/docs/how-to-use-linear"},
    # Issues
    {"title": "Creating Issues",               "url": "https://linear.app/docs/creating-issues"},
    {"title": "Editing Issues",                "url": "https://linear.app/docs/editing-issues"},
    {"title": "Sub-issues",                    "url": "https://linear.app/docs/parent-and-sub-issues"},
    {"title": "Issue Relations",               "url": "https://linear.app/docs/issue-relations"},
    {"title": "Issue Templates",               "url": "https://linear.app/docs/issue-templates"},
    {"title": "Labels",                        "url": "https://linear.app/docs/labels"},
    {"title": "Estimates",                     "url": "https://linear.app/docs/estimates"},
    {"title": "Due Dates",                     "url": "https://linear.app/docs/due-dates"},
    {"title": "SLAs",                          "url": "https://linear.app/docs/sla"},
    {"title": "Customer Requests",             "url": "https://linear.app/docs/customer-requests"},
    # Triage & intake
    {"title": "Triage",                        "url": "https://linear.app/docs/triage"},
    {"title": "Triage Intelligence",           "url": "https://linear.app/docs/triage-intelligence"},
    # Workflow
    {"title": "Workflows & Statuses",          "url": "https://linear.app/docs/configuring-workflows"},
    # Teams & workspace structure
    {"title": "Teams",                         "url": "https://linear.app/docs/teams"},
    {"title": "Sub-teams",                     "url": "https://linear.app/docs/sub-teams"},
    {"title": "Members & Roles",               "url": "https://linear.app/docs/members-roles"},
    {"title": "Private Teams",                 "url": "https://linear.app/docs/private-teams"},
    {"title": "Workspaces",                    "url": "https://linear.app/docs/workspaces"},
    # Projects & planning
    {"title": "Projects",                      "url": "https://linear.app/docs/projects"},
    {"title": "Project Milestones",            "url": "https://linear.app/docs/project-milestones"},
    {"title": "Project Status & Updates",      "url": "https://linear.app/docs/initiative-and-project-updates"},
    {"title": "Initiatives",                   "url": "https://linear.app/docs/initiatives"},
    {"title": "Sub-initiatives",               "url": "https://linear.app/docs/sub-initiatives"},
    {"title": "Timeline",                      "url": "https://linear.app/docs/timeline"},
    {"title": "Releases",                      "url": "https://linear.app/docs/releases"},
    # Cycles
    {"title": "Cycles",                        "url": "https://linear.app/docs/use-cycles"},
    {"title": "Updating Cycles",               "url": "https://linear.app/docs/update-cycles"},
    # Views & reporting
    {"title": "Custom Views",                  "url": "https://linear.app/docs/custom-views"},
    {"title": "Filters",                       "url": "https://linear.app/docs/filters"},
    {"title": "Insights & Analytics",          "url": "https://linear.app/docs/insights"},
    {"title": "Dashboards",                    "url": "https://linear.app/docs/dashboards"},
    {"title": "Pulse",                         "url": "https://linear.app/docs/pulse"},
    # Asks
    {"title": "Linear Asks",                   "url": "https://linear.app/docs/linear-asks"},
    {"title": "Asks Web Forms",                "url": "https://linear.app/docs/asks-web-forms"},
    # AI & agents
    {"title": "AI at Linear",                  "url": "https://linear.app/docs/ai-at-linear"},
    {"title": "Linear Agent",                  "url": "https://linear.app/docs/linear-agent"},
    {"title": "Agents in Linear",              "url": "https://linear.app/docs/agents-in-linear"},
    {"title": "MCP Server",                    "url": "https://linear.app/docs/mcp"},
    # Integrations — overview
    {"title": "All Integrations",              "url": "https://linear.app/integrations"},
    {"title": "Integration Directory",         "url": "https://linear.app/docs/integration-directory"},
    # Integrations — specific
    {"title": "GitHub Integration",            "url": "https://linear.app/docs/github"},
    {"title": "GitLab Integration",            "url": "https://linear.app/docs/gitlab"},
    {"title": "Slack Integration",             "url": "https://linear.app/docs/slack"},
    {"title": "Figma Integration",             "url": "https://linear.app/docs/figma"},
    {"title": "Notion Integration",            "url": "https://linear.app/docs/notion"},
    {"title": "Zendesk Integration",           "url": "https://linear.app/docs/zendesk"},
    {"title": "Intercom Integration",          "url": "https://linear.app/docs/intercom"},
    {"title": "Sentry Integration",            "url": "https://linear.app/docs/sentry"},
    {"title": "Salesforce Integration",        "url": "https://linear.app/docs/salesforce"},
    {"title": "Microsoft Teams Integration",   "url": "https://linear.app/docs/microsoft-teams"},
    {"title": "Zapier Integration",            "url": "https://linear.app/docs/zapier"},
    {"title": "incident.io Integration",       "url": "https://linear.app/integrations/incident-io"},
    {"title": "Pull Request Reviews",          "url": "https://linear.app/docs/pull-request-reviews"},
    # Import & migration
    {"title": "Import Issues",                 "url": "https://linear.app/docs/import-issues"},
    {"title": "Migrate from Jira",             "url": "https://linear.app/docs/jira-to-linear"},
    {"title": "Jira Sync & Integration",       "url": "https://linear.app/docs/jira"},
    {"title": "Jira Terminology Translated",   "url": "https://linear.app/docs/jira-terminology-translated"},
    # Security & compliance
    {"title": "Security & Access",             "url": "https://linear.app/docs/security-and-access"},
    {"title": "Security Overview",             "url": "https://linear.app/security"},
    {"title": "SAML & Access Control",         "url": "https://linear.app/docs/saml-and-access-control"},
    {"title": "SCIM User Provisioning",        "url": "https://linear.app/docs/scim"},
    {"title": "Audit Log",                     "url": "https://linear.app/docs/audit-log"},
    # Billing
    {"title": "Billing & Plans",               "url": "https://linear.app/docs/billing-and-plans"},
    {"title": "Pricing",                       "url": "https://linear.app/pricing"},
    # API & developer
    {"title": "API Overview",                  "url": "https://linear.app/developers/graphql"},
    {"title": "Webhooks & API",                "url": "https://linear.app/docs/api-and-webhooks"},
    # Misc
    {"title": "Notifications",                 "url": "https://linear.app/docs/notifications"},
    {"title": "Display Options",               "url": "https://linear.app/docs/display-options"},
    {"title": "Keyboard Shortcuts",            "url": "https://linear.app/keyboard-shortcuts"},
    {"title": "Search",                        "url": "https://linear.app/docs/search"},
]

# ── Linear product taxonomy (reference for category discovery) ─────────────────
LINEAR_TAXONOMY = """
Linear's product feature areas — use these as reference when naming categories,
but only create a category if questions actually support it:

- Issues & Issue Management: creating/tracking issues, sub-issues, labels, priorities, templates, custom fields, dependencies, estimation, SLAs
- Workflow Automation: automation rules, custom statuses, triage routing
- Views & Filtering: custom views, filters, search, My Issues
- Projects & Initiatives: projects, initiatives, milestones, roadmaps, OKRs
- Cycles: sprint iterations, cycle planning, velocity, burndown
- Releases: release management, linking issues to releases (beta)
- Asks: cross-team request management via Slack/email
- Intake & Triage: triage inbox, form-based intake
- AI Features & Agents: Linear Agent, AI issue creation, natural language filters, MCP server
- Insights & Reporting: analytics, time-in-status, velocity, exports
- Workspace & Team Structure: teams, nested teams, roles, guests, non-engineering use
- Security & Compliance: SSO, SAML, SCIM, SOC2, audit logs, data residency
- Billing & Pricing: plans, seats, contracts, trials
- Integrations: Slack, GitHub, Figma, Salesforce, HubSpot, Zendesk, etc.
- Migrations & Data Import: importing from Jira, Asana, Monday, ClickUp, CSV
- Competitors & Alternatives: comparisons to Jira, Asana, Monday, ClickUp, Notion, etc.
- Trials & Implementation: onboarding, rollout, pilots, training
"""

EXTRACTED_CACHE  = "extracted_questions.json"
CLASSIFIED_CACHE = "classified_questions.json"
CHUNK_SIZE       = 150

NOTION_TOKEN       = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = (os.environ.get("NOTION_CATALOG_DB_ID", "")
                      or os.environ.get("NOTION_DATABASE_ID", ""))


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 0 — Internal user IDs
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_internal_user_ids() -> set[str]:
    ids: set[str] = set()
    cursor = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        resp = requests.get(f"{GONG_BASE}/v2/users", auth=GONG_AUTH, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for u in data.get("users", []):
            ids.add(u["id"])
        cursor = data.get("records", {}).get("cursor")
        if not cursor or not data.get("users"):
            break
    print(f"  ✓ Internal users: {len(ids)}")
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Fetch calls
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_calls() -> dict[str, dict]:
    print(f"\n{'='*60}\nSTEP 1 — Fetching calls (trailing 30 days)\n  {FROM_DATE[:10]} → {TO_DATE[:10]}\n{'='*60}")
    calls_meta = {}
    cursor = None
    page = 0
    while len(calls_meta) < 300:
        page += 1
        params = {"fromDateTime": FROM_DATE, "toDateTime": TO_DATE}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{GONG_BASE}/v2/calls", auth=GONG_AUTH, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for c in data.get("calls", []):
            cid = c.get("id", "")
            if cid:
                started = c.get("started", "")
                calls_meta[cid] = {
                    "title": c.get("title") or "Untitled call",
                    "date":  started[:10] if started else "",
                    "url":   c.get("url", ""),
                }
        print(f"  Page {page}: {len(data.get('calls',[]))} calls  (total: {len(calls_meta)})")
        cursor = data.get("records", {}).get("cursor")
        if not cursor:
            break
    print(f"\n  ✓ Total calls: {len(calls_meta)}")
    return calls_meta


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Fetch transcripts
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_transcripts(call_ids: list[str]) -> list[dict]:
    print(f"\n{'='*60}\nSTEP 2 — Fetching transcripts\n{'='*60}")
    batches = [call_ids[i:i+50] for i in range(0, len(call_ids), 50)]
    all_transcripts = []
    for i, batch in enumerate(batches, 1):
        print(f"  Batch {i}/{len(batches)} ({len(batch)} calls)...", end=" ", flush=True)
        resp = requests.post(
            f"{GONG_BASE}/v2/calls/transcript", auth=GONG_AUTH,
            json={"filter": {"callIds": batch}},
            headers={"Content-Type": "application/json"}, timeout=60,
        )
        resp.raise_for_status()
        transcripts = resp.json().get("callTranscripts") or resp.json().get("transcripts") or []
        all_transcripts.extend(transcripts)
        print(f"→ {len(transcripts)} transcripts")
        time.sleep(0.3)
    print(f"\n  ✓ Total transcripts: {len(all_transcripts)}")
    return all_transcripts


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Extract questions
# ═══════════════════════════════════════════════════════════════════════════════

EXTRACTION_PROMPT = """You are analyzing a sales call transcript for Linear.app — a project management tool for software teams.

Lines starting with "Rep:" are the Linear sales rep. Lines starting with "Prospect:" are the customer.

Extract EVERY genuine question the prospect asked about Linear's product. Resolve short fragments using surrounding context.

INCLUDE: questions about features, capabilities, pricing, migrations, security, comparisons, implementation.
EXCLUDE: rep questions about the prospect's org, scheduling, small talk, rhetorical tags ("...right?").

Rewrite each as a clean standalone sentence. Return ONLY a JSON array of strings, or [] if none.

TRANSCRIPT:
{transcript}"""


def _format_transcript(call: dict, internal_ids: set[str]) -> str:
    lines = []
    for mono in call.get("transcript", []):
        speaker = "Rep" if mono.get("speakerId", "") in internal_ids else "Prospect"
        text = " ".join(s.get("text", "").strip() for s in mono.get("sentences", []) if s.get("text", "").strip())
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _extract_for_call(call, calls_meta, internal_ids, client):
    call_id = call.get("callId", "")
    meta = calls_meta.get(call_id, {})
    transcript_text = _format_transcript(call, internal_ids)
    if not transcript_text or len(transcript_text.split()) < 50:
        return []
    words = transcript_text.split()
    if len(words) > 8000:
        transcript_text = " ".join(words[:8000])
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=2000,
                messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(transcript=transcript_text)}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                return []
            questions = json.loads(match.group())
            return [{"text": q.strip(), "call_id": call_id, "call_title": meta.get("title", "Untitled"),
                     "call_date": meta.get("date", ""), "call_url": meta.get("url", "")}
                    for q in questions if isinstance(q, str) and len(q.strip()) > 15]
        except (json.JSONDecodeError, IndexError):
            return []
        except anthropic.RateLimitError:
            time.sleep(2 ** (attempt + 1))
        except Exception:
            time.sleep(1)
    return []


def extract_all_questions(transcripts, calls_meta, internal_ids, client):
    print(f"\n{'='*60}\nSTEP 3 — Extracting questions (parallel)\n{'='*60}")
    all_questions, lock, done = [], threading.Lock(), [0]
    def process(call):
        qs = _extract_for_call(call, calls_meta, internal_ids, client)
        with lock:
            all_questions.extend(qs)
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(transcripts):
                print(f"  [{done[0]:>3}/{len(transcripts)}] {len(all_questions)} questions so far")
    with ThreadPoolExecutor(max_workers=15) as ex:
        list(ex.map(process, transcripts))
    print(f"\n  ✓ Extracted: {len(all_questions)} questions")
    with open(EXTRACTED_CACHE, "w") as f:
        json.dump(all_questions, f, indent=2)
    return all_questions


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Fixed taxonomy (replaces LLM-based discovery for stability)
# ═══════════════════════════════════════════════════════════════════════════════

FIXED_CATEGORIES = [
    "Issues & Issue Management",
    "Integrations",
    "AI Features & Agents",
    "Projects & Initiatives",
    "Billing & Pricing",
    "Insights & Reporting",
    "Workspace & Team Structure",
    "Workflow Automation",
    "Trials & Implementation",
    "Migrations & Data Import",
    "Security & Compliance",
    "Competitors & Alternatives",
    "Asks",
    "Cycles",
    "Other / Emerging",
]

FIXED_DESCRIPTIONS = {
    "Issues & Issue Management":    "Creating, editing, and tracking issues — labels, priorities, templates, estimates, SLAs, sub-issues, triage.",
    "Integrations":                 "Connecting Linear to external tools — Slack, GitHub, Figma, Salesforce, Zendesk, Intercom, and third-party apps.",
    "AI Features & Agents":         "Linear's AI capabilities — Linear Agent, triage intelligence, AI coding agents (Cursor, Copilot), MCP server.",
    "Projects & Initiatives":       "Projects, initiatives, milestones, timelines, roadmaps, releases, and cross-team planning.",
    "Billing & Pricing":            "Plan tiers, seat pricing, enterprise contracts, trials, discounts, and billing changes.",
    "Insights & Reporting":         "Analytics, dashboards, cycle time, velocity, Pulse, and data exports.",
    "Workspace & Team Structure":   "Teams, sub-teams, roles, permissions, guests, private teams, and workspace setup.",
    "Workflow Automation":          "Automation rules, custom statuses, triage routing, recurring issues, and workflow configuration.",
    "Trials & Implementation":      "Onboarding, pilots, rollout planning, training, and implementation support.",
    "Migrations & Data Import":     "Importing data from Jira, Asana, Monday, ClickUp, CSV, and migration tooling.",
    "Security & Compliance":        "SSO, SAML, SCIM, SOC 2, HIPAA, audit logs, data residency, and access controls.",
    "Competitors & Alternatives":   "Comparisons to Jira, Asana, Monday, ClickUp, Notion, Shortcut, and other tools.",
    "Asks":                         "Linear Asks — cross-team request management via Slack, web forms, email intake, and customer requests.",
    "Cycles":                       "Sprint iterations, cycle planning, velocity, burndown, and capacity tracking.",
    "Other / Emerging":             "Questions that don't fit the above categories or represent emerging topics.",
}


def get_fixed_categories():
    print(f"\n{'='*60}\nSTEP 4 — Using fixed taxonomy ({len(FIXED_CATEGORIES)} categories)\n{'='*60}")
    for c in FIXED_CATEGORIES:
        print(f"  · {c}")
    return FIXED_CATEGORIES, FIXED_DESCRIPTIONS


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Classify questions
# ═══════════════════════════════════════════════════════════════════════════════

CLASSIFY_PROMPT = """Classify each customer question into exactly one category:
{category_list}

IMPORTANT BOUNDARY RULES — read carefully before classifying:
- "Asks" = questions specifically about Linear Asks (cross-team request management, Slack intake, web forms, customer request portal, renaming the Asks app). NOT general issue creation.
- "Issues & Issue Management" = questions about creating/tracking issues, sub-issues, labels, priorities, templates, custom fields, triage — but NOT Asks-specific workflows.
- "AI Features & Agents" = Linear's own AI (Linear Agent, triage intelligence, AI filters, MCP). Questions about connecting Cursor/Copilot/Codeium TO Linear = "Integrations".
- "Integrations" = connecting Linear to ANY external tool including AI coding assistants.

EXAMPLES:
- "Can I rename the Linear Asks app in Slack?" → Asks
- "How does Linear's customer request portal work?" → Asks
- "Can you submit requests through a web form without a Linear seat?" → Asks
- "How do I create issues from Slack?" → Asks (if about the Asks intake flow) or Integrations (if about general Slack→Linear creation)
- "Can Cursor assign issues directly in Linear?" → Integrations
- "Does Linear Agent automatically triage bugs?" → AI Features & Agents

Return ONLY a JSON array with one category name per question (same order, {count} elements).

QUESTIONS:
{questions}"""


def _classify_batch(batch_index, batch, categories, category_list, client):
    prompt = CLASSIFY_PROMPT.format(
        category_list=category_list, count=len(batch),
        questions="\n".join(f"{j}. {q['text']}" for j, q in enumerate(batch)),
    )
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=1500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                raise ValueError("No array")
            assignments = json.loads(match.group())
            while len(assignments) < len(batch):
                assignments.append("Other / Emerging")
            assignments = assignments[:len(batch)]
            result = []
            for q, cat in zip(batch, assignments):
                cat = cat.strip()
                if cat not in categories:
                    cat = next((c for c in categories if c.lower() in cat.lower() or cat.lower() in c.lower()), "Other / Emerging")
                result.append({**q, "category": cat})
            return batch_index, result
        except Exception:
            if attempt == 2:
                return batch_index, [{**q, "category": "Other / Emerging"} for q in batch]
            time.sleep(2 ** attempt)
    return batch_index, [{**q, "category": "Other / Emerging"} for q in batch]


def classify_questions(all_questions, categories, descriptions, client):
    print(f"\n{'='*60}\nSTEP 5 — Classifying questions (parallel)\n{'='*60}")
    category_list = "\n".join(f"- {c}: {descriptions.get(c,'')}" if descriptions.get(c) else f"- {c}" for c in categories)
    batches = [all_questions[i:i+80] for i in range(0, len(all_questions), 80)]
    results, lock, done = {}, threading.Lock(), [0]
    def process(args):
        idx, batch = args
        bi, classified = _classify_batch(idx, batch, categories, category_list, client)
        with lock:
            results[bi] = classified
            done[0] += 1
            print(f"  [{done[0]:>2}/{len(batches)}] batch {bi+1} done", flush=True)
    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(process, enumerate(batches)))
    classified = []
    for i in range(len(batches)):
        classified.extend(results.get(i, []))
    from collections import Counter
    print(f"\n  ✓ Classified {len(classified)} questions:")
    for cat, n in sorted(Counter(q["category"] for q in classified).items(), key=lambda x: -x[1]):
        print(f"    {cat:<50} {n:>4}")
    with open(CLASSIFIED_CACHE, "w") as f:
        json.dump({"categories": categories, "questions": classified}, f, indent=2)
    print(f"\n  ✓ Saved to {CLASSIFIED_CACHE}")
    return classified


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Map-reduce clustering
# ═══════════════════════════════════════════════════════════════════════════════

CLUSTERING_PROMPT = """Customer questions from Linear.app sales calls — category: "{category}".

Group semantically identical or very similar questions into clusters. Write a clean canonical question for each. Sort by size (most asked first). Every question in exactly one cluster.

Return ONLY:
[{{"canonical": "Question?", "indices": [0, 3, 7, ...]}}]

QUESTIONS:
{numbered_list}"""

MERGE_PROMPT = """Merge near-duplicate canonical questions from the "{category}" category. Keep distinct questions separate. Every input in exactly one output group. Sort by size.

Return ONLY:
[{{"canonical": "Question?", "indices": [0, 2, 5, ...]}}]

INPUT:
{numbered_list}"""


def _cluster_chunk(category, questions, client):
    if not questions:
        return []
    numbered = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(questions))
    prompt = CLUSTERING_PROMPT.format(category=category, numbered_list=numbered)
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                return []
            result = []
            for c in json.loads(match.group()):
                indices = [i for i in c.get("indices", []) if i < len(questions)]
                if not indices:
                    continue
                seen, sources = set(), []
                for idx in indices:
                    q = questions[idx]
                    cid = q.get("call_id", "")
                    if cid and cid not in seen:
                        seen.add(cid)
                        sources.append({"call_id": cid, "call_title": q.get("call_title", ""),
                                        "call_date": q.get("call_date", ""), "call_url": q.get("call_url", ""),
                                        "question": q.get("text", "")})
                result.append({"canonical": c.get("canonical", questions[indices[0]]["text"]), "sources": sources})
            return result
        except (json.JSONDecodeError, KeyError, TypeError):
            if attempt == 2:
                return []
            time.sleep(2)
        except anthropic.RateLimitError:
            time.sleep(2 ** (attempt + 1))
    return []


def _merge_clusters(category, map_clusters, client):
    if len(map_clusters) <= 1:
        return map_clusters
    numbered = "\n".join(f"{i}. {c['canonical']}" for i, c in enumerate(map_clusters))
    prompt = MERGE_PROMPT.format(category=category, numbered_list=numbered)
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                return map_clusters
            result = []
            for m in json.loads(match.group()):
                indices = [i for i in m.get("indices", []) if i < len(map_clusters)]
                if not indices:
                    continue
                seen, sources = set(), []
                for idx in indices:
                    for s in map_clusters[idx].get("sources", []):
                        cid = s.get("call_id", "")
                        if cid and cid not in seen:
                            seen.add(cid)
                            sources.append(s)
                result.append({"canonical": m.get("canonical", map_clusters[indices[0]]["canonical"]), "sources": sources})
            return result if result else map_clusters
        except (json.JSONDecodeError, KeyError, TypeError):
            if attempt == 2:
                return map_clusters
            time.sleep(2)
        except anthropic.RateLimitError:
            time.sleep(2 ** (attempt + 1))
    return map_clusters


def cluster_category(category, questions, client):
    if not questions:
        return []
    if len(questions) <= CHUNK_SIZE:
        raw = _cluster_chunk(category, questions, client)
    else:
        chunks = [questions[i:i+CHUNK_SIZE] for i in range(0, len(questions), CHUNK_SIZE)]
        map_results = [[] for _ in chunks]
        def do_chunk(args):
            idx, chunk = args
            map_results[idx] = _cluster_chunk(category, chunk, client)
        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(do_chunk, enumerate(chunks)))
        all_map = [cl for r in map_results for cl in r]
        if not all_map:
            return []
        if len(all_map) <= CHUNK_SIZE:
            raw = _merge_clusters(category, all_map, client)
        else:
            merge_chunks = [all_map[i:i+CHUNK_SIZE] for i in range(0, len(all_map), CHUNK_SIZE)]
            intermediate = []
            for mc in merge_chunks:
                intermediate.extend(_merge_clusters(category, mc, client))
            raw = _merge_clusters(category, intermediate, client)
    result = []
    for cl in raw:
        sources = sorted(cl.get("sources", []), key=lambda s: s.get("call_date", ""), reverse=True)
        result.append({"canonical": cl["canonical"], "call_count": len(sources), "sources": sources})
    return sorted(result, key=lambda x: -x["call_count"])


def cluster_all_categories(classified, categories, client):
    print(f"\n{'='*60}\nSTEP 6 — Clustering (map-reduce)\n{'='*60}")
    by_category = defaultdict(list)
    for q in classified:
        by_category[q["category"]].append(q)
    ranked = []
    for category in categories:
        questions = by_category.get(category, [])
        if not questions:
            continue
        print(f"  {category} ({len(questions)})...", end=" ", flush=True)
        clusters = cluster_category(category, questions, client)
        all_call_ids = {s.get("call_id") for cl in clusters for s in cl.get("sources", []) if s.get("call_id")}
        print(f"→ {len(clusters)} clusters, {len(all_call_ids)} calls")
        ranked.append({"category": category, "total": len(questions),
                       "total_calls": len(all_call_ids), "clusters": clusters})
    other = [r for r in ranked if "other" in r["category"].lower() or "emerging" in r["category"].lower()]
    main  = [r for r in ranked if r not in other]
    main.sort(key=lambda x: -x["total_calls"])
    return main + other


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7a — Fetch Notion pages
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_notion_pages() -> list[dict]:
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return []
    print(f"\n{'='*60}\nSTEP 7a — Fetching Notion pages\n{'='*60}")
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    pages, start_cursor = [], None
    while True:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        resp = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
                             headers=headers, json=body, timeout=30)
        if resp.status_code != 200:
            print(f"  ⚠ Notion error {resp.status_code}")
            return []
        data = resp.json()
        for result in data.get("results", []):
            title = ""
            for prop in result.get("properties", {}).values():
                if prop.get("type") == "title":
                    title = "".join(p.get("plain_text", "") for p in prop.get("title", [])).strip()
                    break
            url = result.get("url", "")
            if title and url:
                pages.append({"title": title, "url": url})
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")
    print(f"  ✓ Fetched {len(pages)} Notion pages")
    return pages


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7b — Match clusters to resources (external docs + internal Notion)
# ═══════════════════════════════════════════════════════════════════════════════

DOCS_CACHE_PATH  = "docs_cache.json"
DOCS_CACHE_DAYS  = 7
MATCH_BATCH_SIZE = 150


class _TextExtractor(HTMLParser):
    """Strip HTML tags and extract plain text, skipping script/style/nav/footer."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "head"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "head"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self._parts.append(t)

    def get_text(self, max_chars: int = 300) -> str:
        return " ".join(self._parts)[:max_chars]


def build_validated_docs_index(cache_path: str = DOCS_CACHE_PATH) -> list[dict]:
    """Fetch LINEAR_DOCS URLs, validate HTTP 200, extract a content snippet.

    Results are cached for DOCS_CACHE_DAYS days so we don't hammer linear.app
    on every pipeline run.  Returns a list of dicts:
      {"title": ..., "url": ..., "status": <int>, "snippet": <str>}
    """
    # ── Try cache first ──────────────────────────────────────────────────────
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            age_days = (time.time() - cached.get("_ts", 0)) / 86400
            if age_days < DOCS_CACHE_DAYS:
                docs = cached.get("docs", [])
                valid = sum(1 for d in docs if d.get("status") == 200)
                print(f"  ✓ Docs index loaded from cache ({valid}/{len(docs)} valid, {age_days:.1f}d old)")
                return docs
        except Exception:
            pass

    # ── Fetch all URLs in parallel ───────────────────────────────────────────
    print(f"  Building docs index — fetching {len(LINEAR_DOCS)} URLs...")

    def _fetch_one(entry: dict) -> dict:
        url = entry["url"]
        result = {"title": entry["title"], "url": url, "status": 0, "snippet": ""}
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            result["status"] = r.status_code
            if r.status_code == 200:
                extractor = _TextExtractor()
                extractor.feed(r.text)
                result["snippet"] = extractor.get_text(300)
        except Exception:
            pass
        return result

    with ThreadPoolExecutor(max_workers=10) as pool:
        docs = list(pool.map(_fetch_one, LINEAR_DOCS))

    valid = sum(1 for d in docs if d.get("status") == 200)
    print(f"  ✓ Fetched {valid}/{len(docs)} docs (HTTP 200)")

    try:
        with open(cache_path, "w") as f:
            json.dump({"_ts": time.time(), "docs": docs}, f)
    except Exception:
        pass

    return docs


RESOURCE_MATCH_PROMPT = """Match each customer question to the most helpful resources for a Linear sales rep.

For each question find:
1. The best EXTERNAL Linear documentation page — for questions about how a feature works
2. The best INTERNAL sales enablement page (from the Notion list) — for pricing, objections, competitive, onboarding guidance

Only match when genuinely relevant. Many questions will have one but not both. Return null when no good match.

Return ONLY a JSON object:
{{"0": {{"ext": 3, "int": 12}}, "1": {{"ext": null, "int": 7}}, "2": {{"ext": 5, "int": null}}, ...}}

Where numbers are 0-based indices into each respective list.

QUESTIONS:
{questions}

EXTERNAL LINEAR DOCS (index · title · URL · content preview):
{external_pages}

INTERNAL NOTION PAGES:
{internal_pages}"""


def match_resources_to_clusters(ranked, notion_pages, client):
    all_canonicals: list[str] = []
    for r in ranked:
        for cl in r.get("clusters", []):
            all_canonicals.append(cl["canonical"])

    print(f"\n  Matching {len(all_canonicals)} clusters to docs + {len(notion_pages)} internal pages...")

    # Build content-rich external docs index (cached)
    docs_index = build_validated_docs_index()
    valid_docs = [d for d in docs_index if d.get("status") == 200]

    external_text = "\n".join(
        f"{i}. {d['title']} | {d['url']} | {d['snippet'][:200]}"
        for i, d in enumerate(valid_docs)
    )
    internal_text = "\n".join(f"{i}. {p['title']}" for i, p in enumerate(notion_pages))

    # ── Batch questions to stay within context limits ────────────────────────
    batches = [
        all_canonicals[i:i + MATCH_BATCH_SIZE]
        for i in range(0, len(all_canonicals), MATCH_BATCH_SIZE)
    ]

    result: dict[str, dict] = {}

    for batch_idx, batch in enumerate(batches):
        questions_text = "\n".join(f"{i}. {q}" for i, q in enumerate(batch))
        prompt = RESOURCE_MATCH_PROMPT.format(
            questions=questions_text,
            external_pages=external_text,
            internal_pages=internal_text,
        )

        print(f"  Batch {batch_idx + 1}/{len(batches)} ({len(batch)} questions)...", end=" ", flush=True)

        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=4000, temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text.strip()
                m = re.search(r'\{.*\}', raw, re.DOTALL)
                if not m:
                    print("no JSON found")
                    break
                mapping_raw = json.loads(m.group())

                batch_matched = 0
                for q_idx_str, v in mapping_raw.items():
                    try:
                        local_idx = int(q_idx_str)
                        if local_idx >= len(batch):
                            continue
                        canonical = batch[local_idx]
                        ext_page = valid_docs[int(v["ext"])] if v.get("ext") is not None else None
                        int_page = notion_pages[int(v["int"])] if v.get("int") is not None else None
                        if ext_page or int_page:
                            result[canonical] = {"external": ext_page, "internal": int_page}
                            batch_matched += 1
                    except (ValueError, TypeError, IndexError, KeyError):
                        continue

                print(f"ok ({batch_matched} matched)")
                break

            except Exception as e:
                if attempt == 2:
                    print(f"failed: {e}")
                else:
                    time.sleep(2)

    ext_count = sum(1 for v in result.values() if v.get("external"))
    int_count = sum(1 for v in result.values() if v.get("internal"))
    print(f"  ✓ Total matched: {ext_count} external docs, {int_count} internal pages")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    use_cache            = "--use-cache" in sys.argv
    use_classified_cache = "--use-classified-cache" in sys.argv

    print("\n🎯  Linear Sales — Customer Question Leaderboard")
    print(f"    Trailing 30 days: {FROM_DATE[:10]} → {TO_DATE[:10]}\n")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("✗ ANTHROPIC_API_KEY not set"); sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    print("  Loading internal Gong users...")
    internal_ids = fetch_internal_user_ids()

    if use_classified_cache and os.path.exists(CLASSIFIED_CACHE):
        print(f"\n  ── Using classified cache ──")
        with open(CLASSIFIED_CACHE) as f:
            cached = json.load(f)
        categories, classified = cached["categories"], cached["questions"]
        total_questions = len(classified)
        print(f"  ✓ {total_questions} questions, {len(categories)} categories")

    elif use_cache and os.path.exists(EXTRACTED_CACHE):
        print(f"\n  ── Using extracted cache ──")
        with open(EXTRACTED_CACHE) as f:
            all_questions = json.load(f)
        total_questions = len(all_questions)
        print(f"  ✓ {total_questions} questions loaded")
        categories, descriptions = get_fixed_categories()
        classified = classify_questions(all_questions, categories, descriptions, client)

    else:
        calls_meta = fetch_calls()
        if not calls_meta:
            print("\n⚠  No calls found."); return
        transcripts = fetch_transcripts(list(calls_meta.keys()))
        if not transcripts:
            print("\n⚠  No transcripts."); return
        all_questions = extract_all_questions(transcripts, calls_meta, internal_ids, client)
        if not all_questions:
            print("\n⚠  No questions extracted."); return
        total_questions = len(all_questions)
        categories, descriptions = get_fixed_categories()
        classified = classify_questions(all_questions, categories, descriptions, client)

    ranked       = cluster_all_categories(classified, categories, client)
    notion_pages = fetch_notion_pages()
    resource_map = match_resources_to_clusters(ranked, notion_pages, client)

    with open("results.json", "w") as f:
        json.dump({"generated_at": NOW.isoformat(), "date_range": {"from": FROM_DATE, "to": TO_DATE},
                   "total_questions": total_questions, "categories": categories, "ranked": ranked,
                   "resource_map": resource_map}, f, indent=2)
    print("\n  ✓ Saved results.json")

    from render_html import write_html as _write_html
    path = _write_html(ranked, total_questions, FROM_DATE, TO_DATE, resource_map=resource_map)
    print(f"\n{'='*60}\n  ✅  Done!  open {path}\n{'='*60}\n")


if __name__ == "__main__":
    main()
