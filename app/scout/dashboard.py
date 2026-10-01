"""
Static dashboard generator.

Writes a single self-contained HTML page (site/index.html) from the job
store: today's new matches first, then every open Tier 1–3 role with
client-side filters, then source health. No server needed — GitHub Pages
serves it after each daily run.

Job descriptions and resumes are deliberately NOT embedded in the page.
"""
from __future__ import annotations

import html
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from app.scout.store import JobStore

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = ROOT / "site" / "index.html"

TIER_LABEL = {"tier_1": "Tier 1", "tier_2": "Tier 2", "tier_3": "Tier 3",
              "barrier": "Barrier", "do_not_pursue": "Skip"}
SHOWN_TIERS = {"tier_1", "tier_2", "tier_3", "barrier"}

PUBLIC_FIELDS = ("id", "company", "title", "location", "work_model", "url", "portal", "source",
                 "posted_date", "first_seen", "tier", "fit_score", "ats_readiness", "barriers",
                 "flags", "matched_keywords", "missing_supported", "compensation", "resume")


def _artifact_url() -> Optional[str]:
    server, repo, run_id = (os.getenv("GITHUB_SERVER_URL"), os.getenv("GITHUB_REPOSITORY"),
                            os.getenv("GITHUB_RUN_ID"))
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}#artifacts"
    return None


def build(store: Optional[JobStore] = None, out: Optional[Path] = None,
          today: Optional[date] = None) -> Path:
    store = store or JobStore.load()
    today = today or date.today()
    out = Path(out or DEFAULT_OUT)

    jobs = [{k: j.get(k) for k in PUBLIC_FIELDS}
            for j in store.open_jobs() if j.get("tier") in SHOWN_TIERS]
    jobs.sort(key=lambda j: (-(j["fit_score"] or 0), j["company"]))
    last_run = store.runs[-1] if store.runs else {}
    new_today = [j for j in jobs if j["first_seen"] == today.isoformat()
                 and j["tier"] in ("tier_1", "tier_2")]

    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "jobs": jobs,
        "run": last_run,
        "artifacts": _artifact_url(),
    }
    counts = {
        "new": len(new_today),
        "t1": sum(1 for j in jobs if j["tier"] == "tier_1"),
        "t2": sum(1 for j in jobs if j["tier"] == "tier_2"),
        "resumes": sum(1 for j in jobs if (j.get("resume") or {}).get("status") == "ready"),
    }
    page = _TEMPLATE
    page = page.replace("__DATE__", html.escape(today.strftime("%A, %B %-d, %Y")))
    for k, v in counts.items():
        page = page.replace(f"__{k.upper()}__", str(v))
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    (out.parent / ".nojekyll").write_text("")
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Job Scout</title>
<style>
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e4e2dc;--accent:#2f5d50;
--t1:#2f5d50;--t1bg:#e3efe9;--t2:#6a5521;--t2bg:#f5ecd6;--t3:#555;--t3bg:#ececec;--bar:#8a2f2f;--barbg:#f6e1e1}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--panel:#1e1e1e;--ink:#ececec;--muted:#9a9a9f;--line:#2e2e2e;
--accent:#8cc5b3;--t1:#9fd6c3;--t1bg:#1f332c;--t2:#e7c983;--t2bg:#3a3020;--t3:#bbb;--t3bg:#2c2c2c;--bar:#f0a3a3;--barbg:#3b2222}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:28px 16px 64px}
header h1{font-size:26px;margin:0;letter-spacing:-.01em}
header p{margin:4px 0 0;color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 30px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi b{display:block;font-size:28px;line-height:1.1}
.kpi span{color:var(--muted);font-size:13px}
h2{font-size:17px;margin:30px 0 12px}
.cards{display:grid;gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.card h3{margin:0;font-size:16px}
.card h3 a{color:inherit;text-decoration:none}.card h3 a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:13px;margin-top:2px}
.score{text-align:right;white-space:nowrap;font-size:13px;color:var(--muted)}
.score b{font-size:20px;color:var(--ink)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
.tier_1{color:var(--t1);background:var(--t1bg)}.tier_2{color:var(--t2);background:var(--t2bg)}
.tier_3{color:var(--t3);background:var(--t3bg)}.barrier{color:var(--bar);background:var(--barbg)}
.kw{margin-top:8px;font-size:13px}.kw em{font-style:normal;color:var(--muted)}
.flag{font-size:12px;color:var(--bar);margin-top:6px}
.actions{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
.btn{font-size:13px;padding:5px 10px;border-radius:8px;border:1px solid var(--line);color:var(--ink);text-decoration:none;background:transparent}
.btn.primary{background:var(--accent);color:var(--panel);border-color:var(--accent)}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filters input,.filters select{font:inherit;padding:7px 10px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink)}
.filters input{flex:1;min-width:180px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:14px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
td a{color:inherit}
.tablewrap{overflow-x:auto}
.empty{color:var(--muted);padding:16px;background:var(--panel);border:1px dashed var(--line);border-radius:12px}
.health li{margin:3px 0}.muted{color:var(--muted)}
footer{margin-top:40px;color:var(--muted);font-size:12px}
@media (max-width:640px){.hide-sm{display:none}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Job Scout</h1>
  <p>__DATE__ · senior TPM, portfolio &amp; AI program roles in Canada</p>
</header>

<section class="kpis">
  <div class="kpi"><b>__NEW__</b><span>new Tier 1–2 today</span></div>
  <div class="kpi"><b>__T1__</b><span>open Tier 1</span></div>
  <div class="kpi"><b>__T2__</b><span>open Tier 2</span></div>
  <div class="kpi"><b>__RESUMES__</b><span>tailored resumes ready</span></div>
</section>

<h2>New today</h2>
<div id="new" class="cards"></div>

<h2>All open matches</h2>
<div class="filters">
  <input id="q" type="search" placeholder="Search company, title, location…">
  <select id="tier"><option value="">All tiers</option><option value="tier_1">Tier 1</option>
    <option value="tier_2">Tier 2</option><option value="tier_3">Tier 3</option><option value="barrier">Barrier</option></select>
  <select id="src"><option value="">All sources</option><option value="board">Company boards</option><option value="adzuna">Adzuna</option></select>
</div>
<div class="tablewrap"><table>
  <thead><tr><th>Role</th><th class="hide-sm">Location</th><th>Tier</th><th>Fit</th><th class="hide-sm">ATS</th><th class="hide-sm">Found</th><th class="hide-sm">Resume</th></tr></thead>
  <tbody id="rows"></tbody>
</table></div>

<h2>Source health</h2>
<div id="health" class="card"></div>

<footer id="foot"></footer>
</div>

<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const tierName = {tier_1:"Tier 1",tier_2:"Tier 2",tier_3:"Tier 3",barrier:"Barrier"};
const flagText = {partial_description:"Scored on a short snippet — open the posting to confirm fit",
  location_unverified:"Location not stated — verify Canada eligibility",
  us_role_verify_authorization:"US role — verify work authorization"};

function resumeLink(j){
  const r = j.resume || {};
  if (r.status === "ready") return D.artifacts ? `<a href="${esc(D.artifacts)}">Download (${esc(r.file)})</a>` : esc(r.file);
  if (r.status === "needs_review") return `<span title="${esc((r.issues||[]).join('; '))}">Needs review</span>`;
  return '<span class="muted">—</span>';
}

function card(j){
  const kw = (j.matched_keywords||[]).slice(0,6).join(", ");
  const gaps = (j.missing_supported||[]).slice(0,5).join(", ");
  const flags = (j.flags||[]).map(f => flagText[f]||f).concat(j.barriers||[]);
  const comp = j.compensation ? ` · ${esc(j.compensation)}` : "";
  return `<article class="card"><div class="top"><div>
    <h3><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></h3>
    <div class="meta">${esc(j.company)} · ${esc(j.location||"Location n/a")}${j.work_model?" · "+esc(j.work_model):""}${comp}</div></div>
    <div class="score"><span class="pill ${j.tier}">${tierName[j.tier]||j.tier}</span><br><b>${j.fit_score}</b> fit · ${j.ats_readiness}% ATS</div></div>
    ${kw?`<div class="kw"><em>Matches:</em> ${esc(kw)}</div>`:""}
    ${gaps?`<div class="kw"><em>Add to resume (evidence-backed):</em> ${esc(gaps)}</div>`:""}
    ${flags.map(f=>`<div class="flag">⚠ ${esc(f)}</div>`).join("")}
    <div class="actions"><a class="btn primary" href="${esc(j.url)}" target="_blank" rel="noopener">View posting</a>
    <span class="btn">Resume: ${resumeLink(j)}</span></div></article>`;
}

const newJobs = D.jobs.filter(j => j.first_seen === D.today && (j.tier==="tier_1"||j.tier==="tier_2"));
document.getElementById("new").innerHTML = newJobs.length ? newJobs.map(card).join("")
  : '<div class="empty">No new Tier 1–2 roles today. The full list below is still current.</div>';

function render(){
  const q = document.getElementById("q").value.toLowerCase();
  const t = document.getElementById("tier").value, s = document.getElementById("src").value;
  const rows = D.jobs.filter(j => (!t||j.tier===t) && (!s||j.source===s) &&
    (!q || `${j.company} ${j.title} ${j.location}`.toLowerCase().includes(q)));
  document.getElementById("rows").innerHTML = rows.length ? rows.map(j => `<tr>
    <td><a href="${esc(j.url)}" target="_blank" rel="noopener"><b>${esc(j.title)}</b></a><br><span class="muted">${esc(j.company)}</span></td>
    <td class="hide-sm">${esc(j.location||"—")}</td><td><span class="pill ${j.tier}">${tierName[j.tier]||j.tier}</span></td>
    <td>${j.fit_score}</td><td class="hide-sm">${j.ats_readiness}%</td><td class="hide-sm">${esc(j.first_seen)}</td>
    <td class="hide-sm">${resumeLink(j)}</td></tr>`).join("") : '<tr><td colspan="7" class="muted">No roles match these filters.</td></tr>';
}
["q","tier","src"].forEach(id => document.getElementById(id).addEventListener("input", render));
render();

const r = D.run || {};
const srcs = Object.entries(r.sources||{}).map(([k,v]) => `${esc(k)} (${v})`).join(", ");
const errs = (r.source_errors||[]).map(e => `<li>⚠ <b>${esc(e.company)}</b> <span class="muted">${esc(e.source)}</span> — ${esc(e.error)}</li>`).join("");
document.getElementById("health").innerHTML = r.started_at ?
  `<p>Last run ${esc(r.started_at)}: fetched ${r.fetched} postings, ${r.passed_filter} passed filters, ${r.new} new, ${r.closed} closed.</p>
   <p class="muted">${srcs||"No sources returned postings."}</p>${errs?`<ul class="health">${errs}</ul>`:""}`
  : '<p class="muted">No runs yet.</p>';
document.getElementById("foot").textContent = `Generated ${D.generated} UTC by the daily scout workflow.`;
</script>
</body>
</html>
"""
