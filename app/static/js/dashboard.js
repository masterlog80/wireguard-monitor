/* dashboard.js – polls API endpoints every 5 seconds and updates the UI */

'use strict';

// Polyfill for CSS.escape in older browsers
if (!CSS || !CSS.escape) {
  CSS = CSS || {};
  CSS.escape = function(value) {
    return String(value).replace(/[^\w-]/g, function(c) {
      return '\\' + c;
    });
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return '–';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
  return (bytes / 1073741824).toFixed(2) + ' GB';
}

function formatBps(bps) {
  if (bps === null || bps === undefined) return '–';
  return formatBytes(bps) + '/s';
}

function shortKey(key) {
  if (!key || key.length <= 16) return key;
  return key.slice(0, 8) + '…' + key.slice(-8);
}

function timeAgo(epochSeconds) {
  if (!epochSeconds || epochSeconds === 0) return 'Never';
  const diff = Math.floor(Date.now() / 1000) - epochSeconds;
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

// ─────────────────────────────────────────────────────────────────────────────
// Peer Names
// ─────────────────────────────────────────────────────────────────────────────

let peerNames = {};  // public_key -> display name

function peerLabel(publicKey) {
  return peerNames[publicKey] || shortKey(publicKey);
}

async function refreshPeerNames() {
  try {
    const resp = await fetch('/api/peer_names');
    peerNames = await resp.json();
  } catch (e) {
    console.error('Peer names fetch failed', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// WireGuard Status
// ─────────────────────────────────────────────────────────────────────────────

async function refreshStatus() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    const body = document.getElementById('wg-status-body');
    const badge = document.getElementById('wg-refresh-badge');

    if (!data.available) {
      body.innerHTML = `<div class="alert alert-warning mb-0">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>${data.error || 'WireGuard unavailable'}
      </div>`;
      badge.className = 'badge bg-danger ms-auto';
      badge.textContent = 'Down';
      return;
    }

    badge.className = 'badge bg-success ms-auto';
    badge.textContent = 'Up';

    let html = '';
    for (const iface of data.interfaces) {
      if (iface.error) {
        html += `<div class="alert alert-warning">${iface.name}: ${iface.error}</div>`;
        continue;
      }
      html += `
        <div class="mb-3">
          <h6 class="text-success mb-2"><i class="bi bi-hdd-network me-2"></i>${iface.name || iface.interface || '–'}</h6>
          <div class="row row-cols-auto g-2">
            <div class="col"><span class="badge bg-secondary">Public Key</span> <code class="small">${shortKey(iface.public_key || '–')}</code></div>
            <div class="col"><span class="badge bg-secondary">Port</span> <code class="small">${iface.listening_port || '–'}</code></div>
          </div>
        </div>`;
    }
    body.innerHTML = html || '<p class="text-muted mb-0">No interfaces found.</p>';
  } catch (e) {
    console.error('Status fetch failed', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Peer Status Table
// ─────────────────────────────────────────────────────────────────────────────

async function refreshPeers() {
  try {
    const resp = await fetch('/api/peers');
    const peers = await resp.json();
    const tbody = document.getElementById('peers-tbody');

    if (!peers.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-3">No peers found.</td></tr>';
      return;
    }

    tbody.innerHTML = peers.map(p => {
      const dot = `<span class="status-dot ${p.connected ? 'connected' : 'disconnected'}"></span>`;
      const status = p.connected
        ? `${dot}<span class="text-success">Connected</span>`
        : `${dot}<span class="text-danger">Disconnected</span>`;
      const label = peerNames[p.public_key]
        ? `<span title="${p.public_key}" class="fw-semibold">${peerNames[p.public_key]}</span>
           <br><code class="text-muted small">${shortKey(p.public_key)}</code>`
        : `<code title="${p.public_key}">${shortKey(p.public_key)}</code>`;
      return `<tr>
        <td><code>${p.interface}</code></td>
        <td>
          ${label}
          <button class="btn btn-link btn-sm p-0 ms-1 text-muted rename-peer-btn"
                  data-pubkey="${p.public_key}"
                  title="Rename peer"><i class="bi bi-pencil"></i></button>
        </td>
        <td><small>${p.endpoint || '–'}</small></td>
        <td><small>${p.allowed_ips || '–'}</small></td>
        <td><small>${timeAgo(p.latest_handshake)}</small></td>
        <td>${status}</td>
        <td><small>${formatBytes(p.rx_bytes)}</small></td>
        <td><small>${formatBytes(p.tx_bytes)}</small></td>
      </tr>`;
    }).join('');
  } catch (e) {
    console.error('Peers fetch failed', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Charts
// ─────────────────────────────────────────────────────────────────────────────

const _throughputCharts = {};  // key -> Chart instance
const _pingCharts = {};        // key -> Chart instance

const CHART_DEFAULTS = {
  animation: false,
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { labels: { color: '#c9d1d9', boxWidth: 14 } }
  },
  scales: {
    x: {
      ticks: { color: '#8b949e', maxTicksLimit: 8, maxRotation: 0 },
      grid: { color: '#21262d' }
    },
    y: {
      ticks: { color: '#8b949e' },
      grid: { color: '#21262d' },
      beginAtZero: true
    }
  }
};

function getOrCreateCard(containerId, key, title) {
  const container = document.getElementById(containerId);
  // Remove placeholder if present
  const placeholder = container.querySelector('p.text-muted');
  if (placeholder) placeholder.remove();

  let card = container.querySelector(`[data-peer-key="${CSS.escape(key)}"]`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'col-md-6 col-lg-4 mb-3';
    card.setAttribute('data-peer-key', key);
    card.innerHTML = `
      <div class="card h-100">
        <div class="card-header py-2">
          <span class="peer-card-title text-info" title="${key}">${title}</span>
        </div>
        <div class="card-body">
          <div class="chart-wrapper"><canvas></canvas></div>
        </div>
      </div>`;
    // Wrap in a row if needed
    let row = container.querySelector('.row');
    if (!row) {
      row = document.createElement('div');
      row.className = 'row';
      container.appendChild(row);
    }
    row.appendChild(card);
  }
  return card.querySelector('canvas');
}

function updateChartCardTitle(containerId, key, title) {
  const cardEl = document.querySelector(`#${containerId} [data-peer-key="${CSS.escape(key)}"]`);
  if (cardEl) {
    const titleEl = cardEl.querySelector('.peer-card-title');
    if (titleEl) titleEl.textContent = title;
  }
}

async function refreshThroughput() {
  try {
    const resp = await fetch('/api/throughput');
    const data = await resp.json();

    for (const [key, hist] of Object.entries(data)) {
      const label = 'Throughput: ' + peerLabel(key);
      const canvas = getOrCreateCard('throughput-charts-container', key, label);
      updateChartCardTitle('throughput-charts-container', key, label);

      if (_throughputCharts[key]) {
        const chart = _throughputCharts[key];
        chart.data.labels = hist.labels;
        chart.data.datasets[0].data = hist.rx_bps;
        chart.data.datasets[1].data = hist.tx_bps;
        chart.update();
      } else {
        _throughputCharts[key] = new Chart(canvas, {
          type: 'line',
          data: {
            labels: hist.labels,
            datasets: [
              {
                label: 'RX',
                data: hist.rx_bps,
                borderColor: '#2ea043',
                backgroundColor: 'rgba(46,160,67,0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 2
              },
              {
                label: 'TX',
                data: hist.tx_bps,
                borderColor: '#388bfd',
                backgroundColor: 'rgba(56,139,253,0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 2
              }
            ]
          },
          options: {
            ...CHART_DEFAULTS,
            scales: {
              ...CHART_DEFAULTS.scales,
              y: {
                ...CHART_DEFAULTS.scales.y,
                ticks: {
                  color: '#8b949e',
                  callback: v => formatBps(v)
                }
              }
            }
          }
        });
      }
    }
  } catch (e) {
    console.error('Throughput fetch failed', e);
  }
}

async function refreshPing() {
  try {
    const resp = await fetch('/api/ping');
    const data = await resp.json();

    for (const [key, hist] of Object.entries(data)) {
      const label = 'Ping: ' + peerLabel(key);
      const canvas = getOrCreateCard('ping-charts-container', key, label);
      updateChartCardTitle('ping-charts-container', key, label);

      if (_pingCharts[key]) {
        const chart = _pingCharts[key];
        chart.data.labels = hist.labels;
        chart.data.datasets[0].data = hist.latencies;
        chart.update();
      } else {
        _pingCharts[key] = new Chart(canvas, {
          type: 'line',
          data: {
            labels: hist.labels,
            datasets: [
              {
                label: 'RTT (ms)',
                data: hist.latencies,
                borderColor: '#e3b341',
                backgroundColor: 'rgba(227,179,65,0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                spanGaps: true
              }
            ]
          },
          options: {
            ...CHART_DEFAULTS,
            scales: {
              ...CHART_DEFAULTS.scales,
              y: {
                ...CHART_DEFAULTS.scales.y,
                ticks: {
                  color: '#8b949e',
                  callback: v => v + ' ms'
                }
              }
            }
          }
        });
      }
    }
  } catch (e) {
    console.error('Ping fetch failed', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Rename Peer Modal
// ─────────────────────────────────────────────────────────────────────────────

let _renamePeerKey = null;

function openRenameModal(publicKey) {
  _renamePeerKey = publicKey;
  const input = document.getElementById('peer-name-input');
  const display = document.getElementById('rename-peer-key-display');
  input.value = peerNames[publicKey] || '';
  input.classList.remove('is-invalid');
  display.textContent = publicKey;
  const modal = new bootstrap.Modal(document.getElementById('renamePeerModal'));
  modal.show();
}

async function savePeerName() {
  if (!_renamePeerKey) return;
  const input = document.getElementById('peer-name-input');
  const name = input.value.trim();
  if (!name) {
    input.classList.add('is-invalid');
    return;
  }
  input.classList.remove('is-invalid');
  try {
    const resp = await fetchWithCsrf(`/api/peer_names/${encodeURIComponent(_renamePeerKey)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    const data = await resp.json();
    if (data.ok) {
      bootstrap.Modal.getInstance(document.getElementById('renamePeerModal')).hide();
      await refreshAll();
    } else {
      input.classList.add('is-invalid');
      alert(data.error || 'Failed to save name');
    }
  } catch (e) {
    console.error('Save peer name failed', e);
  }
}

async function removePeerName() {
  if (!_renamePeerKey) return;
  try {
    await fetchWithCsrf(`/api/peer_names/${encodeURIComponent(_renamePeerKey)}`, { method: 'DELETE' });
    bootstrap.Modal.getInstance(document.getElementById('renamePeerModal')).hide();
    await refreshAll();
  } catch (e) {
    console.error('Remove peer name failed', e);
  }
}

// Delegate rename button clicks in the peers table
document.getElementById('peers-tbody').addEventListener('click', function(e) {
  const btn = e.target.closest('.rename-peer-btn');
  if (btn) openRenameModal(btn.dataset.pubkey);
});

document.getElementById('save-peer-name-btn').addEventListener('click', savePeerName);
document.getElementById('remove-peer-name-btn').addEventListener('click', removePeerName);

// Allow Enter key to save in the name input
document.getElementById('peer-name-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') savePeerName();
});

// ─────────────────────────────────────────────────────────────────────────────
// Restart WireGuard
// ─────────────────────────────────────────────────────────────────────────────

async function restartWireguard() {
  const RESTART_REFRESH_DELAY_MS = 2000;
  const RESTART_RESET_DELAY_MS = 5000;

  const btn = document.getElementById('restart-btn');
  const originalHTML = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Restarting…';

  try {
    const resp = await fetchWithCsrf('/api/restart', { method: 'POST' });
    const data = await resp.json();
    if (data.ok) {
      btn.className = 'btn btn-sm btn-success ms-2';
      btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Restarted';
      setTimeout(() => refreshAll(), RESTART_REFRESH_DELAY_MS);
    } else {
      btn.className = 'btn btn-sm btn-danger ms-2';
      btn.title = data.error || 'Restart failed';
      btn.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Failed';
    }
  } catch (e) {
    console.error('Restart request failed', e);
    btn.className = 'btn btn-sm btn-danger ms-2';
    btn.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>Error';
  }

  setTimeout(() => {
    btn.disabled = false;
    btn.className = 'btn btn-sm btn-warning ms-2';
    btn.title = 'Restart WireGuard service';
    btn.innerHTML = originalHTML;
  }, RESTART_RESET_DELAY_MS);
}

// ─────────────────────────────────────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────────────────────────────────────

async function refreshAll() {
  await refreshPeerNames();
  await Promise.all([
    refreshStatus(),
    refreshPeers(),
    refreshThroughput(),
    refreshPing()
  ]);
}

refreshAll();
setInterval(refreshAll, 5000);

document.getElementById('restart-btn').addEventListener('click', restartWireguard);
