# How It Works

## Overview

This is a small self-hosted monitoring app for Juniper (Junos) switches. It
is a single FastAPI web server with three moving parts:

1. **Web UI** — add a switch, view its dashboard
2. **Collector** — SSHes into a switch and parses `show` command output
3. **Scheduler** — runs the collector for every switch once a day, in the
   background, so history builds up automatically

There is no separate agent to install on the switches — everything is
pulled over a normal SSH session using the switch's existing CLI, the same
way you would if you typed the commands yourself.

## Components

| File | Responsibility |
|---|---|
| `app/main.py` | FastAPI routes: the switch list/add-switch page, the per-switch dashboard page, and the JSON API the dashboard's JavaScript calls |
| `app/collector.py` | Opens an SSH session (via [Netmiko](https://github.com/ktbyers/netmiko)) to the switch, runs the `show` commands, and parses the text output into structured numbers (CPU %, memory %, temperature, interface counts, alarm counts, etc.) |
| `app/scheduler.py` | [APScheduler](https://apscheduler.readthedocs.io/) background job that calls the collector for every registered switch, once a day (02:00 server time by default) |
| `app/database.py` | SQLite storage: registered switches, every collection run (raw + parsed), and a time-series `metrics` table used to draw the graphs |
| `app/crypto.py` | Encrypts/decrypts switch passwords at rest (Fernet/AES) using a key file generated on first run |
| `app/templates/*.html` | The two pages: switch list + add-switch form, and the per-switch dashboard |
| `app/static/dashboard.js` | Fetches the JSON API and renders the Chart.js graphs on the dashboard |

## Data flow

1. You submit the "add switch" form (name, IP, port, username, password).
2. The password is encrypted and the switch record is saved to SQLite.
3. A background task immediately connects to the switch over SSH and runs
   this set of commands (see `COMMANDS` in `app/collector.py`):
   `show version`, `show system uptime`, `show chassis hardware`,
   `show chassis environment`, `show chassis routing-engine`,
   `show system storage`, `show system alarms`, `show chassis alarms`,
   `show interfaces terse`, `show interfaces extensive` (error/CRC counters),
   `show chassis power`, `show log messages | last 100`, `show arp`,
   `show ethernet-switching table summary`, `show lldp neighbors`.
4. The raw text output of each command is parsed into a summary (used for
   the dashboard's stat cards and raw-output panels) and a flat set of
   numeric metrics (CPU %, memory %, temperature, storage %, interfaces
   up/down, alarm counts, ARP/MAC table size, etc.).
5. Both the summary and the metrics are saved to SQLite — the summary as one
   row per collection run, the metrics as individual time-series rows so
   history can be queried per metric.
6. The scheduler repeats step 3–5 for every registered switch every day,
   building up history with no manual action needed. You can also trigger a
   run immediately with the "Collect Now" button on a switch's dashboard.
7. The dashboard page calls two JSON endpoints — `/api/switches/{id}/summary`
   (latest snapshot) and `/api/switches/{id}/history?metric=...` (time
   series) — and renders them as stat cards, Chart.js line/bar graphs, and
   raw-text panels for the version info and recent log lines.

## Why parsing is regex-based, not JSON

Junos supports `| display json` on many commands, but its structure varies
across hardware families and Junos releases. This app instead parses the
plain-text CLI output with targeted regular expressions per metric
(`parse_version`, `parse_uptime`, `parse_routing_engine`, etc. in
`app/collector.py`). Each parser is wrapped so a failure (e.g. an unexpected
output format on your specific platform) only drops that one metric rather
than failing the whole collection — the raw command output is always stored
too, so you can see exactly what the switch returned even if a particular
number didn't parse.

If you add a new switch model/Junos version and a graph stays empty, check
`raw.<command_key>` in the `/api/switches/{id}/summary` response (or the
"Hardware & Version" / "Recent Log Messages" panels on the dashboard, which
show the raw text for two of the commands) to see the actual CLI output and
adjust the relevant regex.

## Post-deployment checklist

Once the service is up and reachable (see the main `README.md` for
deployment steps), do the following:

1. **Add your first switch.** Open `/switches`, fill in name/IP/port/
   username/password, submit. The app immediately runs a first collection
   in the background.
2. **Confirm the first collection succeeded.** Refresh `/switches` — the
   switch card should show a green `success` badge and a `last collected`
   timestamp within a few seconds. If it shows a red `error` badge, click
   into the switch's dashboard — the banner at the top shows the exact
   error (auth failure, timeout, unreachable host, etc.).
3. **Open the dashboard and sanity-check the graphs.** A single data point
   won't look like much of a graph yet — that's expected on day one. Use
   "Collect Now" a couple of times a few minutes apart if you want to see
   the line charts populate before the next scheduled run.
4. **Verify the raw data looks right for your platform.** Check the
   "Hardware & Version" and "Recent Log Messages" panels against what you'd
   expect from the switch. If a stat card shows `-` (missing), the
   corresponding regex parser likely doesn't match your Junos version's
   output format — see "Why parsing is regex-based" above.
5. **Confirm the daily scheduler is alive.** `journalctl -u juniper-monitor
   -f` (if running under systemd) should log `Adding job tentatively` /
   `Added job "collect_all"` at startup. The job itself fires once at 02:00
   server time — you don't need to wait a full day to trust it's wired up
   correctly, just confirm the job was scheduled.
6. **Add any remaining switches** the same way — each one gets its own name,
   its own dashboard, and its own independent daily collection.
7. **Restrict network access.** The web UI has no login of its own — make
   sure only trusted hosts/VPN can reach the port, or put a reverse proxy
   with auth + TLS in front of it if it needs to be reachable more broadly.
8. **Back up `$JMON_HOME`** (the SQLite database + `secret.key`) on whatever
   schedule you already use for other config/state on this host. Losing
   `secret.key` makes previously-stored switch passwords unrecoverable
   (you'd need to re-add those switches); losing the whole directory loses
   collection history too.
9. **Know the current limitations:** no built-in alerting/notifications on
   thresholds or alarms (today it's a dashboard you check, not a paging
   system); no UI to edit a switch's credentials after creation (delete and
   re-add it instead); single daily collection time shared by all switches
   (change the hour/minute in `scheduler.start()` in `app/scheduler.py` and
   restart the service if you need a different schedule).
