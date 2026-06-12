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

---

## Quick Start

### Prerequisites

- Python 3.10+
- Linux with WireGuard tools (`wg`) installed — the UI gracefully degrades when `wg` is absent
- Root or `sudo` access (required to read WireGuard status and manage firewall rules)

### Clone & run (development)

```bash
git clone https://github.com/masterlog80/wireguard-monitor-copilot.git
cd wireguard-monitor-copilot

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=changeme   # change this!
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

python run.py
```

Open **http://\<your-server\>:5000** in a browser and log in.

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

---

## Running as a systemd Service (Auto-start on Boot)

A ready-to-use `wireguard-monitor.service` unit file is included.

### 1 — Copy to a permanent location

```bash
sudo cp -r . /opt/wireguard-monitor
cd /opt/wireguard-monitor
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### 2 — Create the data directory

```bash
sudo mkdir -p /var/lib/wireguard-monitor
```

### 3 — Set credentials

```bash
sudo tee /etc/wireguard-monitor.env > /dev/null <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF
sudo chmod 600 /etc/wireguard-monitor.env
```

### 4 — Install and enable the service

```bash
sudo cp /opt/wireguard-monitor/wireguard-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wireguard-monitor
sudo systemctl status wireguard-monitor
```

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
        ├── js/dashboard.js
        └── vendor/   # Bootstrap 5, Bootstrap Icons, Chart.js (vendored locally)
```

---

## License

MIT
