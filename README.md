# Linear Sales — Gong Call Analyzer

Fetches the past 6 months of Gong calls, extracts prospect questions,
groups them by theme, and uses Claude (grounded in your Notion + Linear docs)
to draft accurate rep responses. Outputs a self-contained HTML dashboard.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run
python analyze.py

# 4. Open the report
open gong_report.html
```

## What it does

| Step | What happens |
|------|-------------|
| 1 | Calls Gong `/v2/calls/search` with a 6-month date window (paginated) |
| 2 | Fetches all transcripts in batches of 50 via `/v2/calls/transcript` |
| 3 | Filters to external/prospect speakers only, extracts questions |
| 4 | Classifies questions into 10 themes by keyword matching |
| 5 | Groups near-duplicate questions (≥45% word overlap = same cluster) |
| 6 | Claude searches Notion + Linear docs and drafts accurate rep responses |
| 7 | Writes `gong_report.html` + `results.json` |

## Output files

- **`gong_report.html`** — shareable dashboard, open in any browser
- **`results.json`** — raw structured data, ready to power a hosted version later

## Next steps (when ready to host)

- Add a GitHub Actions cron job that runs `analyze.py` nightly
- Commit `results.json` back to the repo
- Serve `gong_report.html` via GitHub Pages — the team gets a living URL
