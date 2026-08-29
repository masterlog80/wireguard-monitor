# WireGuard Monitor

A Flask-based web application that provides a real-time monitoring dashboard for WireGuard VPN on Linux. Displays peer status, live throughput and latency graphs, and firewall rules — with full WireGuard config and firewall ruleset export/import, all secured behind user authentication.

---

## Features

- 🔑 **User authentication** – Login/logout with configurable credentials; multi-user management via the web UI (create, delete, change passwords)
- 📊 **WireGuard status** – Interface name, public key, listening port, and per-peer status table (endpoint, allowed IPs, last handshake, connected/disconnected state)
- 📈 **Throughput graphs** – Per-peer RX/TX bytes-per-second chart, refreshed every 5 seconds
- 📡 **Ping latency graphs** – Per-peer round-trip time chart, refreshed every 5 seconds
- 🔥 **Firewall rules page** – Displays both `iptables` and `nftables` rulesets
- 💾 **Firewall save / restore** – Snapshot and reload active firewall rules server-side
- ⬆️ **Firewall export / import** – Download the live ruleset as a file; upload and immediately apply a previously exported file (nftables import auto-rolls back on failure)
- 📥 **WireGuard config export** – Download all `*.conf` files from `/etc/wireguard/` as a single file or ZIP archive when multiple interfaces are present
- 📤 **WireGuard config import** – Upload a `.conf` file directly from the dashboard to `/etc/wireguard/` with mode `0600`
- 🏷 **Peer naming** – Assign friendly names to peers; names persisted across restarts
- 🌗 **Light/Dark mode** – Toggle in the navbar (top right, next to your username); choice is remembered per-browser

---

## Quick Start

### Prerequisites

- Python 3.10+
- Linux with WireGuard tools (`wg`) installed — the UI gracefully degrades when `wg` is absent
- Root or `sudo` access (required to read WireGuard status and manage firewall rules)

### Clone & run (development)

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
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `10` | Failed login attempts allowed per client IP before a temporary lockout |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Sliding window (seconds) used for the login lockout above |
| `MAX_CONTENT_LENGTH` | `16777216` (16 MiB) | Maximum size of any request body (JSON payloads, config/rules uploads) |
| `MIN_PASSWORD_LENGTH` | `8` | Minimum password length enforced when creating a user or changing a password |

---

## Security Notes

- **Every account has equal, full-admin privileges.** There is no read-only or restricted role — anyone who can log in can manage users, view/change firewall rules, and restart WireGuard. Only create accounts for people you trust with root-adjacent access to the host.
- **All state-changing requests are CSRF-protected** (Flask-WTF). Templates and the dashboard/firewall JavaScript automatically attach the required token — no action needed unless you're scripting against the API, in which case first `GET /login` (or any page) to obtain a token from the `csrf-token` meta tag or a form's hidden field, then send it back via the `X-CSRFToken` header or `csrf_token` form field.
- **Login attempts are rate-limited** per client IP (see `LOGIN_RATE_LIMIT_*` above) to slow down password guessing. The limiter is in-memory and resets on restart — fine for a single-process homelab deployment, not a substitute for a proper WAF/fail2ban if you expose this beyond your LAN.
- **Peer display names and other user-supplied strings are escaped client-side before being inserted into the page**, so a malicious or compromised account can't inject script via a peer rename, an uploaded filename, or an error message reflected back from a failed firewall-rule import.
- Set `SESSION_COOKIE_SECURE=true` once you're serving this behind HTTPS (e.g. a reverse proxy with a TLS certificate) so the session cookie is never sent in the clear.

---

## Running as a systemd Service (Auto-start on Boot)

A ready-to-use `wireguard-monitor.service` unit file is included.

### 1 — Get the code into a permanent location

Pick **one** of the following. Both end with the app living at
`/opt/wireguard-monitor`, owned by root, ready for the service to run.

**Option A — fresh clone (recommended for most people):**

```bash
sudo git clone https://github.com/masterlog80/wireguard-monitor.git /opt/wireguard-monitor
cd /opt/wireguard-monitor
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

This is the simplest and safest path — a brand-new clone can't possibly
carry over a `venv/`, `users.json`, or anything else left over from testing
the [Quick Start](#quick-start) earlier, which is the single most common
cause of "I set new credentials but they don't work" reports.

**Option B — copy from an existing checkout** (only if you've made local
edits to that checkout you specifically want to deploy):

```bash
# Run this from your EXISTING checkout directory (e.g. ~/wireguard-monitor)
# -- NOT from inside /opt/wireguard-monitor.
cd ~/wireguard-monitor   # adjust to wherever you cloned/edited it
pwd                      # sanity check: must NOT print /opt/wireguard-monitor

sudo rsync -a --exclude='venv/' --exclude='.git/' --exclude='__pycache__/' \
  --exclude='*.pyc' --exclude='users.json' --exclude='peer_names.json' \
  --exclude='firewall_saves/' ./ /opt/wireguard-monitor/
# No rsync? `sudo apt install rsync` (Debian/Ubuntu) or substitute a plain
# `sudo cp -r . /opt/wireguard-monitor` and manually delete the excluded
# paths afterward.

cd /opt/wireguard-monitor
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

> ⚠️ If your shell prompt already shows `/opt/wireguard-monitor` (e.g. from
> a previous attempt) before running the `rsync`/`cp` line, you're about to
> copy that directory into itself — `rsync` will fail with a `getcwd()`
> error and leave `/opt/wireguard-monitor` empty (so the next step's
> `pip install -r requirements.txt` then fails with *"No such file or
> directory"*). `cd` out to your source checkout first, or just use Option A
> instead. If you also see `(venv)` at the start of your prompt from an
> earlier attempt, run `deactivate` first to avoid confusion about which
> virtualenv is active.

### 2 — Create the data directory

```bash
sudo mkdir -p /var/lib/wireguard-monitor
```

This is where the service persists `users.json`, `peer_names.json`, and
firewall snapshots (see `Environment=` in the unit file) — kept separate from
`/opt/wireguard-monitor` so re-deploying the app code never touches your data.

### 3 — Set credentials

```bash
sudo tee /etc/wireguard-monitor.env > /dev/null <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF
sudo chmod 600 /etc/wireguard-monitor.env
```

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

### 4 — Install and enable the service

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
    │   └── users.html
    └── static/
        ├── favicon.svg
        ├── css/style.css
        ├── js/app.js          # shared helpers: CSRF-attaching fetch, HTML escaping
        ├── js/dashboard.js
        └── vendor/   # Bootstrap 5, Bootstrap Icons, Chart.js (vendored locally)
```

---

## License

MIT
