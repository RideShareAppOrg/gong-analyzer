#!/usr/bin/env python3
"""Standalone HTML renderer — generates gong_report.html from results.json.
Run directly: python render_html.py
Also called by analyze.py after each pipeline run.
"""

import json, re
from datetime import datetime


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _make_pills(ext_page, int_page):
    pills = ""
    if ext_page:
        t = ext_page["title"][:45] + ("…" if len(ext_page["title"]) > 45 else "")
        pills += f'<a href="{esc(ext_page["url"])}" target="_blank" class="pill pill-ext">{esc(t)}</a>'
    if int_page:
        t = int_page["title"][:45] + ("…" if len(int_page["title"]) > 45 else "")
        pills += f'<a href="{esc(int_page["url"])}" target="_blank" class="pill pill-int">{esc(t)}</a>'
    return pills


def write_html(ranked, total_questions, from_date, to_date,
               resource_map=None, deltas=None, compare_period=None,
               output_path="gong_report.html"):
    resource_map  = resource_map or {}
    deltas        = deltas or {}

    # Build compare label: "vs Feb 19 – Mar 13" for the toggle button
    if deltas and compare_period:
        from datetime import datetime as _dt2
        _cf = _dt2.strptime(compare_period["from"][:10], "%Y-%m-%d")
        _ct = _dt2.strptime(compare_period["to"][:10], "%Y-%m-%d")
        _same_year = _cf.year == _ct.year
        _cf_str = _cf.strftime("%b %-d")
        _ct_str = _ct.strftime("%b %-d") + ("" if _same_year else f" {_ct.year}")
        compare_label     = f"vs {_cf_str} – {_ct_str}"
        delta_toggle_btn  = (f'<button class="delta-toggle-btn" id="delta-toggle"'
                             f' data-on-label="{compare_label}" data-off-label="&#916; Changes"'
                             f' onclick="toggleDeltas()">&#916; Changes</button>')
    elif deltas:
        delta_toggle_btn  = ('<button class="delta-toggle-btn" id="delta-toggle"'
                             ' data-on-label="&#916; Changes" data-off-label="&#916; Changes"'
                             ' onclick="toggleDeltas()">&#916; Changes</button>')
    else:
        delta_toggle_btn  = ""

    now_str   = datetime.now().strftime("%B %d, %Y at %H:%M")
    max_calls = max((r["total_calls"] for r in ranked), default=1)

    # Collect all rep names across all clusters
    all_reps = sorted({
        s.get("rep_name", "")
        for r in ranked
        for cl in r.get("clusters", [])
        for s in cl.get("sources", [])
        if s.get("rep_name", "")
    })

    from datetime import datetime as _dt
    _fd = _dt.strptime(from_date[:10], "%Y-%m-%d")
    _td = _dt.strptime(to_date[:10], "%Y-%m-%d")
    _days = (_td - _fd).days + 1
    from_month = _fd.strftime("%b")
    from_day   = str(_fd.day)
    from_year  = _fd.strftime("%Y")
    to_month   = _td.strftime("%b")
    to_day     = str(_td.day)
    to_year    = _td.strftime("%Y")

    # ── Left panel: leaderboard category list ─────────────────────────────────
    cat_items = ""
    for i, r in enumerate(ranked):
        is_emerging = "other" in r["category"].lower() or "emerging" in r["category"].lower()
        pct = round((r["total_calls"] / max_calls) * 100)
        rank_label     = "" if is_emerging else f'<span class="ci-rank">#{i+1}</span>'
        emerging_badge = '<span class="ci-emerging-badge">Emerging</span>' if is_emerging else ""
        cat_reps = esc("|".join(sorted({
            s.get("rep_name", "") for cl in r.get("clusters", [])
            for s in cl.get("sources", []) if s.get("rep_name", "")
        })))
        d          = deltas.get(r["category"], {})
        call_delta = d.get("call_delta")
        if call_delta is None or call_delta == 0:
            delta_badge = ""
        else:
            prev_calls = r["total_calls"] - call_delta
            pct        = round((call_delta / prev_calls) * 100) if prev_calls > 0 else 0
            if call_delta > 0:
                delta_badge = f'<span class="ci-delta ci-delta-up">↑{pct}%</span>'
            else:
                delta_badge = f'<span class="ci-delta ci-delta-down">↓{abs(pct)}%</span>'

        cat_items += (
            f'<div class="cat-item{"  cat-item-emerging" if is_emerging else ""}"'
            f' data-cat="{i}" data-calls="{r["total_calls"]}" data-questions="{r["total"]}"'
            f' data-pct="{pct}" data-name="{esc(r["category"])}" data-reps="{cat_reps}" onclick="selectCat({i})">\n'
            f'  <div class="ci-header">\n'
            f'    {rank_label}{emerging_badge}\n'
            f'    <span class="ci-name">{esc(r["category"])}</span>\n'
            f'    <div class="ci-score">'
            f'<span class="ci-score-num">{r["total_calls"]}</span>'
            f'<span class="ci-score-sub">unique calls</span>'
            f'{delta_badge}</div>\n'
            f'  </div>\n'
            f'  <div class="ci-bar-track"><div class="ci-bar-fill" style="width:{pct}%"></div></div>\n'
            f'</div>\n'
        )

    # ── Global search rows (all clusters, all categories) ─────────────────────
    search_rows = ""
    for r in ranked:
        cat_name = esc(r["category"])
        for cl in r.get("clusters", []):
            sr_calls_s = "s" if cl["call_count"] != 1 else ""
            search_rows += (
                f'<div class="sr-row hidden"'
                f' data-text="{esc(cl["canonical"].lower())} {esc(r["category"].lower())}"'
                f' data-cat="{esc(r["category"])}">\n'
                f'  <div class="sr-main">\n'
                f'    <span class="sr-cat">{cat_name}</span>\n'
                f'    <div class="q-label">{esc(cl["canonical"])}</div>\n'
                f'    <div class="q-call-meta">asked in <span class="q-freq">{cl["call_count"]}</span> call{sr_calls_s}</div>\n'
                f'  </div>\n'
                f'</div>\n'
            )

    # ── Right panel: per-category question panels ──────────────────────────────
    question_panels = ""
    for i, r in enumerate(ranked):
        questions_html = ""

        # Collect unique resources across all clusters for the Topic Library
        seen_urls  = set()
        ext_pills  = ""
        int_pills  = ""
        for cl in r.get("clusters", []):
            res = resource_map.get(cl["canonical"], {})
            for key, pill_cls, container in (
                ("external", "pill pill-ext", "ext"),
                ("internal", "pill pill-int", "int"),
            ):
                page = res.get(key)
                if page and page.get("url") and page["url"] not in seen_urls:
                    seen_urls.add(page["url"])
                    t = page["title"][:50] + ("…" if len(page["title"]) > 50 else "")
                    pill = f'<a href="{esc(page["url"])}" target="_blank" class="{pill_cls}">{esc(t)}</a>'
                    if container == "ext":
                        ext_pills += pill
                    else:
                        int_pills += pill

        for q_idx, cl in enumerate(r.get("clusters", [])):
            n_src     = len(cl.get("sources", []))
            calls_s   = "s" if cl["call_count"] != 1 else ""

            src_items = ""
            for s in cl.get("sources", []):
                title   = esc(s.get("call_title") or "Untitled")
                date    = esc(s.get("call_date", ""))
                url     = s.get("call_url", "")
                excerpt = esc(s.get("question", ""))
                link    = (f'<a href="{esc(url)}" target="_blank" class="src-link">{title}</a>'
                           if url else f'<span class="src-plain">{title}</span>')
                excerpt_html = f'<div class="src-excerpt">"{excerpt}"</div>' if excerpt else ""
                src_rep = esc(s.get("rep_name", ""))
                src_items += (
                    f'<div class="src-item" data-rep="{src_rep}">'
                    f'<div class="src-meta"><span class="src-date">{date}</span>{link}</div>'
                    f'{excerpt_html}</div>\n'
                )

            src_s      = "s" if n_src != 1 else ""
            from collections import Counter as _Counter
            rep_counts = _Counter(s.get("rep_name","") for s in cl.get("sources",[]) if s.get("rep_name",""))
            rep_counts_attr = esc("|".join(f"{k}:{v}" for k,v in rep_counts.items()))
            cl_reps = esc("|".join(sorted(rep_counts.keys())))
            src_toggle = (
                f'<details class="src-toggle">'
                f'<summary>asked in <span class="q-freq">{cl["call_count"]}</span> call{calls_s}</summary>'
                f'<div class="src-list">{src_items}</div></details>'
            ) if src_items else (
                f'<div class="q-call-meta">asked in <span class="q-freq">{cl["call_count"]}</span> call{calls_s}</div>'
            )
            questions_html += (
                f'<div class="q-row" data-text="{esc(cl["canonical"].lower())}" data-reps="{cl_reps}" data-rep-counts="{rep_counts_attr}" data-total-calls="{cl["call_count"]}">\n'
                f'  <div class="q-left">\n'
                f'    <span class="q-rank">#{q_idx+1}</span>\n'
                f'  </div>\n'
                f'  <div class="q-main">\n'
                f'    <div class="q-label">{esc(cl["canonical"])}</div>\n'
                f'    {src_toggle}\n'
                f'  </div>\n'
                f'</div>\n'
            )

        n_clusters  = len(r.get("clusters", []))
        n_ext       = ext_pills.count('<a ')
        n_int       = int_pills.count('<a ')
        ext_row     = (f'<div class="tl-row">'
                       f'<span class="tl-label">Docs</span>'
                       f'<div class="tl-pills">{ext_pills}</div>'
                       f'</div>') if ext_pills else ""
        int_row     = (f'<div class="tl-row">'
                       f'<span class="tl-label">Plays</span>'
                       f'<div class="tl-pills">{int_pills}</div>'
                       f'</div>') if int_pills else ""
        counts      = " &middot; ".join(filter(None, [
            f"{n_ext} doc{'s' if n_ext != 1 else ''}" if n_ext else "",
            f"{n_int} playbook{'s' if n_int != 1 else ''}" if n_int else "",
        ]))
        topic_lib   = (f'<details class="topic-library">'
                       f'<summary class="tl-summary">Resources &middot; {counts}</summary>'
                       f'<div class="tl-body">{ext_row}{int_row}</div>'
                       f'</details>') if (ext_row or int_row) else ""
        question_panels += (
            f'<div class="q-panel" id="panel-{i}" style="display:none">\n'
            f'  <div class="qp-header">\n'
            f'    <div class="qp-title">{esc(r["category"])}</div>\n'
            f'    <div class="qp-meta"><strong>{r["total_calls"]} unique calls</strong> raised this topic'
            f' &middot; {r["total"]} questions asked &middot; {n_clusters} clusters</div>\n'
            f'    {topic_lib}\n'
            f'  </div>\n'
            f'  <div class="qp-list" id="qplist-{i}">{questions_html}</div>\n'
            f'</div>\n'
        )

    rep_options = "\n".join(f'<option value="{esc(r)}">{esc(r)}</option>' for r in all_reps)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Customer Questions Leaderboard — Linear Sales</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#f5f3ef; --surface:#fff; --border:#e2ddd6; --ink:#1a1814;
  --muted:#8c8680; --accent:#5E6AD2; --accent-bg:#ECEEFB;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%}}
body{{background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;font-size:15px;line-height:1.65;display:flex;flex-direction:column;height:100vh;overflow:hidden}}

/* ── Masthead ── */
.masthead{{background:var(--ink);color:#f5f3ef;padding:26px 40px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}}
.masthead-left .eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;letter-spacing:.18em;text-transform:uppercase;color:#8c8680;margin-bottom:4px}}
.masthead-left .title{{font-family:'Inter',sans-serif;font-weight:600;font-size:3rem;letter-spacing:-.01em;line-height:1.1}}
.masthead-left .title em{{font-style:normal;color:#5E6AD2}}
.masthead-right{{display:flex;flex-direction:column;align-items:flex-end;gap:8px}}
.date-tiles{{display:flex;align-items:center;gap:6px}}
.dt-tile{{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:5px;padding:8px 14px;text-align:center;cursor:pointer;transition:background .15s,border-color .15s,transform .1s}}
.dt-tile:hover{{background:rgba(94,106,210,0.18);border-color:rgba(94,106,210,0.55);transform:translateY(-1px)}}
.dt-label{{display:block;font-family:'IBM Plex Mono',monospace;font-size:.48rem;letter-spacing:.18em;text-transform:uppercase;color:#9c9890;margin-bottom:4px}}
.dt-date{{display:block;font-family:'Inter',sans-serif;font-weight:800;font-size:1.05rem;color:#f5f3ef;line-height:1;letter-spacing:-.02em}}
.dt-year{{display:block;font-family:'IBM Plex Mono',monospace;font-size:.54rem;color:#9c9890;margin-top:3px}}
.dt-arrow{{color:#5E6AD2;font-size:.85rem;flex-shrink:0;margin:0 2px}}
.dt-duration{{background:rgba(94,106,210,0.2);border:1px solid rgba(94,106,210,0.35);border-radius:3px;padding:3px 9px;font-family:'IBM Plex Mono',monospace;font-size:.58rem;color:#a8aef0;letter-spacing:.04em}}
.masthead-meta{{text-align:right;font-family:'IBM Plex Mono',monospace;font-size:.62rem;color:#5a5650;line-height:1.8}}
.masthead-meta .stat{{color:#c8c4be;font-family:'Inter',sans-serif;font-weight:600;font-size:.82rem;display:block}}

/* ── App shell ── */
.app{{display:flex;flex:1;overflow:hidden}}

/* ── Left panel ── */
.left-panel{{width:500px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}}
.lp-controls{{padding:14px 16px;border-bottom:1px solid var(--border);flex-shrink:0}}
.lp-search{{width:100%;padding:7px 11px;border:1px solid var(--border);border-radius:3px;font-family:'IBM Plex Mono',monospace;font-size:.75rem;background:var(--bg);color:var(--ink);outline:none}}
.lp-search:focus{{border-color:var(--accent)}}
.lp-rep-filter{{width:100%;margin-top:8px;padding:7px 11px;border:1px solid var(--border);border-radius:3px;font-family:'IBM Plex Mono',monospace;font-size:.75rem;background:var(--bg);color:var(--ink);outline:none;cursor:pointer}}
.lp-rep-filter:focus{{border-color:var(--accent)}}
.lp-sort{{display:flex;gap:6px;margin-top:8px;align-items:center}}
.sort-select{{flex:1;font-family:'IBM Plex Mono',monospace;font-size:.62rem;padding:4px 6px;border:1px solid var(--border);border-radius:2px;background:transparent;color:var(--muted);cursor:pointer;appearance:none;-webkit-appearance:none}}
.sort-select:focus{{outline:none;border-color:var(--accent);color:var(--accent)}}
.delta-toggle-btn{{font-family:'IBM Plex Mono',monospace;font-size:.62rem;padding:4px 8px;border:1px solid var(--border);border-radius:2px;background:transparent;color:var(--muted);cursor:pointer;white-space:nowrap}}
.delta-toggle-btn.active{{border-color:var(--accent);color:var(--accent);background:var(--accent-bg)}}
.cat-list{{flex:1;overflow-y:auto;padding:6px 0}}

/* ── Category items — leaderboard style ── */
.cat-item{{padding:11px 16px 12px;cursor:pointer;border-left:3px solid transparent;transition:background .1s}}
.cat-item:hover{{background:#f9f7f4}}
.cat-item.active{{border-left-color:var(--accent);background:var(--accent-bg)}}
.cat-item-emerging{{opacity:.65}}
.ci-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.ci-rank{{font-family:'IBM Plex Mono',monospace;font-size:.72rem;font-weight:500;color:var(--muted);min-width:26px;flex-shrink:0}}
.cat-item.active .ci-rank{{color:var(--accent)}}
.ci-emerging-badge{{font-family:'IBM Plex Mono',monospace;font-size:.58rem;background:#ece9e3;color:var(--muted);padding:1px 5px;border-radius:2px;text-transform:uppercase;letter-spacing:.06em;flex-shrink:0}}
.ci-name{{font-family:'Inter',sans-serif;font-weight:600;font-size:.88rem;flex:1;min-width:0;line-height:1.3}}
.cat-item.active .ci-name{{color:var(--accent)}}
.ci-score{{font-family:'Inter',sans-serif;font-weight:800;font-size:1.15rem;color:var(--ink);flex-shrink:0;line-height:1;text-align:right}}
.cat-item.active .ci-score{{color:var(--accent)}}
.ci-score-sub{{display:block;font-family:'IBM Plex Mono',monospace;font-size:.55rem;font-weight:400;color:var(--muted);text-align:right;margin-top:2px}}
.cat-item.active .ci-score-sub{{color:var(--accent);opacity:.7}}
.ci-delta{{display:none;font-family:'IBM Plex Mono',monospace;font-size:.6rem;font-weight:700;text-align:right;margin-top:3px}}
.deltas-visible .ci-delta{{display:block}}
.ci-delta-up{{color:#22c55e}}
.ci-delta-down{{color:#f97316}}
.ci-bar-track{{height:7px;background:#ede9e4;border-radius:4px}}
.ci-bar-fill{{height:7px;background:#cac8f0;border-radius:4px;transition:width .35s ease,background .15s}}
.cat-item.active .ci-bar-fill{{background:var(--accent)}}
.cat-item:hover:not(.active) .ci-bar-fill{{background:#b0ade6}}

/* ── Right panel ── */
.right-panel{{flex:1;overflow:hidden;display:flex;flex-direction:column;background:var(--bg)}}
.right-panel-inner{{flex:1;overflow-y:auto}}
.empty-state{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px}}
.empty-state-label{{font-family:'IBM Plex Mono',monospace;font-size:.78rem;color:var(--muted)}}
.empty-state-hint{{font-family:'IBM Plex Mono',monospace;font-size:.65rem;color:var(--muted);opacity:.6}}

/* ── Question panel ── */
.q-panel{{padding:0}}
.qp-header{{padding:22px 32px 16px;border-bottom:1px solid var(--border);background:var(--surface);position:sticky;top:0;z-index:10}}
.qp-title{{font-family:'Inter',sans-serif;font-weight:800;font-size:1.4rem;letter-spacing:-.02em;color:var(--ink);margin-bottom:4px}}
.qp-meta{{font-family:'IBM Plex Mono',monospace;font-size:.67rem;color:var(--muted)}}
.qp-meta strong{{color:var(--ink);font-weight:600}}
.topic-library{{margin-top:10px;border-top:1px solid var(--border);padding-top:8px}}
.tl-summary{{cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:5px;font-family:'IBM Plex Mono',monospace;font-size:.62rem;color:var(--muted);user-select:none;padding:2px 0}}
.tl-summary::-webkit-details-marker{{display:none}}
.tl-summary::before{{content:'▶';font-size:.42rem;transition:transform .15s}}
.topic-library[open] .tl-summary::before{{transform:rotate(90deg)}}
.tl-body{{display:flex;flex-direction:column;gap:8px;margin-top:10px}}
.tl-row{{display:flex;align-items:flex-start;gap:8px}}
.tl-label{{font-family:'IBM Plex Mono',monospace;font-size:.55rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;padding-top:3px;flex-shrink:0;width:32px}}
.tl-pills{{display:flex;flex-wrap:wrap;gap:5px}}
.qp-list{{padding:8px 32px 40px}}

/* ── Question rows ── */
.q-row{{display:flex;gap:16px;padding:16px 0;border-bottom:1px dashed var(--border);align-items:flex-start}}
.q-row:last-child{{border-bottom:none}}
.q-row.hidden{{display:none}}
.q-left{{display:flex;flex-direction:column;align-items:center;gap:5px;min-width:52px;padding-top:2px;flex-shrink:0}}
.q-rank{{font-family:'IBM Plex Mono',monospace;font-size:.6rem;color:var(--muted)}}
.q-call-meta{{font-size:.72rem;color:var(--muted);margin:2px 0 4px;font-family:'IBM Plex Mono',monospace}}
.q-freq{{font-weight:600;color:var(--ink)}}
.q-main{{flex:1;min-width:0}}
.q-label{{font-family:'Inter',sans-serif;font-weight:600;font-size:.95rem;color:var(--ink);line-height:1.45;margin-bottom:7px}}

/* ── Global search results ── */
.sr-row{{display:flex;gap:14px;padding:14px 0;border-bottom:1px dashed var(--border);align-items:flex-start}}
.sr-row:last-child{{border-bottom:none}}
.sr-row.hidden{{display:none}}
.sr-left{{flex-shrink:0;min-width:52px}}
.sr-main{{flex:1;min-width:0}}
.sr-cat{{display:inline-block;font-family:'IBM Plex Mono',monospace;font-size:.58rem;background:var(--accent-bg);color:var(--accent);padding:2px 7px;border-radius:2px;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}}

/* ── Resource pills ── */
.q-pills{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:7px}}
.pill{{font-family:'IBM Plex Mono',monospace;font-size:.63rem;padding:3px 9px;border-radius:3px;text-decoration:none;line-height:1.5;white-space:nowrap;max-width:240px;overflow:hidden;text-overflow:ellipsis}}
.pill-ext{{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe}}
.pill-ext:hover{{background:#dbeafe}}
.pill-int{{background:#fdf7e8;color:#92600a;border:1px solid #e5d4a0}}
.pill-int:hover{{background:#faefc8}}
.pill-legend{{display:flex;gap:16px;padding:10px 32px 2px;font-family:'IBM Plex Mono',monospace;font-size:.6rem;color:var(--muted)}}
.pill-legend-item{{display:flex;align-items:center;gap:5px}}
.pill-legend-dot{{width:8px;height:8px;border-radius:1px;flex-shrink:0}}

/* ── Source toggle ── */
.src-toggle{{margin-top:4px}}
.src-toggle summary{{cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:4px;font-family:'IBM Plex Mono',monospace;font-size:.63rem;color:var(--accent);user-select:none}}
.src-toggle summary::-webkit-details-marker{{display:none}}
.src-toggle summary::before{{content:'▶';font-size:.42rem;transition:transform .15s}}
.src-toggle[open] summary::before{{transform:rotate(90deg)}}
.src-list{{margin-top:7px}}
.src-item{{padding:7px 10px;border:1px solid var(--border);border-radius:3px;margin-bottom:5px;background:var(--surface)}}
.src-meta{{display:flex;align-items:baseline;gap:8px;margin-bottom:3px}}
.src-date{{font-family:'IBM Plex Mono',monospace;font-size:.6rem;color:var(--muted);white-space:nowrap;min-width:68px}}
.src-link{{font-size:.76rem;color:var(--accent);text-decoration:none}}
.src-link:hover{{text-decoration:underline}}
.src-plain{{font-size:.76rem;color:var(--ink)}}
.src-excerpt{{font-size:.71rem;color:var(--muted);font-style:italic;line-height:1.4;padding-left:76px}}

@media(max-width:800px){{
  body{{overflow:auto}}
  .app{{flex-direction:column;overflow:visible}}
  .left-panel{{width:100%;border-right:none;border-bottom:1px solid var(--border);max-height:300px}}
  .right-panel{{overflow:visible}}
  .right-panel-inner{{overflow:visible}}
  .qp-header{{position:relative}}
}}
</style>
</head>
<body>

<div class="masthead">
  <div class="masthead-left">
    <div class="eyebrow">Linear Sales Intelligence · Gong Call Analysis</div>
    <div class="title">Customer <em>Questions</em> Leaderboard</div>
  </div>
  <div class="masthead-right">
    <div class="date-tiles">
      <div class="dt-tile">
        <span class="dt-label">from</span>
        <span class="dt-date">{from_month} {from_day}</span>
        <span class="dt-year">{from_year}</span>
      </div>
      <span class="dt-arrow">→</span>
      <div class="dt-tile">
        <span class="dt-label">to</span>
        <span class="dt-date">{to_month} {to_day}</span>
        <span class="dt-year">{to_year}</span>
      </div>
      <span class="dt-duration">{_days}d</span>
    </div>
    <div class="masthead-meta">
      <span class="stat">{total_questions:,} questions · {len(ranked)} topics</span>
      Generated {now_str}
    </div>
  </div>
</div>

<div class="app">
  <!-- Left panel -->
  <div class="left-panel">
    <div class="lp-controls">
      <input class="lp-search" type="text" id="search" placeholder="Search all questions…" oninput="filterQuestions(this.value)">
      <select class="lp-rep-filter" id="rep-filter" onchange="filterByRep(this.value)">
        <option value="">All Reps</option>
        {rep_options}
      </select>
      <div class="lp-sort">
        <select class="sort-select" id="sort-select" onchange="sortBy(this.value)">
          <option value="calls">Sort: Calls</option>
          <option value="questions">Sort: Questions</option>
        </select>
        {delta_toggle_btn}
      </div>
    </div>
    <div class="cat-list" id="cat-list">
      {cat_items}
    </div>
  </div>

  <!-- Right panel -->
  <div class="right-panel">
    <div class="pill-legend">
      <span class="pill-legend-item"><span class="pill-legend-dot" style="background:#bfdbfe"></span>Linear docs</span>
      <span class="pill-legend-item"><span class="pill-legend-dot" style="background:#e5d4a0"></span>Internal Notion</span>
    </div>
    <div class="right-panel-inner" id="right-inner">
      <div class="empty-state" id="empty-state">
        <span class="empty-state-label">← Select a topic to explore</span>
        <span class="empty-state-hint">or search above to find questions across all topics</span>
      </div>

      <!-- Global search results -->
      <div class="q-panel" id="search-results-panel" style="display:none">
        <div class="qp-header">
          <div class="qp-title">Search Results</div>
          <div class="qp-meta" id="search-meta">—</div>
        </div>
        <div class="qp-list" id="search-results-list">
          {search_rows}
        </div>
      </div>

      {question_panels}
    </div>
  </div>
</div>

<script>
let currentCat  = null;
let currentSort = 'calls';
let searchQuery = '';
let currentRep  = '';

function selectCat(idx) {{
  clearSearch();
  document.querySelectorAll('.q-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.cat-item').forEach(el => el.classList.remove('active'));
  document.getElementById('empty-state').style.display = 'none';

  const panel = document.getElementById('panel-' + idx);
  const item  = document.querySelector('[data-cat="' + idx + '"]');
  if (panel) panel.style.display = 'block';
  if (item)  item.classList.add('active');

  document.getElementById('right-inner').scrollTop = 0;
  currentCat = idx;
  if (currentRep) filterByRep(currentRep);
}}

function filterByRep(rep) {{
  currentRep = rep;

  // Filter source call items and update the summary count
  document.querySelectorAll('.src-toggle').forEach(toggle => {{
    const items = toggle.querySelectorAll('.src-item');
    items.forEach(item => {{
      if (!rep) {{ item.style.display = ''; return; }}
      item.style.display = (item.dataset.rep === rep) ? '' : 'none';
    }});
    const visible = rep
      ? [...items].filter(i => i.dataset.rep === rep).length
      : items.length;
    const summary = toggle.querySelector('summary');
    if (summary) summary.innerHTML = 'asked in <span class="q-freq">' + visible + '</span> ' + (visible === 1 ? 'call' : 'calls');
  }});

  // Update every question row across all panels
  document.querySelectorAll('.q-row').forEach(row => {{
    const reps = (row.dataset.reps || '').split('|');
    const visible = !rep || reps.includes(rep);
    row.classList.toggle('hidden', !visible);

    // Update the call count badge to reflect this rep's calls
    const badge = row.querySelector('.q-freq');
    if (badge) {{
      if (!rep) {{
        badge.childNodes[0].textContent = row.dataset.totalCalls;
      }} else {{
        const counts = Object.fromEntries(
          (row.dataset.repCounts || '').split('|').filter(Boolean)
            .map(p => {{ const [k,v] = p.split(':'); return [k, parseInt(v)]; }})
        );
        badge.childNodes[0].textContent = counts[rep] || 0;
      }}
    }}
  }});

  // Update category items: hide if no visible rows, update score, re-sort
  const catList = document.getElementById('cat-list');
  const allItems = Array.from(catList.querySelectorAll('.cat-item'));
  const emerging = allItems.filter(el => el.classList.contains('cat-item-emerging'));
  const main     = allItems.filter(el => !el.classList.contains('cat-item-emerging'));

  main.forEach(el => {{
    const idx = el.dataset.cat;
    if (!rep) {{
      el.style.display = '';
      const num = el.querySelector('.ci-score-num');
      if (num) num.textContent = currentSort === 'calls' ? el.dataset.calls : el.dataset.questions;
      return;
    }}
    const reps = (el.dataset.reps || '').split('|');
    const hasRep = reps.includes(rep);
    el.style.display = hasRep ? '' : 'none';
    if (hasRep) {{
      const visibleRows = document.querySelectorAll('#panel-' + idx + ' .q-row:not(.hidden)');
      const num = el.querySelector('.ci-score-num');
      if (num) num.textContent = visibleRows.length;
    }}
  }});

  // Re-sort visible categories by their updated score
  if (rep) {{
    main.sort((a, b) => {{
      if (a.style.display === 'none') return 1;
      if (b.style.display === 'none') return -1;
      const aVal = parseInt(a.querySelector('.ci-score-num')?.textContent || 0);
      const bVal = parseInt(b.querySelector('.ci-score-num')?.textContent || 0);
      return bVal - aVal;
    }});
    main.forEach((el, i) => {{
      const rank = el.querySelector('.ci-rank');
      if (rank) rank.textContent = '#' + (i + 1);
    }});
  }} else {{
    // Restore original sort
    sortBy(currentSort);
    return;
  }}

  // Update bar widths
  const maxVal = Math.max(...main.filter(el => el.style.display !== 'none')
    .map(el => parseInt(el.querySelector('.ci-score-num')?.textContent || 0)));
  main.forEach(el => {{
    const val  = parseInt(el.querySelector('.ci-score-num')?.textContent || 0);
    const fill = el.querySelector('.ci-bar-fill');
    if (fill) fill.style.width = maxVal > 0 ? Math.round((val / maxVal) * 100) + '%' : '0%';
  }});

  [...main, ...emerging].forEach(el => catList.appendChild(el));
}}

function clearSearch() {{
  const el = document.getElementById('search');
  if (el) el.value = '';
  searchQuery = '';
  document.getElementById('search-results-panel').style.display = 'none';
  document.querySelectorAll('.cat-item').forEach(el => el.style.display = '');
}}

function filterQuestions(query) {{
  searchQuery = query.toLowerCase().trim();
  const searchPanel = document.getElementById('search-results-panel');
  const emptyState  = document.getElementById('empty-state');

  if (searchQuery.length < 2) {{
    searchPanel.style.display = 'none';
    document.querySelectorAll('.cat-item').forEach(el => el.style.display = '');
    if (currentCat !== null) {{
      document.getElementById('panel-' + currentCat).style.display = 'block';
    }} else {{
      emptyState.style.display = 'flex';
    }}
    return;
  }}

  document.querySelectorAll('.q-panel:not(#search-results-panel)').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.cat-item').forEach(el => el.classList.remove('active'));
  emptyState.style.display = 'none';
  searchPanel.style.display = 'block';
  document.getElementById('right-inner').scrollTop = 0;

  let count = 0;
  const matchedCats = new Set();
  document.querySelectorAll('.sr-row').forEach(row => {{
    const match = (row.dataset.text || '').includes(searchQuery);
    row.classList.toggle('hidden', !match);
    if (match) {{ count++; matchedCats.add(row.dataset.cat); }}
  }});

  document.getElementById('search-meta').textContent =
    count + ' result' + (count !== 1 ? 's' : '') +
    ' across ' + matchedCats.size + ' topic' + (matchedCats.size !== 1 ? 's' : '');

  document.querySelectorAll('.cat-item').forEach(item => {{
    item.style.display = matchedCats.has(item.dataset.name) ? '' : 'none';
  }});
}}

function sortBy(col) {{
  currentSort = col;
  const catList  = document.getElementById('cat-list');
  const items    = Array.from(catList.querySelectorAll('.cat-item'));
  const emerging = items.filter(el => el.classList.contains('cat-item-emerging'));
  const main     = items.filter(el => !el.classList.contains('cat-item-emerging'));

  main.sort((a, b) => {{
    if (col === 'calls')     return parseInt(b.dataset.calls)     - parseInt(a.dataset.calls);
    if (col === 'questions') return parseInt(b.dataset.questions) - parseInt(a.dataset.questions);
    return 0;
  }});

  main.forEach((el, i) => {{
    const rank = el.querySelector('.ci-rank');
    if (rank) rank.textContent = '#' + (i + 1);
  }});

  [...main, ...emerging].forEach(el => catList.appendChild(el));

  const maxVal = Math.max(...main.map(el =>
    parseInt(col === 'calls' ? el.dataset.calls : el.dataset.questions)));
  [...main, ...emerging].forEach(el => {{
    const val  = parseInt(col === 'calls' ? el.dataset.calls : el.dataset.questions);
    const fill = el.querySelector('.ci-bar-fill');
    if (fill) fill.style.width = Math.round((val / maxVal) * 100) + '%';
    const num = el.querySelector('.ci-score-num');
    if (num) num.textContent = val;
    const sub = el.querySelector('.ci-score-sub');
    if (sub) sub.textContent = col === 'calls' ? 'unique calls' : 'questions';
  }});

  const sel = document.getElementById('sort-select');
  if (sel) sel.value = col;
}}

function toggleDeltas() {{
  const catList = document.getElementById('cat-list');
  const btn     = document.getElementById('delta-toggle');
  const active  = catList.classList.toggle('deltas-visible');
  if (btn) {{
    btn.classList.toggle('active', active);
    btn.innerHTML = active ? btn.dataset.onLabel : btn.dataset.offLabel;
  }}
}}

document.addEventListener('DOMContentLoaded', () => {{
  const first = document.querySelector('.cat-item:not(.cat-item-emerging)');
  if (first) selectCat(parseInt(first.dataset.cat));
}});
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ Written: {output_path}")
    return output_path


if __name__ == "__main__":
    import os as _os
    with open("results.json") as f:
        data = json.load(f)

    ranked          = data["ranked"]
    total_questions = data["total_questions"]
    from_date       = data["date_range"]["from"]
    to_date         = data["date_range"]["to"]
    resource_map    = data.get("resource_map", {})

    # Load deltas + compare_period from snapshots.json if available
    deltas         = {}
    compare_period = None
    if _os.path.exists("snapshots.json"):
        with open("snapshots.json") as f:
            store = json.load(f)
        snaps = store.get("snapshots", [])
        if len(snaps) >= 2:
            prev     = snaps[-2]
            curr     = snaps[-1]
            prev_map = {c["name"]: c for c in prev["categories"]}
            curr_map = {c["name"]: c for c in curr["categories"]}
            for name, cat in curr_map.items():
                if name in prev_map:
                    deltas[name] = {
                        "call_delta": cat["total_calls"] - prev_map[name]["total_calls"],
                        "rank_delta": prev_map[name]["rank"] - cat["rank"],
                    }
            compare_period = {"from": prev["from_date"], "to": prev["to_date"]}

    print(f"  Loaded {len(resource_map)} resource mappings from results.json")
    if deltas:
        print(f"  Loaded deltas from snapshots.json ({len(deltas)} categories, compare: {compare_period})")
    write_html(ranked, total_questions, from_date, to_date,
               resource_map=resource_map, deltas=deltas, compare_period=compare_period)
