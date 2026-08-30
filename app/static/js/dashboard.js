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
let peerConnected = {};  // public_key -> bool, populated by refreshPeers()

// public_key -> true when the Throughput chart should show RX/TX from this
// peer's own point of view instead of the server's (WireGuard's native
// convention: RX = server received from peer, TX = server sent to peer).
// Persisted per-browser, keyed by peer so each peer's preference is
// independent.
let rxTxPeerPerspective = {};
try {
  rxTxPeerPerspective = JSON.parse(localStorage.getItem('rxTxPeerPerspective') || '{}');
} catch (e) {
  rxTxPeerPerspective = {};
}

function isPeerPerspective(key) {
  return !!rxTxPeerPerspective[key];
}

function togglePeerPerspective(key) {
  if (rxTxPeerPerspective[key]) {
    delete rxTxPeerPerspective[key];
  } else {
    rxTxPeerPerspective[key] = true;
  }
  localStorage.setItem('rxTxPeerPerspective', JSON.stringify(rxTxPeerPerspective));

  // Apply immediately to an already-rendered chart rather than waiting for
  // the next 5s refresh.
  const chart = _throughputCharts[key];
  if (chart && chart.__lastHist) {
    applyThroughputDatasets(chart, key, chart.__lastHist);
    chart.update();
  }
  const cardEl = document.querySelector(`#throughput-charts-container [data-peer-key="${CSS.escape(key)}"]`);
  if (cardEl) updateChartCardPerspectiveBadge(cardEl, key);
}

// Assign the RX/TX datasets on a throughput chart according to the
// peer's current perspective setting. The dataset LABELED "RX" always
// stays green and the one labeled "TX" always stays blue -- only which
// underlying series (hist.rx_bps vs hist.tx_bps) backs each label changes.
function applyThroughputDatasets(chart, key, hist) {
  chart.__lastHist = hist;
  chart.data.labels = hist.labels;
  if (isPeerPerspective(key)) {
    // This peer's RX = what it received = what the server sent (tx_bps).
    chart.data.datasets[0].data = hist.tx_bps;
    chart.data.datasets[1].data = hist.rx_bps;
  } else {
    chart.data.datasets[0].data = hist.rx_bps;
    chart.data.datasets[1].data = hist.tx_bps;
  }
}

function updateChartCardPerspectiveBadge(cardEl, key) {
  const badge = cardEl.querySelector('.peer-perspective-badge');
  if (!badge) return;
  badge.classList.toggle('d-none', !isPeerPerspective(key));
  const btn = cardEl.querySelector('.perspective-toggle-btn');
  if (btn) {
    btn.classList.toggle('text-info', isPeerPerspective(key));
    btn.title = isPeerPerspective(key)
      ? "Showing this peer's own perspective -- click to switch back to the server's perspective"
      : "Showing the server's perspective (default) -- click to view from this peer's perspective";
  }
}

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
        <i class="bi bi-exclamation-triangle-fill me-2"></i>${escapeHtml(data.error) || 'WireGuard unavailable'}
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
        html += `<div class="alert alert-warning">${escapeHtml(iface.name)}: ${escapeHtml(iface.error)}</div>`;
        continue;
      }
      html += `
        <div class="mb-3">
          <h6 class="text-success mb-2"><i class="bi bi-hdd-network me-2"></i>${escapeHtml(iface.name || iface.interface) || '–'}</h6>
          <div class="row row-cols-auto g-2">
            <div class="col"><span class="badge bg-secondary">Public Key</span> <code class="small">${escapeHtml(shortKey(iface.public_key)) || '–'}</code></div>
            <div class="col"><span class="badge bg-secondary">Port</span> <code class="small">${escapeHtml(iface.listening_port) || '–'}</code></div>
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

    peerConnected = Object.fromEntries(peers.map(p => [p.public_key, p.connected]));

    tbody.innerHTML = peers.map(p => {
      const dot = `<span class="status-dot ${p.connected ? 'connected' : 'disconnected'}"></span>`;
      const status = p.connected
        ? `${dot}<span class="text-success">Connected</span>`
        : `${dot}<span class="text-danger">Disconnected</span>`;
      const label = peerNames[p.public_key]
        ? `<span title="${escapeHtml(p.public_key)}" class="fw-semibold">${escapeHtml(peerNames[p.public_key])}</span>
           <br><code class="text-muted small">${escapeHtml(shortKey(p.public_key))}</code>`
        : `<code title="${escapeHtml(p.public_key)}">${escapeHtml(shortKey(p.public_key))}</code>`;
      return `<tr>
        <td><code>${escapeHtml(p.interface)}</code></td>
        <td>
          ${label}
          <button class="btn btn-link btn-sm p-0 ms-1 text-muted rename-peer-btn"
                  data-pubkey="${escapeHtml(p.public_key)}"
                  title="Rename peer"><i class="bi bi-pencil"></i></button>
        </td>
        <td><small>${escapeHtml(p.endpoint) || '–'}</small></td>
        <td><small>${escapeHtml(p.allowed_ips) || '–'}</small></td>
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
const CHART_HEIGHT_BY_COLUMNS = { 2: 300, 3: 220, 4: 170 };
const CHART_GRID_CONTAINER_IDS = ['throughput-charts-container', 'ping-charts-container'];

let chartColumns = parseInt(localStorage.getItem('chartColumns'), 10);
if (![2, 3, 4].includes(chartColumns)) chartColumns = 3;

function rowClassForColumns(n) {
  // Always 1 column on phones, 2 on small tablets, and the user's chosen
  // count from the medium breakpoint up -- so picking "4" on a desktop
  // never forces unusably narrow cards on a phone.
  return `row row-cols-1 row-cols-sm-2 row-cols-md-${n} g-3`;
}

function applyColumnCount(n) {
  chartColumns = n;
  localStorage.setItem('chartColumns', String(n));
  const heightPx = CHART_HEIGHT_BY_COLUMNS[n] || 220;

  for (const containerId of CHART_GRID_CONTAINER_IDS) {
    const container = document.getElementById(containerId);
    if (!container) continue;
    container.style.setProperty('--chart-h', heightPx + 'px');
    const row = container.querySelector('.row');
    if (row) row.className = rowClassForColumns(n);
  }

  // Chart.js is responsive and redraws on its own via ResizeObserver, but
  // resize() makes the size change apply immediately rather than waiting
  // for the next tick.
  for (const chart of [...Object.values(_throughputCharts), ...Object.values(_pingCharts)]) {
    chart.resize();
  }
}

function chartThemeColors() {
  const isLight = document.documentElement.getAttribute('data-bs-theme') === 'light';
  return isLight
    ? { text: '#495057', grid: '#dee2e6' }
    : { text: '#8b949e', grid: '#21262d' };
}

function getChartDefaults() {
  const { text, grid } = chartThemeColors();
  return {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: text, boxWidth: 14 } }
    },
    scales: {
      x: {
        ticks: { color: text, maxTicksLimit: 8, maxRotation: 0 },
        grid: { color: grid }
      },
      y: {
        ticks: { color: text },
        grid: { color: grid },
        beginAtZero: true
      }
    }
  };
}

// Re-theme any already-rendered charts when the light/dark toggle fires
// (see base.html), instead of waiting for the next data refresh.
document.addEventListener('themechange', () => {
  const { text, grid } = chartThemeColors();
  for (const chart of [...Object.values(_throughputCharts), ...Object.values(_pingCharts)]) {
    chart.options.plugins.legend.labels.color = text;
    chart.options.scales.x.ticks.color = text;
    chart.options.scales.x.grid.color = grid;
    chart.options.scales.y.ticks.color = text;
    chart.options.scales.y.grid.color = grid;
    chart.update();
  }
});

function getOrCreateCard(containerId, key, title, options) {
  options = options || {};
  const container = document.getElementById(containerId);
  // Remove placeholder if present
  const placeholder = container.querySelector('p.text-muted');
  if (placeholder) placeholder.remove();

  let card = container.querySelector(`[data-peer-key="${CSS.escape(key)}"]`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'col mb-3';
    card.setAttribute('data-peer-key', key);
    const perspectiveControls = options.showPerspectiveToggle ? `
          <span class="badge bg-info-subtle text-info-emphasis peer-perspective-badge d-none">Peer view</span>
          <button type="button" class="btn btn-sm btn-link p-0 ms-auto text-muted perspective-toggle-btn"
                  data-peer-key="${escapeHtml(key)}"
                  title="Showing the server's perspective (default) -- click to view from this peer's perspective">
            <i class="bi bi-arrow-left-right"></i>
          </button>` : '';
    card.innerHTML = `
      <div class="card h-100">
        <div class="card-header py-2 d-flex align-items-center gap-2">
          <span class="peer-card-title text-info" title="${escapeHtml(key)}">${escapeHtml(title)}</span>
          <span class="badge bg-secondary peer-offline-badge d-none" title="No recent WireGuard handshake -- not actively probed">Offline</span>
          ${perspectiveControls}
        </div>
        <div class="card-body">
          <div class="chart-wrapper"><canvas></canvas></div>
        </div>
      </div>`;
    // Wrap in a row if needed
    let row = container.querySelector('.row');
    if (!row) {
      row = document.createElement('div');
      row.className = rowClassForColumns(chartColumns);
      container.style.setProperty('--chart-h', (CHART_HEIGHT_BY_COLUMNS[chartColumns] || 220) + 'px');
      container.appendChild(row);
    }
    row.appendChild(card);
  }
  updateChartCardOfflineBadge(card, key);
  if (options.showPerspectiveToggle) updateChartCardPerspectiveBadge(card, key);
  return card.querySelector('canvas');
}

function updateChartCardOfflineBadge(cardEl, key) {
  const badge = cardEl.querySelector('.peer-offline-badge');
  if (!badge) return;
  badge.classList.toggle('d-none', peerConnected[key] !== false);
}

function updateChartCardTitle(containerId, key, title) {
  const cardEl = document.querySelector(`#${containerId} [data-peer-key="${CSS.escape(key)}"]`);
  if (cardEl) {
    const titleEl = cardEl.querySelector('.peer-card-title');
    if (titleEl) titleEl.textContent = title;
    updateChartCardOfflineBadge(cardEl, key);
    updateChartCardPerspectiveBadge(cardEl, key);  // no-op if this card has no toggle
  }
}

async function refreshThroughput() {
  try {
    const resp = await fetch('/api/throughput');
    const data = await resp.json();

    for (const [key, hist] of Object.entries(data)) {
      const label = 'Throughput: ' + peerLabel(key);
      const canvas = getOrCreateCard('throughput-charts-container', key, label, { showPerspectiveToggle: true });
      updateChartCardTitle('throughput-charts-container', key, label);

      if (_throughputCharts[key]) {
        const chart = _throughputCharts[key];
        applyThroughputDatasets(chart, key, hist);
        chart.update();
      } else {
        _throughputCharts[key] = new Chart(canvas, {
          type: 'line',
          data: {
            labels: hist.labels,
            datasets: [
              {
                label: 'RX',
                data: isPeerPerspective(key) ? hist.tx_bps : hist.rx_bps,
                borderColor: '#2ea043',
                backgroundColor: 'rgba(46,160,67,0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 2
              },
              {
                label: 'TX',
                data: isPeerPerspective(key) ? hist.rx_bps : hist.tx_bps,
                borderColor: '#388bfd',
                backgroundColor: 'rgba(56,139,253,0.15)',
                fill: true,
                tension: 0.3,
                pointRadius: 2
              }
            ]
          },
          options: {
            ...getChartDefaults(),
            scales: {
              ...getChartDefaults().scales,
              y: {
                ...getChartDefaults().scales.y,
                ticks: {
                  color: chartThemeColors().text,
                  callback: v => formatBps(v)
                }
              }
            }
          }
        });
        _throughputCharts[key].__lastHist = hist;
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
            ...getChartDefaults(),
            scales: {
              ...getChartDefaults().scales,
              y: {
                ...getChartDefaults().scales.y,
                ticks: {
                  color: chartThemeColors().text,
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

document.getElementById('throughput-charts-container').addEventListener('click', (e) => {
  const btn = e.target.closest('.perspective-toggle-btn');
  if (btn) togglePeerPerspective(btn.getAttribute('data-peer-key'));
});

const columnsSelect = document.getElementById('chart-columns-select');
columnsSelect.value = String(chartColumns);
columnsSelect.addEventListener('change', (e) => {
  applyColumnCount(parseInt(e.target.value, 10));
});
