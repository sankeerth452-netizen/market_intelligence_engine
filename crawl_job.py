"""
crawl_job.py — the weekly competitor crawl, run by Render's scheduled Cron Job.

It crawls each competitor's sitemap and updates the shared database, so the web
app's Competitors view shows which pages rivals have newly published. Runs against
the SAME Postgres as the web service (DATABASE_URL), so results appear live.

Run locally:   python crawl_job.py
On Render:     a `type: cron` service (see render.yaml) runs it weekly.
"""
import os

import competitors
import store


def main():
    engine = store.connect(os.environ.get("DATABASE_URL", "sqlite:///webapp.db"))
    results = competitors.refresh(engine)
    for r in results:
        status = "ok" if r["ok"] else f"skipped ({r['note']})"
        print(f"[crawl] {r['name']:<16} {status:<28} found={r['found']} new={r['added']}")
    ok = sum(1 for r in results if r["ok"])
    print(f"[crawl] done — {ok}/{len(results)} sites crawled")


if __name__ == "__main__":
    main()
