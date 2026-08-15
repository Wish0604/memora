const API_BASE = window.KB_API_BASE || '';

const NODE_COLORS = {
  Account: '#5eead4', Issue: '#fb7185', Task: '#fbbf6a', MeetingNote: '#a78bfa',
  FeatureRequest: '#60a5fa', Feature: '#60a5fa', DocPage: '#34d399', ReleaseNote: '#34d399', Person: '#94a3b8',
};

// ============================= Tab routing =============================
document.querySelectorAll('.rail-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.rail-tab').forEach(t => t.classList.remove('is-active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('is-active'));
    tab.classList.add('is-active');
    document.getElementById('view-' + tab.dataset.tab).classList.add('is-active');
    if (tab.dataset.tab === 'contradictions') loadContradictions();
    if (tab.dataset.tab === 'docs') loadDocsTab();
    if (tab.dataset.tab === 'analytics') loadAnalytics();
  });
});

// ============================= Chat =============================
const chatLog = document.getElementById('chat-log');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderAnswerHtml(text) {
  let html = escapeHtml(text);
  html = html.replace(/\n/g, '<br>');
  // customer record citations
  html = html.replace(/\[?(ISS|MTG|TASK|FR|acct)-(\d+)\]?/g, (m, prefix, num) =>
    `<span class="cite">${prefix}-${num}</span>`);
  // doc / release URL citations
  html = html.replace(/\[?(https?:\/\/(?:docs|releases)\.flytbase\.com\/[^\s\]<]+)\]?/g, (m, url) =>
    `<span class="cite cite-doc" title="${url}">${url.replace('https://', '')}</span>`);
  return html;
}

function addMessage(role, html, meta) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-system');
  wrap.innerHTML = `
    <div class="msg-avatar">${role === 'user' ? '›' : '◆'}</div>
    <div class="msg-body">
      <p>${html}</p>
      ${meta ? `<div class="msg-meta">${meta}</div>` : ''}
    </div>`;
  chatLog.appendChild(wrap);
  chatLog.scrollTop = chatLog.scrollHeight;
  return wrap;
}

let lastGraphNodeIds = [];

async function submitQuery(query) {
  addMessage('user', escapeHtml(query));
  const thinking = addMessage('system', 'Thinking…');

  try {
    const res = await fetch(`${API_BASE}/api/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    thinking.remove();

    let bodyHtml = renderAnswerHtml(data.answer || 'No answer returned.');
    let contradictionsHtml = '';
    if (data.contradictions && data.contradictions.length) {
      contradictionsHtml = data.contradictions.map(c => `
        <div class="contradiction-callout">
          ⚠ <b>${escapeHtml(c.feature)}</b> is still requested
          (${c.open_feature_requests.map(r => r.id).join(', ')})
          but already shipped in ${c.shipped_in.map(s => s.id.replace('https://', '')).join(', ')}
        </div>`).join('');
    }

    const meta = `${data.intent} · ${data.latency_ms}ms · ${data.citations.length} citations`;
    const el = addMessage('system', bodyHtml + contradictionsHtml, meta);

    lastGraphNodeIds = data.graph_node_ids || [];
    if (lastGraphNodeIds.length) renderGraphExplorer(lastGraphNodeIds);
  } catch (err) {
    thinking.remove();
    addMessage('system', `Something went wrong reaching the agent: ${escapeHtml(String(err))}`);
  }
}

chatForm.addEventListener('submit', e => {
  e.preventDefault();
  const q = chatInput.value.trim();
  if (!q) return;
  chatInput.value = '';
  submitQuery(q);
});

document.querySelectorAll('[data-demo]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelector('[data-tab="chat"]').click();
    submitQuery(btn.dataset.demo);
  });
});

// ============================= Graph explorer (D3) =============================
async function renderGraphExplorer(nodeIds) {
  document.getElementById('graph-empty').style.display = 'none';
  const capped = nodeIds.slice(0, 60);
  const res = await fetch(`${API_BASE}/api/graph/subgraph`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_ids: capped }),
  });
  const { nodes, edges } = await res.json();
  drawGraph(nodes, edges);
  renderLegend(nodes);
}

function renderLegend(nodes) {
  const types = [...new Set(nodes.map(n => n.type))];
  const legend = document.getElementById('graph-legend');
  legend.innerHTML = types.map(t => `
    <div class="legend-item"><span class="legend-dot" style="background:${NODE_COLORS[t] || '#888'}"></span>${t}</div>
  `).join('');
}

function drawGraph(nodes, edges) {
  const svgEl = document.getElementById('graph-svg');
  const width = svgEl.clientWidth || 800;
  const height = svgEl.clientHeight || 480;
  const svg = d3.select('#graph-svg');
  svg.selectAll('*').remove();

  const simNodes = nodes.map(n => ({ ...n }));
  const simLinks = edges.map(e => ({ ...e }));

  const sim = d3.forceSimulation(simNodes)
    .force('link', d3.forceLink(simLinks).id(d => d.id).distance(70).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-140))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(20));

  const link = svg.append('g').selectAll('line')
    .data(simLinks).join('line')
    .attr('stroke', 'rgba(148,163,196,0.25)')
    .attr('stroke-width', 1);

  const node = svg.append('g').selectAll('circle')
    .data(simNodes).join('circle')
    .attr('r', d => d.type === 'Account' ? 9 : 6)
    .attr('fill', d => NODE_COLORS[d.type] || '#888')
    .attr('stroke', '#0b0f1a')
    .attr('stroke-width', 1.5)
    .style('filter', d => `drop-shadow(0 0 4px ${NODE_COLORS[d.type] || '#888'})`)
    .call(d3.drag()
      .on('start', (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on('end', (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  node.append('title').text(d => `${d.type}: ${d.label}`);

  const label = svg.append('g').selectAll('text')
    .data(simNodes).join('text')
    .text(d => d.label.length > 22 ? d.label.slice(0, 22) + '…' : d.label)
    .attr('font-size', 9)
    .attr('fill', '#9aa3bf')
    .attr('font-family', 'JetBrains Mono, monospace')
    .attr('dx', 10)
    .attr('dy', 3);

  sim.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
    label.attr('x', d => d.x).attr('y', d => d.y);
  });
}

// ============================= Contradictions =============================
async function loadContradictions() {
  const board = document.getElementById('contradiction-board');
  board.innerHTML = '<div class="panel">Loading…</div>';
  const res = await fetch(`${API_BASE}/api/contradictions`);
  const { contradictions } = await res.json();
  if (!contradictions.length) {
    board.innerHTML = '<div class="panel">No structural contradictions detected right now.</div>';
    return;
  }
  board.innerHTML = contradictions.map(c => `
    <div class="contradiction-card">
      <h4>${escapeHtml(c.feature)}</h4>
      <div class="contradiction-row">
        <div>
          <div class="contradiction-col-label">Still open as feature requests</div>
          ${c.open_feature_requests.map(r => `<span class="cite">${r.id}</span> ${escapeHtml(r.title)} <span style="color:var(--text-faint)">(${r.status})</span><br>`).join('')}
        </div>
        <div>
          <div class="contradiction-col-label">Already shipped per</div>
          ${c.shipped_in.map(s => `<span class="cite cite-doc">${s.id.replace('https://', '')}</span> ${escapeHtml(s.title)}<br>`).join('')}
        </div>
      </div>
    </div>
  `).join('');
}

// ============================= Docs sync =============================
async function loadDocsTab() {
  const tbody = document.querySelector('#docs-table tbody');
  tbody.innerHTML = `<tr><td colspan="4">Run "Trigger sync" to fetch live pages.</td></tr>`;
}

document.getElementById('sync-btn').addEventListener('click', async () => {
  const btn = document.getElementById('sync-btn');
  btn.textContent = 'Syncing…';
  try {
    const res = await fetch(`${API_BASE}/api/docs/sync`, { method: 'POST' });
    const data = await res.json();
    const tbody = document.querySelector('#docs-table tbody');
    if (!data.urls || !data.urls.length) {
      tbody.innerHTML = `<tr><td colspan="4">No pages synced.</td></tr>`;
    } else {
      tbody.innerHTML = data.urls.map(u => `
        <tr>
          <td>${u.includes('releases.') ? 'releases' : 'docs'}</td>
          <td>${u}</td>
          <td>just now</td>
          <td>—</td>
        </tr>`).join('');
    }
  } catch (e) {
    document.querySelector('#docs-table tbody').innerHTML = `<tr><td colspan="4">Sync failed: ${escapeHtml(String(e))}</td></tr>`;
  }
  btn.textContent = 'Trigger sync';
});

// ============================= Analytics =============================
async function loadAnalytics() {
  const res = await fetch(`${API_BASE}/api/analytics`);
  const data = await res.json();

  document.getElementById('stat-grid').innerHTML = `
    <div class="stat-card"><div class="num">${data.graph_stats.node_count}</div><div class="label">Graph nodes</div></div>
    <div class="stat-card"><div class="num">${data.graph_stats.edge_count}</div><div class="label">Graph edges</div></div>
    <div class="stat-card"><div class="num">${data.usage.total_queries}</div><div class="label">Queries answered</div></div>
    <div class="stat-card"><div class="num">${data.usage.avg_latency_ms}ms</div><div class="label">Avg latency</div></div>
  `;

  const maxMentions = Math.max(...data.most_requested_features.map(f => f.mentions || 0), 1);
  document.getElementById('top-features').innerHTML = data.most_requested_features.map(f => `
    <div class="feature-row">
      <span>${escapeHtml(f.title)}</span>
      <div class="bar-bg"><div class="bar-fill" style="width:${(f.mentions / maxMentions) * 100}%"></div></div>
      <span style="color:var(--text-faint)">${f.mentions}</span>
    </div>
  `).join('');

  const tierColors = { enterprise: '#5eead4', starter: '#fbbf6a', zero: '#fb7185' };
  document.getElementById('tier-chart').innerHTML = Object.entries(data.issue_counts_by_tier).map(([tier, count]) => `
    <div class="tier-row">
      <span class="legend-dot" style="background:${tierColors[tier] || '#888'}"></span>
      <span style="width:80px; display:inline-block;">${tier}</span>
      <span style="color:var(--text-faint)">${count} issues</span>
    </div>
  `).join('');

  document.getElementById('recent-queries').innerHTML = data.usage.recent_queries.length
    ? data.usage.recent_queries.map(q => `
        <div class="recent-q">
          <span>${escapeHtml(q.query)}</span>
          <span class="intent-tag">${q.intent}</span>
        </div>`).join('')
    : '<div style="color:var(--text-faint); font-size:12.5px;">No queries logged yet — ask something in the Ask tab.</div>';
}

// ============================= Init =============================
(async function init() {
  try {
    const res = await fetch(`${API_BASE}/api/graph/stats`);
    const stats = await res.json();
    document.getElementById('rail-node-count').innerHTML =
      `<span class="dot dot-live"></span> ${stats.node_count} nodes indexed`;
  } catch (e) { /* backend not reachable yet — non-fatal */ }
})();
