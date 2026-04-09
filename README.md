# wireguard-monitor-copilot

A Flask-based web application running on Linux (port 5000) that provides a real-time monitoring UI for WireGuard VPN.

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

## Screenshots

### Login Page
![Login Page](https://github.com/user-attachments/assets/116594ca-444b-4550-a636-6807083fd029)

### Dashboard
![Dashboard](https://github.com/user-attachments/assets/e815662b-3037-4409-a96b-b703f9515efa)

### Firewall Rules
![Firewall Rules](https://github.com/user-attachments/assets/4897b603-e59b-4729-9d83-c1be6b868dc7)

### User Management
![User Management](https://github.com/user-attachments/assets/78d32ff9-4b4f-45af-ba11-27cb31ad744c)

### Create User
![Create User](https://github.com/user-attachments/assets/f5e58c7d-dddf-48d5-be78-f41e6ecc18bf)

## Features

- **WireGuard status** – interface name, public key, listening port
- **Peer status table** – shows each peer's endpoint, allowed IPs, last handshake and connected/disconnected state
- **Throughput graphs** – per-peer RX/TX bytes-per-second chart, refreshed every 5 seconds
- **Ping latency graphs** – per-peer round-trip time chart, refreshed every 5 seconds
- **Firewall rules page** – displays both `iptables` and `nftables` rulesets
- **User authentication** – login/logout with configurable credentials (via environment variables)
- **User management** – create, delete, and change passwords for multiple user accounts via the web UI


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
    ├── routes.py       # Dashboard + API blueprints
    ├── users.py        # User management blueprint
    ├── wireguard.py    # WireGuard data collection & history
    ├── firewall.py     # iptables / nftables reader
    ├── templates/
    │   ├── base.html
    │   ├── login.html
    │   ├── dashboard.html
    │   ├── firewall.html
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
