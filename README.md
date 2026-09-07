# cc-cockpit

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
cc-cockpit calibrate 21    # teach it the real ceiling (see below)
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

## Calibrating against the real limit

Anthropic does not publish the plan limit, and it is nowhere on disk — but the
CLI does show a percentage (`/usage`, or the plan panel). Tell cc-cockpit that
number and it derives the ceiling:

```bash
cc-cockpit calibrate 21              # "21% used" in the current 5h window
cc-cockpit calibrate 63 --window week
cc-cockpit calibrate                 # show the samples and the implied ceiling
cc-cockpit calibrate --reset
```

Each sample stores `consumption ÷ percentage`; the ceiling is the median of the
samples, so a couple of readings absorb the delay between seeing the number and
typing it. Ceilings are picked in order of trust: `limits` in the config (set by
you) → calibration → your historical peak. The dashboard says which one is in
use.

The implied ceiling holds while your model mix stays roughly the same, since the
weighting behind Anthropic's percentage is not documented. Recalibrate after a
plan change — and note that promos ("+50% weekly limits" and the like) move the
weekly ceiling while they last.

## How it works

```
~/.claude/projects/**/*.jsonl   transcripts (usage per request)
~/.claude/sessions/*.json       one entry per live CLI  ─┐
                                                          ├─> cockpit/
      ~/.local/share/cc-cockpit/events.ndjson  <──────────┘
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

## Honest limitations

- Without calibration and without `limits`, the percentage is relative to your
  own history, not to the real plan limit.
- Models released after this version fall back to their family price (`opus`,
  `sonnet`, `haiku`, `fable`) until they are added to `pricing.py`.
- `<synthetic>` rows are responses the CLI generates locally: they show up in
  the request count and cost nothing.
