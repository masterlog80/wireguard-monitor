# wireguard-monitor-copilot

A Flask-based web application running on Linux (port 5000) that provides a real-time monitoring UI for WireGuard VPN.

## Features

- **WireGuard status** – interface name, public key, listening port
- **Peer status table** – shows each peer's endpoint, allowed IPs, last handshake and connected/disconnected state
- **Throughput graphs** – per-peer RX/TX bytes-per-second chart, refreshed every 5 seconds
- **Ping latency graphs** – per-peer round-trip time chart, refreshed every 5 seconds
- **Firewall rules page** – displays both `iptables` and `nftables` rulesets
- **Firewall save / restore** – snapshot and reload active firewall rules server-side
- **Firewall export / import** – download the live `iptables` or `nftables` ruleset as a file; upload and immediately apply a previously exported file
- **WireGuard config export** – download all `*.conf` files from `/etc/wireguard/` (single file or a ZIP archive when multiple interfaces are present)
- **WireGuard config import** – upload a `.conf` file to `/etc/wireguard/` directly from the dashboard
- **User authentication** – login/logout with configurable credentials (via environment variables)
- **User management** – create, delete, and change passwords for multiple user accounts via the web UI

## Requirements

- Python 3.10+
- Linux with WireGuard tools (`wg`) installed (the UI gracefully degrades when `wg` is absent)

## Quick Start

```bash
# 1. Install Python dependencies

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# 2. (Optional) set credentials via environment variables
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=changeme   # change this!
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 3. Run the application
python run.py
```

Then open **http://\<your-server\>:5000** in a browser and log in.

## Configuration

| Environment variable | Default      | Description                                      |
|----------------------|--------------|--------------------------------------------------|
| `ADMIN_USERNAME`     | `admin`      | Login username                                   |
| `ADMIN_PASSWORD`     | `changeme`   | Login password – **change in production!**       |
| `SECRET_KEY`         | random       | Flask secret key for session signing             |
| `WG_INTERFACE`       | (auto)       | Force a specific WireGuard interface name        |
| `MAX_HISTORY`        | `60`         | Number of 5-second data points kept per peer     |

## Project Structure

```
├── run.py              # Entry point
├── config.py           # Configuration class
├── requirements.txt    # Python dependencies
├── tests.py            # Unit tests
└── app/
    ├── __init__.py     # Flask application factory
    ├── auth.py         # Login / logout blueprint
    ├── routes.py       # Dashboard + API blueprints (including export/import endpoints)
    ├── users.py        # User management blueprint
    ├── wireguard.py    # WireGuard data collection, history & config export/import
    ├── firewall.py     # iptables / nftables reader, save/restore & export/import
    ├── templates/
    │   ├── base.html
    │   ├── login.html
    │   ├── dashboard.html   # WireGuard config export/import card
    │   ├── firewall.html    # Firewall rules + save/restore + export/import
    │   └── users.html
    └── static/
        ├── css/style.css
        ├── js/dashboard.js
        └── vendor/        # Bootstrap 5, Bootstrap Icons, Chart.js (local)
```

## Running as a Service (Auto-start on Boot)

A ready-to-use **systemd** unit file (`wireguard-monitor.service`) is included.
Follow the steps below to install it so the monitor starts automatically every time the machine boots.

### 1 – Copy the application to a permanent location

```bash
sudo cp -r . /opt/wireguard-monitor
```

### 2 – Create the virtual environment on the server

```bash
cd /opt/wireguard-monitor
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### 3 – Create the data directory

The service stores `users.json` and `peer_names.json` under `/var/lib/wireguard-monitor` so they survive updates.

```bash
sudo mkdir -p /var/lib/wireguard-monitor
```

### 4 – Set credentials (strongly recommended)

Create the environment file that the service reads at startup:

```bash
sudo tee /etc/wireguard-monitor.env > /dev/null <<EOF
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF
sudo chmod 600 /etc/wireguard-monitor.env
```

> **Note:** The commands above generate random credentials automatically.  
> To use a custom password, replace the `$(python3 …)` part with your chosen value.

### 5 – Install and enable the systemd unit

```bash
sudo cp /opt/wireguard-monitor/wireguard-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wireguard-monitor
```

The `--now` flag starts the service immediately without requiring a reboot.

### 6 – Verify

```bash
sudo systemctl status wireguard-monitor
```

You should see `Active: active (running)`.  
Open **http://\<your-server\>:5000** in a browser to confirm the UI is available.

### Common management commands

| Task | Command |
|------|---------|
| Check status | `sudo systemctl status wireguard-monitor` |
| View live logs | `sudo journalctl -u wireguard-monitor -f` |
| Stop the service | `sudo systemctl stop wireguard-monitor` |
| Start the service | `sudo systemctl start wireguard-monitor` |
| Restart the service | `sudo systemctl restart wireguard-monitor` |
| Disable auto-start | `sudo systemctl disable wireguard-monitor` |

## Uninstall

Follow these steps to completely remove the wireguard-monitor from your system.

### 1 – Stop and disable the systemd service

```bash
sudo systemctl stop wireguard-monitor
sudo systemctl disable wireguard-monitor
```

### 2 – Remove the systemd unit file

```bash
sudo rm /etc/systemd/system/wireguard-monitor.service
sudo systemctl daemon-reload
```

### 3 – Remove the application files

```bash
sudo rm -rf /opt/wireguard-monitor
```

### 4 – Remove the data directory

> **Warning:** This deletes all user accounts and peer names stored by the application.

```bash
sudo rm -rf /var/lib/wireguard-monitor
```

### 5 – Remove the environment file

```bash
sudo rm -f /etc/wireguard-monitor.env
```

## Running Tests

```bash
pip install pytest
python -m pytest tests.py -v
```

## Screenshots

### Login Page
![Login Page](https://github.com/user-attachments/assets/395fbf9c-d054-4601-97cf-e885b5493417)

### Dashboard
![Dashboard](https://github.com/user-attachments/assets/5d78af9c-6891-4e8b-b583-9fb7cd21f7c7)

### WireGuard Config Export / Import
The dashboard includes a **WireGuard Config Export / Import** card directly below the WireGuard Status section.

- **Export Config** – downloads all `*.conf` files from `/etc/wireguard/` as a single file (one interface) or a ZIP archive (multiple interfaces).
- **Import Config** – uploads a `.conf` file from your browser and writes it to `/etc/wireguard/` with mode `0600`. Restart the interface afterwards to apply the new configuration.

![WireGuard Config Export / Import](https://github.com/user-attachments/assets/5d78af9c-6891-4e8b-b583-9fb7cd21f7c7)

### Firewall Rules
![Firewall Rules](https://github.com/user-attachments/assets/b7baa1c6-ae57-4a28-823c-0c4606a95a05)

### Firewall Export / Import
The **Save &amp; Restore Rules** panel on the Firewall page exposes two additional buttons per ruleset:

- **Export** – downloads the live ruleset (`iptables-save` / `nft list ruleset`) directly to your browser as `iptables.rules` or `nftables.rules`.
- **Import** – uploads a rules file from your browser and immediately applies it (`iptables-restore` / `nft -f`). nftables import performs an automatic rollback to the previous ruleset if the new rules fail to load.

![Firewall Export / Import](https://github.com/user-attachments/assets/b7baa1c6-ae57-4a28-823c-0c4606a95a05)

### User Management
![User Management](https://github.com/user-attachments/assets/16ebcefe-f74c-4bfa-8ad8-b1de67572ae8)

### Create User
![Create User](https://github.com/user-attachments/assets/c6206fae-789f-45bd-8417-7f788198837c)

