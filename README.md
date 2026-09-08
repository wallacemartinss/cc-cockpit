# cc-cockpit

[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/cc-cockpit)](https://pypi.org/project/cc-cockpit/)
[![AUR](https://img.shields.io/aur/version/cc-cockpit)](https://aur.archlinux.org/packages/cc-cockpit)

A Claude Code usage panel for Linux: a tray indicator with a consumption ring,
a local dashboard and a terminal summary.

Everything is read from what Claude Code already writes under `~/.claude` — or
under each account's directory, if you run more than one. It makes no network
calls, reads no credentials and sends nothing anywhere.

The interface follows your OS language — English, Portuguese and Spanish are
bundled — and can be pinned in the config file or with `--lang`.

## What it shows

| | |
|---|---|
| **5h block** | how much the current rate-limit window has consumed, time to reset, hourly pace, projection to the end of the block, and how long until the reference ceiling. The window starts at the exact timestamp of its first request — not rounded to the hour — which is what makes the reset match what the CLI reports |
| **7 days / today / month** | rolling totals, as a percentage of your own historical peak |
| **Open sessions** | every live CLI instance: name, project, `busy`/`idle`, uptime, RAM, pid, and what that session has consumed. From the tray, each one opens a terminal in its own directory, resuming that conversation |
| **Projects** | ranked by consumption across the whole history |
| **Blocks, days and hours** | time series showing when you actually spend |
| **Token mix** | input / output / cache write 5m / cache write 1h / cache read, with the cache hit rate |
| **Models, effort and subagents** | where the consumption really goes |

Usage is measured in **API-equivalent USD**: what those messages would cost on
the pay-as-you-go API. On a Pro/Max plan none of it is billed — the number works
as a weight unit for consumption and shows how much the plan returns.

## The three surfaces

**The tray menu** is the glance. One section per account with its 5h and 7d
windows, then the day, the month, the live sessions and today's projects. A
session expands into its own detail — directory, context window, requests, pid,
memory — and offers to open a terminal there, resuming that conversation.
*Shown on the panel* picks which account the label speaks for.

It refreshes every twenty seconds without redrawing. The menu is exported over
dbusmenu and the panel draws it, so adding or removing an item tears the popup
down while you are reading it; a refresh that keeps the same shape only rewrites
the labels that actually changed, and an expanded session stays expanded.

**The dashboard** is the long look: gauges, sixty days of history, the last
twenty-four hours, projects, blocks, the token mix, models and effort. Open it
from the tray, or `cc-cockpit serve --open`. With more than one account it grows
a tab bar — one per account, plus **All accounts**.

**Settings** opens a real window rather than a submenu: a menu has nowhere to
type a number, and GNOME's appindicator extension flattens submenus to a single
level anyway. Four tabs — General, Accounts, Limits, Plan — each scrolling on
its own so nothing falls off a short screen, with Save always reachable below
them. Saving applies right away, without a restart.

## Install

**Debian / Ubuntu** — the `.deb` pulls in the GTK dependencies by itself:

```bash
# from the latest release
sudo apt install ./cc-cockpit_0.2.0_all.deb
cc-cockpit setup
nohup cc-cockpit tray >/dev/null 2>&1 &   # tray now, without logging out
```

**Arch** — from the [AUR](https://aur.archlinux.org/packages/cc-cockpit):

```bash
yay -S cc-cockpit    # or paru, or makepkg -si
cc-cockpit setup
nohup cc-cockpit tray >/dev/null 2>&1 &   # tray now, without logging out
```

**Any distribution** — pipx, reusing the system GTK bindings:

```bash
sudo apt install python3-gi python3-cairo gir1.2-ayatanaappindicator3-0.1  # tray only
pipx install cc-cockpit --system-site-packages
cc-cockpit setup
nohup cc-cockpit tray >/dev/null 2>&1 &   # tray now, without logging out
```

`--system-site-packages` is what lets the virtualenv see PyGObject and pycairo.
Without them the tray is unavailable, and the dashboard and `report` still work.

**From a checkout**:

```bash
git clone https://github.com/wallacemartinss/cc-cockpit
cd cc-cockpit && ./install.sh
nohup cc-cockpit tray >/dev/null 2>&1 &   # tray now, without logging out
```

`cc-cockpit setup` registers the autostart entry, captures the statusline
(see below), checks the tray dependencies and runs the first collection.
`cc-cockpit setup --remove` undoes the autostart entry.

That autostart entry only fires on the next login, so the last line starts the
tray in the session you are already in — the icon shows up right away, with no
need to log out. It is the same command on every distribution, and it is only
needed once: from the next login on, autostart takes care of it. Running it
again is harmless — a second tray refuses to start and says which pid already
holds it.

```bash
cc-cockpit                 # tray + dashboard in the background
cc-cockpit report          # terminal summary
cc-cockpit serve --open    # dashboard only (http://127.0.0.1:8765)
cc-cockpit json            # everything as JSON, for scripting
cc-cockpit collect         # ingest new transcripts and exit
cc-cockpit config          # config path and contents
cc-cockpit accounts        # list the Claude Code accounts it reads
cc-cockpit --lang es report
```

## Desktops

The indicator is a StatusNotifierItem, not a GNOME applet, so it shows up on any
panel that hosts one:

| | |
|---|---|
| **GNOME** | needs the AppIndicator extension (`gnome-shell-extension-appindicator`); Ubuntu ships it enabled |
| **XFCE** | `xfce4-panel` 4.16+ hosts indicators through **Status Tray Items** — add that item to the panel. On 4.14, install `xfce4-statusnotifier-plugin` |
| **KDE Plasma** | nothing to install |
| **LXQt** | enable the Status Notifier plugin on the panel |
| **LXDE and other XEmbed-only trays** | the ring icon still shows, through the fallback in libayatana-appindicator, but the panel label (`45% · $12.30`) is lost — `snixembed` brings the indicator path back |

`cc-cockpit setup` prints what your desktop needs. GNOME is what this is
developed and tested on; the others follow from the protocol, not from separate
code paths. The dashboard and `report` depend on none of it.

## More than one account

A company Claude Code in `~/.claude` and a personal one in `~/.claude-pessoal`
are two subscriptions, not two folders. Each has **its own 5h and 7d windows**,
so cc-cockpit keeps them apart everywhere: separate history, separate rate-limit
snapshot, separate calibration.

```bash
cc-cockpit accounts --detect          # finds ~/.claude* and registers them
cc-cockpit accounts --primary empresa # whose number the tray label shows
cc-cockpit setup                      # re-registers the statusline in each one
```

**That last step is the one that matters.** The statusline payload carries the
account's rate limits but nothing that identifies the account, so each
`settings.json` gets `cc-cockpit statusline --account <id>`. Without it,
whichever CLI renders last overwrites the other's percentage, and the tray
reports the wrong subscription with nothing on screen to reveal the swap.

### What changes where

The **tray label** speaks for the primary account, and the ring takes the colour
of whichever account is **worst off** — a 95% on the one you are not watching
still turns the icon red. The menu gains one section per account and a *Shown on
the panel* submenu to switch between them.

The **dashboard** gains a tab per account, plus **All accounts**. That tab adds
up spend, tokens, projects and models, and deliberately shows one ring per
account instead of a combined percentage: two windows with different ceilings
and different resets have no meaningful sum.

### Naming them

Detection names an account after its directory, so `~/.claude` becomes
`default` — a poor label for what is usually the company account. There are two
different things to rename, and they carry different risk:

```bash
cc-cockpit accounts --label default=Empresa   # the name shown everywhere
cc-cockpit accounts --rename default=empresa  # the id, moving its history along
```

The **name** is editable in the Settings *Accounts* tab too. The **id** is not,
because it names `accounts/<id>/`, which holds months Claude Code has already
pruned; changing it has to move a directory, so it lives in `--rename`, which
also fixes up the statusline registrations.

### By hand

Accounts live in the config file:

```jsonc
"accounts": [
  {"id": "empresa", "label": "Empresa", "dir": "~/.claude"},
  {"id": "pessoal", "label": "Pessoal", "dir": "~/.claude-pessoal"}
],
"primary_account": "empresa"
```

With nothing configured, everything behaves exactly as before, against
`CLAUDE_CONFIG_DIR` or `~/.claude`. An existing history is moved into
`~/.local/share/cc-cockpit/accounts/<id>/` the first time the new version runs.

## Configuration

Everything the **Settings** window writes lives in `~/.config/cc-cockpit/config.json`, and any key missing from
the file is written back on start, so new options show up there:

```jsonc
{
  "language": "auto",            // auto (follows the OS) | en | pt | es
  "block_hours": 5,
  "limits": { "block_usd": null, "week_usd": null },  // null = automatic
  "tray_metric": "block",        // block | week | today | none
  "tray_show_cost": true,
  "menu_bar_style": "blocks",    // blocks | shade | fine | dots | squares |
                                 // line | braille | color_blocks | color_dots
  "refresh_seconds": 20,
  "plan_monthly_usd": null,      // e.g. 200 -> shows how many times the plan paid for itself
  "plan_name": "",
  "local_currency": null,        // e.g. {"code":"BRL","symbol":"R$","rate":5.4}
  "dashboard_port": 8765,
  "warn_pct": 70,
  "critical_pct": 90,
  "accounts": [],                // see "More than one account" above
  "primary_account": null        // null = the first one
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
<account>/projects/**/*.jsonl   transcripts (usage per request)
<account>/sessions/*.json       one entry per live CLI       ─┐
statusline payload (stdin)      official rate limits + context ├─> cockpit/
   ~/.local/share/cc-cockpit/accounts/<id>/events.ndjson <────┘
   ~/.local/share/cc-cockpit/accounts/<id>/panel.json    official snapshot
```

`<account>` is `CLAUDE_CONFIG_DIR` or `~/.claude` when nothing is configured,
and each configured account otherwise.

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
- `accounts.py` owns the roster and hands every stateful module its directory.
  Only money is ever added across accounts — rate limits, ceilings and anchors
  belong to one subscription and are never mixed.
- `terminal.py` knows twelve terminal emulators and what each wants, so a
  session can be reopened where it lives.

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
- Opening a terminal on a session starts a **new** one resuming that
  conversation; it cannot raise the window the session is already in. Window
  activation by pid is not available to an ordinary application on Wayland.
- With several accounts, the **All accounts** view adds up money but never
  percentages: each subscription has its own window, and one combined ring
  would be a number that does not exist anywhere.

## Packaging

`packaging/` holds the `.deb` build script and the Arch `PKGBUILD`; see
[packaging/README.md](packaging/README.md) for the release flow. A `v*` tag
builds the wheel, the sdist and the `.deb`, publishes to PyPI and attaches
everything to the GitHub release.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with Anthropic.
