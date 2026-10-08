# WireGuard Monitor

A Flask-based web application that provides a real-time monitoring dashboard for WireGuard VPN on Linux. Displays peer status, live throughput and latency graphs, and firewall rules — with full WireGuard config and firewall ruleset export/import, all secured behind user authentication.

---

## Features

- 🔑 **User authentication** – Login/logout with configurable credentials; multi-user management via the web UI (create, delete, change passwords)
- 📊 **WireGuard status** – Interface name, public key, listening port, and per-peer status table (endpoint, allowed IPs, last handshake, connected/disconnected state)
- 📈 **Throughput graphs** – Per-peer RX/TX bytes-per-second chart, refreshed every 5 seconds. Rate is only computed across intervals where the peer had a live WireGuard handshake — WireGuard can report a slow trickle of raw "sent" bytes toward a peer with no recent handshake (traffic attempted from elsewhere on the network, counted before delivery is ever confirmed), and that isn't meaningful as this peer's throughput, so a Disconnected peer's chart shows flat 0 regardless of what the raw counters do. Grid layout is adjustable (2/3/4 columns, remembered per-browser), and graphs can be manually reordered by dragging them; each graph type keeps its own order in browser local storage. RX/TX default to WireGuard's own convention (RX = server received *from* the peer, TX = server sent *to* the peer) — enable "Peer view" per peer on the [Options page](#options-page) to show that peer's chart from its own point of view instead
- 📡 **Ping latency graphs** – Per-peer round-trip time chart, refreshed every 5 seconds. Only actively probes peers with a recent WireGuard handshake — a Disconnected peer is shown as "Offline" on its charts instead of being pinged, since WireGuard's own handshake (not this app's ping) is what detects a peer coming back online. Ping graphs can also be manually reordered independently from Throughput graphs by dragging them.
- 🔥 **Firewall rules page** – Displays both `iptables` and `nftables` rulesets
- 💾 **Firewall save / restore** – Snapshot and reload active firewall rules server-side
- ⬆️ **Firewall export / import** – Download the live ruleset as a file; upload and immediately apply a previously exported file (nftables import auto-rolls back on failure)
- 📥 **WireGuard config export** – Download all `*.conf` files from `/etc/wireguard/` as a single file or ZIP archive when multiple interfaces are present
- 📤 **WireGuard config import** – Upload a `.conf` file directly from the dashboard to `/etc/wireguard/` with mode `0600`
- 🏷 **Peer naming** – Assign friendly names to peers; names persisted across restarts
- 🌗 **Light/Dark mode** – Toggle in the navbar (top right, next to your username); choice is remembered per-browser
- 🏷️ **Version display** – Current app version shown in the footer of every page and in `/api/status`, so you can always tell what's actually deployed

---

## Quick Start

### Prerequisites

- Python 3.10+
- Linux with WireGuard tools (`wg`) installed — the UI gracefully degrades when `wg` is absent
- Root or `sudo` access (required to read WireGuard status and manage firewall rules)

## Running as a systemd Service (Auto-start on Boot)

A ready-to-use `wireguard-monitor.service` unit file is included.

### 1 — Get the code into a permanent location

Pick **one** of the following. Both end with the app living at
`/opt/wireguard-monitor`, owned by root, ready for the service to run.

**Fresh clone:**

The service runs as root from `/opt/wireguard-monitor`, so create the virtual
environment and install dependencies there with `sudo`. On Ubuntu/Debian,
install `python3-venv` first; without it, the virtual environment may not be
created, and systemd will fail to execute the configured Python path.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
sudo git clone https://github.com/masterlog80/wireguard-monitor.git /opt/wireguard-monitor
sudo python3 -m venv /opt/wireguard-monitor/venv
sudo /opt/wireguard-monitor/venv/bin/python -m pip install --upgrade pip
sudo /opt/wireguard-monitor/venv/bin/python -m pip install -r /opt/wireguard-monitor/requirements.txt
```

**Verify the service's Python environment exists before starting systemd:**

```bash
test -x /opt/wireguard-monitor/venv/bin/python && echo "Virtual environment OK"
sudo /opt/wireguard-monitor/venv/bin/python -m pip check
```

Or, using `install.sh` (see [Clone & run (development)](#clone--run-development)
below for what it does — GitHub token auth and pending-PR selection included):

```bash
sudo REPO=masterlog80/wireguard-monitor DIRNAME=/opt/wireguard-monitor \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/masterlog80/wireguard-monitor/main/install.sh)"
```

### 2 — Create the data directory and the credentials

```bash
sudo mkdir -p /var/lib/wireguard-monitor
sudo tee /etc/wireguard-monitor.env > /dev/null <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF
sudo chmod 600 /etc/wireguard-monitor.env
```

Folder `/var/lib/wireguard-monitor` is where the service persists `users.json`,
`peer_names.json`, and firewall snapshots (see `Environment=` in the unit file).
Kept separate from `/opt/wireguard-monitor` so re-deploying the app code never 
touches your data.

**Edit `ADMIN_PASSWORD` above before continuing** — either replace `changeme`
with your own password, or generate a random one and make sure to note it
down, e.g.:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(16))"
```

> ⚠️ Just like in the Quick Start, **these credentials are only applied the
> first time the service starts** (when `/var/lib/wireguard-monitor/users.json`
> doesn't exist yet). If you restart the service after editing
> `ADMIN_PASSWORD` here and it still doesn't work, that file already exists —
> see [Resetting the admin password](#resetting-the-admin-password) below.

### 3 — Install and enable the service

```bash
sudo cp /opt/wireguard-monitor/wireguard-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wireguard-monitor
sudo systemctl status wireguard-monitor
```

Then check the startup log to confirm your credentials were actually applied:

```bash
sudo journalctl -u wireguard-monitor -n 20 --no-pager
```

You should see `created initial admin account 'admin'`. If instead you see
`ADMIN_USERNAME/ADMIN_PASSWORD are ignored while this file exists`, a
`users.json` from an earlier attempt is already in place — see the next
section.

> ⚠️ **Already have this service installed?** Pulling a new version of this
> repo does **not** update the copy systemd is actually running from — you
> installed a *copy* of `wireguard-monitor.service` at
> `/etc/systemd/system/` in step 3, and that copy is what's live. After
> `git pull`, always re-run this step's three commands (`cp` the updated
> unit file, `daemon-reload`, `restart`) to pick up any changes to the
> service file itself, e.g. new `Environment=` lines.

### Uninstall

```bash
sudo systemctl stop wireguard-monitor
sudo systemctl disable wireguard-monitor
sudo rm /etc/systemd/system/wireguard-monitor.service
sudo systemctl daemon-reload
sudo rm -rf /opt/wireguard-monitor
sudo rm -rf /var/lib/wireguard-monitor
sudo rm -f /etc/wireguard-monitor.env
```

### Clone & run (development)

The fastest way to get a local checkout is `install.sh`, which additionally
handles GitHub token authentication (this repo is private) and lets you pick
up an open, not-yet-merged pull request instead of `main`:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/masterlog80/wireguard-monitor/main/install.sh)"
```

It prompts for a GitHub token (or reads `GH_TOKEN`/`GITHUB_TOKEN` from the
environment if already set), lists any open PRs so you can choose one, clones
into `./wireguard-monitor`, and sets up a `venv/` with dependencies installed.
From there, continue exactly as in the "by hand" steps below, starting from
`cd wireguard-monitor` (skip the `git clone`/`venv`/`pip install` lines,
since the script already did those) — export the credentials, then
`venv/bin/python run.py`. See the comments at the top of the script for the
environment variables it accepts (`REPO`, `DIRNAME`).

Equivalently, by hand:

```bash
git clone https://github.com/masterlog80/wireguard-monitor.git
cd wireguard-monitor

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=changeme   # change this!
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

python run.py
```

Open **http://\<your-server\>:5000** in a browser and log in with the `ADMIN_USERNAME`/`ADMIN_PASSWORD` you exported above.

> ⚠️ **These credentials only take effect the first time the app starts** — specifically, the first time it needs to create `users.json` (or whatever `USERS_FILE` points to). If that file already exists from an earlier run, `ADMIN_USERNAME`/`ADMIN_PASSWORD` are silently ignored and the *original* credentials still apply. If you can't log in, check the terminal/log output on startup — it always prints one of:
> - `created initial admin account '<user>'` — a fresh account was just seeded from your env vars, or
> - `ADMIN_USERNAME/ADMIN_PASSWORD are ignored while this file exists` — an existing account was loaded instead, and your env vars had no effect.
>
> See **[Resetting the admin password](#resetting-the-admin-password)** below to fix this.

---

## Options Page

A dedicated `/options` page (linked in the navbar) holds settings that apply
across the app rather than to a single view. Currently:

- **Peer View** — a switch per peer controlling whether that peer's
  Dashboard Throughput chart is labeled from the server's point of view
  (the default) or that peer's own point of view. See the Throughput
  graphs bullet above for what this means. Stored per-browser, same as
  the light/dark and chart-column preferences.

---

## Screenshots

> Shown in the default dark theme. A light mode is also available via the toggle in the navbar (top right, next to your username).

### Login Page
![Login Page](https://github.com/user-attachments/assets/395fbf9c-d054-4601-97cf-e885b5493417)

### Dashboard
![Dashboard](https://github.com/user-attachments/assets/5d78af9c-6891-4e8b-b583-9fb7cd21f7c7)

### Firewall Rules
![Firewall Rules](https://github.com/user-attachments/assets/b7baa1c6-ae57-4a28-823c-0c4606a95a05)

### User Management
![User Management](https://github.com/user-attachments/assets/16ebcefe-f74c-4bfa-8ad8-b1de67572ae8)

### Create User
![Create User](https://github.com/user-attachments/assets/c6206fae-789f-45bd-8417-7f788198837c)

### Option Page
<img width="2940" height="1284" alt="image" src="https://github.com/user-attachments/assets/e4037079-6000-4895-9933-34f204857c71" />


---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_USERNAME` | `admin` | Login username |
| `ADMIN_PASSWORD` | `changeme` | Login password — **change in production!** |
| `SECRET_KEY` | random | Flask secret key for session signing |
| `WG_INTERFACE` | (auto) | Force a specific WireGuard interface name |
| `MAX_HISTORY` | `60` | Number of 5-second data points kept per peer |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` once served over HTTPS to mark cookies `Secure` |
| `WTF_CSRF_ENABLED` | `true` | CSRF protection for all state-changing requests — leave enabled in production |
| `WTF_CSRF_TIME_LIMIT` | *(none)* | Seconds before a page's CSRF token expires. Unset by default since this is a long-running dashboard people leave open for hours; set a value (e.g. `3600`) to reintroduce Flask-WTF's normal expiry if you want tighter security |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `10` | Failed login attempts allowed per client IP before a temporary lockout |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Sliding window (seconds) used for the login lockout above |
| `MAX_CONTENT_LENGTH` | `16777216` (16 MiB) | Maximum size of any request body (JSON payloads, config/rules uploads) |
| `MIN_PASSWORD_LENGTH` | `8` | Minimum password length enforced when creating a user or changing a password |
| `FIREWALL_SAVE_DIR` | `firewall_saves` (relative) | Directory used to store saved iptables/nftables rule snapshots. The bundled systemd service overrides this to `/var/lib/wireguard-monitor/firewall_saves`, since the default relative path would otherwise resolve inside the service's read-only `/opt/wireguard-monitor` |

---

## Security Notes

- **Every account has equal, full-admin privileges.** There is no read-only or restricted role — anyone who can log in can manage users, view/change firewall rules, and restart WireGuard. Only create accounts for people you trust with root-adjacent access to the host.
- **All state-changing requests are CSRF-protected** (Flask-WTF). Templates and the dashboard/firewall JavaScript automatically attach the required token — no action needed unless you're scripting against the API, in which case first `GET /login` (or any page) to obtain a token from the `csrf-token` meta tag or a form's hidden field, then send it back via the `X-CSRFToken` header or `csrf_token` form field.
- **Login attempts are rate-limited** per client IP (see `LOGIN_RATE_LIMIT_*` above) to slow down password guessing. The limiter is in-memory and resets on restart — fine for a single-process homelab deployment, not a substitute for a proper WAF/fail2ban if you expose this beyond your LAN.
- **Peer display names and other user-supplied strings are escaped client-side before being inserted into the page**, so a malicious or compromised account can't inject script via a peer rename, an uploaded filename, or an error message reflected back from a failed firewall-rule import.
- Set `SESSION_COOKIE_SECURE=true` once you're serving this behind HTTPS (e.g. a reverse proxy with a TLS certificate) so the session cookie is never sent in the clear.

---

### Resetting the admin password

The admin account is only *seeded* from `ADMIN_USERNAME`/`ADMIN_PASSWORD` —
once the users file exists, those env vars are permanently ignored on every
future start (the app logs which case applies every time it starts, see
above). Two ways to fix a "can't log in" situation:

- **You can still log in as some account:** go to **Users** in the navbar and
  change the password from there instead of via env vars.
- **You're fully locked out:** stop the service, delete the users file so it
  gets re-seeded from your current `ADMIN_USERNAME`/`ADMIN_PASSWORD`, then
  restart.

  ```bash
  # systemd service:
  sudo systemctl stop wireguard-monitor
  sudo rm /var/lib/wireguard-monitor/users.json
  sudo systemctl start wireguard-monitor

  # Quick Start / development run (from the repo directory):
  rm users.json
  python run.py
  ```

  This resets **all** accounts, not just admin — recreate any other users
  afterward from the Users page.

### Troubleshooting: service fails with `203/EXEC`

If `systemctl status wireguard-monitor` shows
`status=203/EXEC`, systemd could not execute the command in the service's
`ExecStart` line. This installation expects the interpreter at
`/opt/wireguard-monitor/venv/bin/python`. A common cause is that the virtual
environment was never created (for example, because `python3-venv` was not
installed), or it was removed while updating the application.

Check whether the interpreter exists:

```bash
ls -l /opt/wireguard-monitor/venv/bin/python
```

If it is missing, recreate the virtual environment and reinstall the
requirements. This does not delete the application code or persistent data
under `/var/lib/wireguard-monitor`:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
sudo systemctl stop wireguard-monitor
sudo python3 -m venv /opt/wireguard-monitor/venv
sudo /opt/wireguard-monitor/venv/bin/python -m pip install --upgrade pip
sudo /opt/wireguard-monitor/venv/bin/python -m pip install -r /opt/wireguard-monitor/requirements.txt
sudo systemctl daemon-reload
sudo systemctl reset-failed wireguard-monitor
sudo systemctl start wireguard-monitor
sudo systemctl status wireguard-monitor --no-pager
sudo journalctl -u wireguard-monitor -n 50 --no-pager
```

Do not point `ExecStart` at the system Python as a workaround: the app's
dependencies are installed in the virtual environment and system Python may
not have them. If the interpreter exists but the service still fails, inspect
the journal output for the next error.

---
### Common service management commands

| Task | Command |
|------|---------|
| Check status | `sudo systemctl status wireguard-monitor` |
| View live logs | `sudo journalctl -u wireguard-monitor -f` |
| Stop | `sudo systemctl stop wireguard-monitor` |
| Start | `sudo systemctl start wireguard-monitor` |
| Restart | `sudo systemctl restart wireguard-monitor` |
| Disable auto-start | `sudo systemctl disable wireguard-monitor` |

---

## Versioning

The current version is tracked in a single `VERSION` file at the repo root
(a plain `MAJOR.MINOR.PATCH` string, no `v` prefix) and shown in the footer
of every page and in the `/api/status` response, so it's always possible to
tell exactly what's deployed on a given host — useful when comparing a
running instance against these docs, or reporting a bug.

**Every change to the app should bump `VERSION`** as part of that change,
following normal semver judgment: PATCH for fixes, MINOR for new
backwards-compatible features, MAJOR for breaking changes. There's no build
step involved — just edit the file and commit it alongside the rest of the
change.

---

## Running Tests

```bash
pip install pytest
python -m pytest tests.py -v
```

---

## Project Structure

```
├── run.py
├── config.py
├── requirements.txt
├── tests.py
├── VERSION
├── install.sh
├── wireguard-monitor.service
└── app/
    ├── __init__.py
    ├── auth.py
    ├── routes.py
    ├── users.py
    ├── wireguard.py
    ├── firewall.py
    ├── peer_names.py
    ├── templates/
    │   ├── base.html
    │   ├── login.html
    │   ├── dashboard.html
    │   ├── firewall.html
    │   ├── users.html
    │   └── options.html
    └── static/
        ├── favicon.svg
        ├── css/style.css
        ├── js/app.js          # shared helpers: CSRF-attaching fetch, HTML escaping
        ├── js/dashboard.js
        ├── js/options.js
        └── vendor/   # Bootstrap 5, Bootstrap Icons, Chart.js (vendored locally)
```

---

## License

MIT
