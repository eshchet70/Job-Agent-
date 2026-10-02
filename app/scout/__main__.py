"""
Daily scout command line.

  python -m app.scout run          # discover + score, update data/scout/jobs.json
  python -m app.scout resumes      # tailor resumes for new Tier 1–2 jobs (needs ANTHROPIC_API_KEY)
  python -m app.scout dashboard    # build site/index.html
  python -m app.scout daily        # all three, in order (what the workflow runs)
  python -m app.scout check        # verify every watchlist board slug resolves
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def _run() -> None:
    from app.scout.pipeline import run
    report = run()
    print(f"Scout: fetched {report.fetched}, passed filters {report.passed_filter}, "
          f"new {report.new} (Tier 1: {report.new_tier1}, Tier 2: {report.new_tier2}), "
          f"closed {report.closed}")
    for err in report.source_errors:
        print(f"  ! {err['company']} [{err['source']}]: {err['error']}")


def _resumes() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Resume agent skipped: ANTHROPIC_API_KEY is not set.")
        return
    from app.agents.resume_agent import run_batch
    results = run_batch()
    print(f"Resume agent: {len(results)} job(s) processed")
    for r in results:
        print(f"  {r['status']:12} {r['job']}  {r.get('file') or r.get('error') or ''}")


def _dashboard() -> None:
    from app.scout.dashboard import build
    print(f"Dashboard written to {build()}")


def _check() -> int:
    import httpx
    from app.integrations.ats_boards import BoardError, BoardNotFound, USER_AGENT, fetch_board
    from app.scout.pipeline import load_config

    bad = 0
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
        for e in load_config()["watchlist"]:
            try:
                n = len(fetch_board(e["ats"], e["slug"], e["company"], c))
                print(f"  ok    {e['company']:<16} {e['ats']}:{e['slug']}  ({n} openings)")
            except (BoardNotFound, BoardError) as exc:
                bad += 1
                print(f"  FAIL  {e['company']:<16} {e['ats']}:{e['slug']}  {type(exc).__name__}")
    return 1 if bad else 0


def _llm_check() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    if not api_key or not api_key.strip():
        print("❌ ANTHROPIC_API_KEY is not set in .env")
        return 1
    print(f"Testing Anthropic Claude connection using model '{model}'...")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key.strip())
        resp = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        print(f"✅ Success: Claude model '{model}' responded successfully.")
        return 0
    except Exception as exc:
        print(f"❌ Anthropic API call failed: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.scout")
    parser.add_argument("command", choices=["run", "resumes", "dashboard", "daily", "check", "llm-check"])
    args = parser.parse_args(argv)
    if args.command == "run":
        _run()
    elif args.command == "resumes":
        _resumes()
    elif args.command == "dashboard":
        _dashboard()
    elif args.command == "check":
        return _check()
    elif args.command == "llm-check":
        return _llm_check()
    elif args.command == "daily":
        _run()
        _resumes()
        _dashboard()
    return 0


if __name__ == "__main__":
    sys.exit(main())
