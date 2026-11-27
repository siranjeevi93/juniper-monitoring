# Juniper Switch Monitoring

A self-hosted web app that logs into one or more Juniper (Junos) switches over
SSH, collects status information (uptime, CPU/memory, temperature, interfaces,
alarms, logs, etc.), and shows it on a dashboard with historical graphs. A
background scheduler re-collects data from every registered switch once a day
so you build up history automatically.

See [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) for the architecture and
post-deployment checklist.

## Prerequisites

- Python 3.10+
- `git`
- Network access from this machine to the Junos device(s) on SSH (port 22)
- Linux or macOS (Windows users: use WSL)

## 1. Clone the repo

```bash
git clone https://github.com/siranjeevi93/juniper-monitoring.git
cd juniper-monitoring
```

## 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Run it (quick test / foreground)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<this-machine-ip>:8000/switches` in a browser. You'll see a
form asking for a switch **name**, **IP**, **port**, **username**, and
**password** — submit it and the app logs in immediately to run the first
collection. Click the switch's name afterwards to see its dashboard.

By default, app data (SQLite database + the encryption key used for stored
switch passwords) is written to `~/.juniper_monitor`. Set the `JMON_HOME`
environment variable before starting the app to use a different location:

```bash
export JMON_HOME=/opt/juniper-monitor/data
```

Press `Ctrl+C` to stop. This foreground mode is fine for trying it out, but
it won't survive a reboot or a closed terminal — use the systemd setup below
for a real deployment.

## 4. Run it persistently (Linux, systemd)

```bash
sudo mkdir -p /opt/juniper-monitor
sudo cp -r app requirements.txt venv /opt/juniper-monitor/
sudo chown -R $(whoami):$(whoami) /opt/juniper-monitor
```

Edit `juniper-monitor.service` and set:
- `User=` to the Linux user that should run the app
- `WorkingDirectory=` / `ExecStart=` / `Environment="JMON_HOME=..."` to match
  wherever you copied the app (defaults assume `/opt/juniper-monitor`)

Then install and start it:

```bash
sudo cp juniper-monitor.service /etc/systemd/system/juniper-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now juniper-monitor
sudo systemctl status juniper-monitor
```

Check logs any time with:

```bash
journalctl -u juniper-monitor -f
```

## 5. Firewall

If a firewall is active on the host, allow the port you're serving on, e.g.:

```bash
sudo ufw allow 8000/tcp
```

## Updating to a newer version

```bash
cd juniper-monitoring
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart juniper-monitor   # if running under systemd
```

## Security notes

- The web UI itself has **no login** — anything that can reach the HTTP port
  can add/remove switches and read collected data. Only run this on a trusted
  LAN/VPN, or put it behind a reverse proxy with authentication and TLS if it
  needs to be reachable more broadly.
- Switch passwords are encrypted at rest (Fernet/AES) using a key generated
  on first run and stored in `$JMON_HOME/secret.key` with `0600` permissions.
  Anyone with read access to that key file plus the database can decrypt
  stored switch passwords — protect `$JMON_HOME` the same way you'd protect
  any credential store, and back it up somewhere safe (losing the key makes
  stored passwords unrecoverable; losing the whole directory loses history
  too).
- Nothing in this repo ever sends switch credentials anywhere except the
  switch itself.
