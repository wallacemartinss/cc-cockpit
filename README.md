# cc-cockpit

[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Claude Code usage panel for GNOME: a tray indicator with a consumption ring,
a local dashboard and a terminal summary.

Everything is read from what Claude Code already writes under `~/.claude`. It
makes no network calls, reads no credentials and sends nothing anywhere.

The interface follows your OS language — English, Portuguese and Spanish are
bundled — and can be pinned in the config file or with `--lang`.

## What it shows

| | |
|---|---|
| **5h block** | how much the current rate-limit window has consumed, time to reset, hourly pace, projection to the end of the block, and how long until the reference ceiling. The window starts at the exact timestamp of its first request — not rounded to the hour — which is what makes the reset match what the CLI reports |
| **7 days / today / month** | rolling totals, as a percentage of your own historical peak |
| **Open sessions** | every live CLI instance: name, project, `busy`/`idle`, uptime, RAM, pid, and what that session has consumed |
| **Projects** | ranked by consumption across the whole history |
| **Blocks, days and hours** | time series showing when you actually spend |
| **Token mix** | input / output / cache write 5m / cache write 1h / cache read, with the cache hit rate |
| **Models, effort and subagents** | where the consumption really goes |

Usage is measured in **API-equivalent USD**: what those messages would cost on
the pay-as-you-go API. On a Pro/Max plan none of it is billed — the number works
as a weight unit for consumption and shows how much the plan returns.

## Install

```bash
sudo apt install gir1.2-ayatanaappindicator3-0.1   # tray only
./install.sh
cc-cockpit          # tray + dashboard in the background
```

`install.sh` creates `~/.local/bin/cc-cockpit` and registers the GNOME autostart
entry.

```bash
cc-cockpit report          # terminal summary
cc-cockpit serve --open    # dashboard only (http://127.0.0.1:8765)
cc-cockpit json            # everything as JSON, for scripting
cc-cockpit collect         # ingest new transcripts and exit
cc-cockpit config          # config path and contents
cc-cockpit statusline --install   # capture the official numbers (see below)
cc-cockpit --lang es report
```

## Configuration

`~/.config/cc-cockpit/config.json`:

```jsonc
{
  "language": "auto",            // auto (follows the OS) | en | pt | es
  "block_hours": 5,
  "limits": { "block_usd": null, "week_usd": null },  // null = auto-calibrate
  "tray_metric": "block",        // block | week | today | none
  "menu_bar_style": "blocks",    // blocks | dots | emoji (emoji is the colourful one)
  "tray_show_cost": true,
  "refresh_seconds": 20,
  "plan_monthly_usd": null,      // e.g. 200 -> shows how many times the plan paid for itself
  "plan_name": "",
  "local_currency": null,        // e.g. {"code":"BRL","symbol":"R$","rate":5.4}
  "dashboard_port": 8765,
  "warn_pct": 70,
  "critical_pct": 90
}
```

## The real numbers, from the statusline

Two things cannot be derived from local transcripts:

1. **The limit belongs to the account, not to the CLI.** Whatever you consume in
   the Claude app counts against the same window and leaves nothing on disk, so
   a window can start before your first local request.
2. **The weekly limit is a fixed window** with its own reset time, not the
   rolling 7 days a local reader would assume.

Claude Code pipes a JSON payload into the statusline command on every render,
and it carries exactly what the plan panel shows:

```json
"rate_limits": {
  "five_hour": {"used_percentage": 23, "resets_at": 1788800000},
  "seven_day": {"used_percentage": 3,  "resets_at": 1788790000}
}
```

Register the capture once — no credentials, no undocumented endpoint:

```bash
cc-cockpit statusline --install
```

It writes `statusLine` into `~/.claude/settings.json`, keeping a `.bak`. If you
already had one, it is chained rather than replaced, so its output still shows
in the CLI. The captured payload also carries the **context window percentage
per session**, which the dashboard shows next to each open session.

From then on the official percentage is the source of truth, and it reveals the
real ceiling — `local consumption ÷ official percentage` — so the currency
figures stay meaningful too.

### When there is no statusline data yet

Numbers fall back, in order of trust: **official** (statusline) → **anchored**
(what you typed) → **local estimate**. The middle one exists because a fresh
install has no capture yet:

```bash
cc-cockpit sync --block 23% --block-reset 1h55 --week 3% --week-reset 1h15
cc-cockpit sync            # show anchors, samples and implied ceilings
cc-cockpit sync --reset
```

Both the tray and the dashboard say which source is in use.

## How it works

```
~/.claude/projects/**/*.jsonl   transcripts (usage per request)
~/.claude/sessions/*.json       one entry per live CLI       ─┐
statusline payload (stdin)      official rate limits + context ├─> cockpit/
      ~/.local/share/cc-cockpit/events.ndjson  <───────────────┘
      ~/.local/share/cc-cockpit/panel.json     official snapshot
```

- `collector.py` reads each transcript **from the last offset**, so a refresh
  costs ~30 ms even with 190 MB of history.
- Events land in a dedicated NDJSON file. That matters: Claude Code **prunes
  transcripts after ~30 days**, and from the first collection onward cc-cockpit
  keeps the full history.
- Deduplication by `message.id:requestId`, so resuming a session is not counted
  twice.
- `sessions.py` validates each pid against `/proc` **and** compares the
  `starttime`, so a recycled pid is never mistaken for a live session.
- Prices live in `pricing.py`: cache writes at 1.25× (5m) and 2× (1h) of input,
  cache reads at 0.1× (0.025× on Fable 5.1). The transcript separates the two
  cache-write TTLs and the calculation uses that split instead of assuming 5m.
- `i18n.py` holds one catalogue for all three surfaces, plus locale-aware number
  and currency formatting.
- `panel.py` keeps the official snapshot and appends a line to
  `panel-history.ndjson` whenever the percentage changes.

## Honest limitations

- Without the statusline capture and without `limits`, the percentage is
  relative to your own history, not to the real plan limit.
- The statusline only refreshes while a CLI session is rendering. That is
  enough — what is not running cannot be consuming — but right after a long
  gap the percentage may lag until the next render.
- Consumption from the Claude app shows up in the official percentage, never in
  the local currency figures, which read Claude Code transcripts only.
- Models released after this version fall back to their family price (`opus`,
  `sonnet`, `haiku`, `fable`) until they are added to `pricing.py`.
- `<synthetic>` rows are responses the CLI generates locally: they show up in
  the request count and cost nothing.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with Anthropic.
