/* options.js -- Options page: per-peer Throughput "Peer view" toggle */

'use strict';

let optionsPeerPerspective = loadPeerPerspectiveMap();

function setPeerPerspective(key, enabled) {
  if (enabled) {
    optionsPeerPerspective[key] = true;
  } else {
    delete optionsPeerPerspective[key];
  }
  savePeerPerspectiveMap(optionsPeerPerspective);
}

async function loadPeerPerspectiveList() {
  const container = document.getElementById('peer-perspective-list');
  try {
    const [peersResp, namesResp] = await Promise.all([
      fetch('/api/peers'),
      fetch('/api/peer_names')
    ]);
    const peers = await peersResp.json();
    const names = await namesResp.json();

    if (!peers.length) {
      container.innerHTML = '<p class="text-muted mb-0">No peers found.</p>';
      return;
    }

    // One row per unique peer (a peer can appear more than once if it has
    // multiple interfaces/allowed IPs entries -- de-dupe by public key).
    const seen = new Set();
    const rows = [];
    for (const p of peers) {
      if (seen.has(p.public_key)) continue;
      seen.add(p.public_key);
      const key = p.public_key;
      const label = names[key] || shortKey(key);
      const checked = !!optionsPeerPerspective[key];
      rows.push(`
        <div class="d-flex align-items-center justify-content-between py-2 border-bottom border-secondary-subtle">
          <div>
            <div class="fw-semibold">${escapeHtml(label)}</div>
            <code class="text-muted small">${escapeHtml(shortKey(key))}</code>
          </div>
          <div class="form-check form-switch mb-0">
            <input class="form-check-input peer-perspective-switch" type="checkbox"
                   role="switch" data-peer-key="${escapeHtml(key)}" ${checked ? 'checked' : ''}
                   aria-label="Peer view for ${escapeHtml(label)}">
          </div>
        </div>`);
    }
    container.innerHTML = rows.join('');
  } catch (e) {
    container.innerHTML = '<p class="text-danger mb-0">Failed to load peers.</p>';
    console.error('Failed to load peer list', e);
  }
}

document.getElementById('peer-perspective-list').addEventListener('change', (e) => {
  const input = e.target.closest('.peer-perspective-switch');
  if (!input) return;
  setPeerPerspective(input.getAttribute('data-peer-key'), input.checked);
});

loadPeerPerspectiveList();
