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
    if (tab.dataset.tab === 'graph') loadFullGraph();
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
    
    // Phase 13 Retrieval Indicators
    const hasCustomer = ['customer', 'both', 'contradiction', 'analytical'].includes(data.intent);
    const hasDocs = ['docs', 'both', 'contradiction'].includes(data.intent);
    
    const badgesHtml = `
      <div class="retrieval-badges" style="margin-bottom:8px; display:flex; gap:6px; flex-wrap:wrap;">
        ${hasCustomer ? '<span class="badge-tag" style="background:#1e293b; color:#5eead4; border:1px solid #5eead455; padding:2px 8px; border-radius:12px; font-size:0.75rem;">✓ Customer Graph</span>' : ''}
        ${hasDocs ? '<span class="badge-tag" style="background:#1e293b; color:#34d399; border:1px solid #34d39955; padding:2px 8px; border-radius:12px; font-size:0.75rem;">✓ Product Graph</span>' : ''}
        <span class="badge-tag" style="background:#1e293b; color:#60a5fa; border:1px solid #60a5fa55; padding:2px 8px; border-radius:12px; font-size:0.75rem;">✓ Vector Search</span>
      </div>`;

    let evidenceHtml = '';
    if (data.evidence_set && data.evidence_set.primary_evidence && data.evidence_set.primary_evidence.length) {
      evidenceHtml = `
        <details style="margin-top:10px; border:1px solid #334155; border-radius:6px; padding:8px; background:#0f172a;">
          <summary style="cursor:pointer; color:#94a3b8; font-size:0.85rem; font-weight:600;">
            🔍 Evidence Set (${data.evidence_set.primary_evidence.length} Primary Items)
          </summary>
          <div style="margin-top:8px; display:flex; flex-direction:column; gap:6px;">
            ${data.evidence_set.primary_evidence.slice(0, 5).map(ev => `
              <div style="font-size:0.8rem; background:#1e293b; padding:6px 10px; border-radius:4px; border-left:3px solid ${ev.source_type === 'documentation' ? '#34d399' : '#60a5fa'};">
                <span style="color:#f8fafc; font-weight:600;">[${escapeHtml(ev.source_id)}]</span>
                <span style="color:#64748b; font-size:0.75rem;"> (${escapeHtml(ev.source_file_or_url)})</span>
                <div style="color:#cbd5e1; margin-top:2px;">${escapeHtml(ev.snippet)}</div>
              </div>`).join('')}
          </div>
        </details>`;
    }

    let contradictionsHtml = '';
    if (data.contradictions && data.contradictions.length) {
      contradictionsHtml = data.contradictions.map(c => `
        <div class="contradiction-callout" style="margin-top:8px; padding:8px; background:#450a0a; border-left:3px solid #f87171; border-radius:4px; font-size:0.85rem; color:#fca5a5;">
          ⚠ <b>${escapeHtml(c.feature_title || c.feature_key || '')}</b> is marked '<em>${escapeHtml(c.request_status || '')}</em>' (${escapeHtml(c.feature_request_id || '')}) but already shipped in <b>${escapeHtml(c.release_title || '')}</b> (${escapeHtml(c.release_url || '')})
        </div>`).join('');
    }

    let mutationHtml = '';
    if (data.mutation_info && data.mutation_info.status === 'committed') {
      mutationHtml = `
        <div class="mutation-callout" style="margin-top:8px; padding:8px 12px; background:#064e3b; border-left:3px solid #34d399; border-radius:4px; font-size:0.85rem; color:#a7f3d0;">
          <b>✓ Knowledge Persisted to Graph:</b> ${escapeHtml(data.mutation_info.message)}
        </div>`;
    }

    const meta = `Intent: ${data.intent} · ${data.latency_ms}ms · ${data.citations.length} citations`;
    addMessage('system', badgesHtml + bodyHtml + mutationHtml + contradictionsHtml + evidenceHtml, meta);

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

// ============================= Full KG Interactive Graph Module (Cytoscape.js) =============================
let cy = null;
let fullGraphData = { nodes: [], edges: [] };
let activeNodeTypes = new Set();
let activeRelTypes = new Set();
let currentLayoutName = 'cose';
let currentGraphLimit = 400;

const NODE_SHAPES = {
  Account: 'ellipse',
  Person: 'ellipse',
  Issue: 'diamond',
  Feature: 'hexagon',
  FeatureRequest: 'round-rectangle',
  Task: 'rectangle',
  MeetingNote: 'barrel',
  Plan: 'tag',
  DocPage: 'round-tag',
  ReleaseNote: 'pentagon',
  Version: 'star',
};

async function loadFullGraph(limit = currentGraphLimit) {
  currentGraphLimit = limit;
  const statBadge = document.getElementById('kg-stat-badge');
  const emptyEl = document.getElementById('graph-empty');
  if (emptyEl) emptyEl.style.display = 'block';

  try {
    const res = await fetch(`${API_BASE}/api/graph?limit=${limit}`);
    fullGraphData = await res.json();
    if (emptyEl) emptyEl.style.display = 'none';

    if (statBadge) {
      const totalStr = fullGraphData.total_nodes_in_store ? ` (of ${fullGraphData.total_nodes_in_store} total)` : '';
      statBadge.textContent = `${fullGraphData.nodes.length} Nodes · ${fullGraphData.edges.length} Edges${totalStr}`;
    }

    // Extract unique node & rel types
    const nodeTypes = [...new Set(fullGraphData.nodes.map(n => n.type))].sort();
    const relTypes = [...new Set(fullGraphData.edges.map(e => e.type))].sort();

    activeNodeTypes = new Set(nodeTypes);
    activeRelTypes = new Set(relTypes);

    populateFilterCheckboxes(nodeTypes, relTypes);
    initCytoscape();
  } catch (err) {
    if (emptyEl) emptyEl.textContent = `Failed to load Knowledge Graph: ${err}`;
  }
}

function populateFilterCheckboxes(nodeTypes, relTypes) {
  const nodeContainer = document.getElementById('kg-node-filters');
  const relContainer = document.getElementById('kg-rel-filters');

  if (nodeContainer) {
    const counts = {};
    fullGraphData.nodes.forEach(n => counts[n.type] = (counts[n.type] || 0) + 1);
    nodeContainer.innerHTML = nodeTypes.map(t => `
      <label class="kg-cb-item">
        <span><input type="checkbox" class="kg-node-cb" value="${t}" checked> ${t}</span>
        <span class="kg-count-badge">${counts[t] || 0}</span>
      </label>`).join('');

    nodeContainer.querySelectorAll('.kg-node-cb').forEach(cb => {
      cb.addEventListener('change', e => {
        if (e.target.checked) activeNodeTypes.add(e.target.value);
        else activeNodeTypes.delete(e.target.value);
        applyGraphFilters();
      });
    });
  }

  if (relContainer) {
    const relCounts = {};
    fullGraphData.edges.forEach(e => relCounts[e.type] = (relCounts[e.type] || 0) + 1);
    relContainer.innerHTML = relTypes.map(t => `
      <label class="kg-cb-item">
        <span><input type="checkbox" class="kg-rel-cb" value="${t}" checked> ${t}</span>
        <span class="kg-count-badge">${relCounts[t] || 0}</span>
      </label>`).join('');

    relContainer.querySelectorAll('.kg-rel-cb').forEach(cb => {
      cb.addEventListener('change', e => {
        if (e.target.checked) activeRelTypes.add(e.target.value);
        else activeRelTypes.delete(e.target.value);
        applyGraphFilters();
      });
    });
  }
}

function initCytoscape() {
  const cyContainer = document.getElementById('cy');
  if (!cyContainer) return;

  const elements = [];
  fullGraphData.nodes.forEach(n => {
    elements.push({
      data: {
        id: n.id,
        label: n.label,
        type: n.type,
        subgraph: n.subgraph,
        properties: n.properties,
      }
    });
  });

  fullGraphData.edges.forEach(e => {
    elements.push({
      data: {
        id: e.id || `${e.source}_${e.target}`,
        source: e.source,
        target: e.target,
        type: e.type,
        properties: e.properties || {},
      }
    });
  });

  if (typeof cytoscape === 'undefined') {
    console.warn("Cytoscape.js not loaded, falling back to D3 force layout");
    drawD3Fallback(fullGraphData.nodes.slice(0, 100), fullGraphData.edges.slice(0, 200));
    return;
  }

  if (cy) cy.destroy();

  const layoutOpts = {
    cose: { name: 'cose', animate: false, fit: true, padding: 30, randomize: false, numIter: 300, idealEdgeLength: 35 },
    dagre: { name: 'dagre', rankDir: 'TB', animate: false, padding: 30 },
    circle: { name: 'circle', animate: false, padding: 30 },
    concentric: { name: 'concentric', animate: false, padding: 30 },
  };

  const selectedLayout = layoutOpts[currentLayoutName] || layoutOpts['cose'];

  cy = cytoscape({
    container: cyContainer,
    elements: elements,
    textureOnViewport: true,
    pixelRatio: 'auto',
    hideEdgesOnViewport: elements.length > 800,
    style: [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'font-size': '10px',
          'color': '#cbd5e1',
          'font-family': 'Inter, sans-serif',
          'text-valign': 'bottom',
          'text-margin-y': 4,
          'width': 22,
          'height': 22,
          'background-color': ele => NODE_COLORS[ele.data('type')] || '#94a3b8',
          'shape': ele => NODE_SHAPES[ele.data('type')] || 'ellipse',
          'border-width': 1.5,
          'border-color': '#0f172a',
        }
      },
      {
        selector: 'node[type = "Account"]',
        style: { 'width': 30, 'height': 30, 'font-weight': 'bold', 'font-size': '11px', 'color': '#5eead4' }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.2,
          'line-color': 'rgba(148, 163, 184, 0.25)',
          'target-arrow-color': 'rgba(148, 163, 184, 0.4)',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'font-size': '8px',
          'color': '#64748b',
        }
      },
      {
        selector: ':selected',
        style: {
          'border-width': 3,
          'border-color': '#38bdf8',
          'line-color': '#38bdf8',
          'target-arrow-color': '#38bdf8',
        }
      },
      {
        selector: '.highlighted',
        style: {
          'border-width': 3,
          'border-color': '#f59e0b',
          'background-color': '#f59e0b',
        }
      }
    ],
    layout: selectedLayout
  });

  cy.on('tap', 'node', evt => inspectNode(evt.target));
  cy.on('tap', 'edge', evt => inspectEdge(evt.target));
  cy.on('tap', evt => {
    if (evt.target === cy) closeInspector();
  });

  applyGraphFilters();
}

function drawD3Fallback(nodes, edges) {
  const svgEl = document.getElementById('graph-svg');
  if (!svgEl) return;
  svgEl.style.display = 'block';
  const width = svgEl.clientWidth || 800;
  const height = svgEl.clientHeight || 480;
  const svg = d3.select('#graph-svg');
  svg.selectAll('*').remove();

  const simNodes = nodes.map(n => ({ ...n }));
  const simLinks = edges.map(e => ({ ...e }));

  const sim = d3.forceSimulation(simNodes)
    .force('link', d3.forceLink(simLinks).id(d => d.id).distance(70).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-140))
    .force('center', d3.forceCenter(width / 2, height / 2));

  const link = svg.append('g').selectAll('line')
    .data(simLinks).join('line')
    .attr('stroke', 'rgba(148,163,196,0.25)')
    .attr('stroke-width', 1);

  const node = svg.append('g').selectAll('circle')
    .data(simNodes).join('circle')
    .attr('r', 8)
    .attr('fill', d => NODE_COLORS[d.type] || '#888');

  sim.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
  });
}

function applyGraphFilters() {
  if (!cy) return;
  cy.batch(() => {
    cy.nodes().forEach(node => {
      const type = node.data('type');
      if (activeNodeTypes.has(type)) node.show();
      else node.hide();
    });
    cy.edges().forEach(edge => {
      const type = edge.data('type');
      const srcVisible = activeNodeTypes.has(edge.source().data('type'));
      const tgtVisible = activeNodeTypes.has(edge.target().data('type'));
      if (activeRelTypes.has(type) && srcVisible && tgtVisible) edge.show();
      else edge.hide();
    });
  });
}

function inspectNode(nodeEle) {
  const inspector = document.getElementById('kg-inspector');
  if (inspector) inspector.classList.add('is-active');

  const d = nodeEle.data();
  const props = d.properties || {};
  const inspType = document.getElementById('insp-type');
  const inspBody = document.getElementById('insp-body');

  if (inspType) inspType.textContent = `${d.type} Node`;

  // Find connected edges
  const connectedEdges = nodeEle.connectedEdges();
  let relsHtml = '';
  if (connectedEdges.length) {
    relsHtml = `
      <div class="insp-section-title">Relationships (${connectedEdges.length})</div>
      <div style="max-height:160px; overflow-y:auto;">
        ${connectedEdges.map(edge => {
          const ed = edge.data();
          const otherNode = edge.source().id() === d.id ? edge.target() : edge.source();
          const isSrc = edge.source().id() === d.id;
          return `
            <div class="insp-edge-item">
              <span>${isSrc ? '→' : '←'} <b>${escapeHtml(ed.type)}</b> ${escapeHtml(otherNode.data('label'))}</span>
              <span class="kg-count-badge">${escapeHtml(otherNode.data('type'))}</span>
            </div>`;
        }).join('')}
      </div>`;
  }

  let propsGrid = Object.entries(props)
    .filter(([k]) => !['content_hash', 'ingested_at'].includes(k))
    .map(([k, v]) => `
      <div class="insp-prop-row">
        <span class="insp-prop-key">${escapeHtml(k)}</span>
        <span class="insp-prop-val">${escapeHtml(Array.isArray(v) ? v.join(', ') : String(v))}</span>
      </div>`).join('');

  if (inspBody) {
    inspBody.innerHTML = `
      <div class="insp-title">${escapeHtml(d.label)}</div>
      <div style="margin-bottom:12px; font-family:var(--font-mono); font-size:11px; color:var(--text-faint);">ID: ${escapeHtml(d.id)}</div>
      
      <div class="insp-prop-grid">
        ${propsGrid || '<div class="inspector-placeholder">No extra properties</div>'}
      </div>

      ${relsHtml}

      <div style="margin-top:16px;">
        <button class="kg-btn-sub" id="insp-focus-btn" style="width:100%; padding:8px;">🎯 Focus & Show Neighborhood</button>
      </div>`;

    document.getElementById('insp-focus-btn').addEventListener('click', () => {
      cy.nodes().removeClass('highlighted');
      nodeEle.addClass('highlighted');
      nodeEle.neighborhood().nodes().addClass('highlighted');
      cy.animate({
        center: { eles: nodeEle.union(nodeEle.neighborhood()) },
        zoom: 1.5,
        duration: 400
      });
    });
  }
}

function inspectEdge(edgeEle) {
  const inspector = document.getElementById('kg-inspector');
  if (inspector) inspector.classList.add('is-active');

  const d = edgeEle.data();
  const src = edgeEle.source().data();
  const tgt = edgeEle.target().data();
  const inspType = document.getElementById('insp-type');
  const inspBody = document.getElementById('insp-body');

  if (inspType) inspType.textContent = `Relationship: ${d.type}`;

  if (inspBody) {
    inspBody.innerHTML = `
      <div class="insp-title">${escapeHtml(d.type)}</div>
      
      <div class="insp-prop-grid">
        <div class="insp-prop-row">
          <span class="insp-prop-key">Source</span>
          <span class="insp-prop-val">${escapeHtml(src.label)} (${escapeHtml(src.type)})</span>
        </div>
        <div class="insp-prop-row">
          <span class="insp-prop-key">Target</span>
          <span class="insp-prop-val">${escapeHtml(tgt.label)} (${escapeHtml(tgt.type)})</span>
        </div>
        ${Object.entries(d.properties || {}).map(([k, v]) => `
          <div class="insp-prop-row">
            <span class="insp-prop-key">${escapeHtml(k)}</span>
            <span class="insp-prop-val">${escapeHtml(String(v))}</span>
          </div>`).join('')}
      </div>`;
  }
}

function closeInspector() {
  const inspector = document.getElementById('kg-inspector');
  if (inspector) inspector.classList.remove('is-active');
  const inspBody = document.getElementById('insp-body');
  if (inspBody) {
    inspBody.innerHTML = '<div class="inspector-placeholder">Click any node or edge in the Knowledge Graph to inspect properties, relationships, and source provenance.</div>';
  }
}

// Controls wiring
document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('kg-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', e => {
      const query = e.target.value.trim().toLowerCase();
      if (!cy) return;
      cy.nodes().removeClass('highlighted');
      if (!query) return;

      const matches = cy.nodes().filter(node => {
        return node.data('label').toLowerCase().includes(query) || node.data('id').toLowerCase().includes(query);
      });

      if (matches.length) {
        matches.addClass('highlighted');
        cy.animate({ center: { eles: matches }, duration: 300 });
      }
    });
  }

  document.querySelectorAll('[data-layout]').forEach(btn => {
    btn.addEventListener('click', e => {
      document.querySelectorAll('[data-layout]').forEach(b => b.classList.remove('is-active'));
      e.target.classList.add('is-active');
      currentLayoutName = e.target.dataset.layout;
      if (cy) {
        const layout = cy.layout({ name: currentLayoutName, animate: true, animationDuration: 400 });
        layout.run();
      }
    });
  });

  const fitBtn = document.getElementById('kg-fit-btn');
  if (fitBtn) fitBtn.addEventListener('click', () => { if (cy) cy.fit(padding = 30); });

  const resetBtn = document.getElementById('kg-reset-filters-btn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      document.querySelectorAll('.kg-node-cb, .kg-rel-cb').forEach(cb => cb.checked = true);
      if (cy) {
        activeNodeTypes = new Set(fullGraphData.nodes.map(n => n.type));
        activeRelTypes = new Set(fullGraphData.edges.map(e => e.type));
        applyGraphFilters();
      }
    });
  }

  const refreshBtn = document.getElementById('kg-refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadFullGraph);

  const inspClose = document.getElementById('insp-close');
  if (inspClose) inspClose.addEventListener('click', closeInspector);
});

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
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="4">Loading synced documentation pages...</td></tr>`;

  try {
    const res = await fetch(`${API_BASE}/api/docs`);
    const data = await res.json();
    if (!data.pages || !data.pages.length) {
      tbody.innerHTML = `<tr><td colspan="4">No pages synced. Click "Trigger sync" to fetch live docs.</td></tr>`;
      return;
    }
    renderDocsTable(data.pages);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--accent-rose)">Failed to load doc pages: ${escapeHtml(String(e))}</td></tr>`;
  }
}

function renderDocsTable(pages) {
  const tbody = document.querySelector('#docs-table tbody');
  if (!tbody) return;
  tbody.innerHTML = pages.map(p => {
    const isRel = p.source === 'releases' || (p.url && p.url.includes('releases.')) || p.type === 'ReleaseNote';
    const featuresHtml = (p.canonical_features && p.canonical_features.length)
      ? p.canonical_features.map(f => `<span class="cite" style="margin-right:4px;">${escapeHtml(f)}</span>`).join('')
      : '—';
    return `
      <tr>
        <td><span class="kg-count-badge" style="background:${isRel ? 'rgba(167,139,250,0.15)' : 'rgba(94,234,212,0.15)'}; color:${isRel ? 'var(--accent-violet)' : 'var(--accent-cyan)'}">${isRel ? 'releases' : 'docs'}</span></td>
        <td>
          <a href="${escapeHtml(p.url)}" target="_blank" style="color:var(--accent-cyan); text-decoration:none; font-weight:500;">
            ${escapeHtml(p.title || p.url)}
          </a>
          <div style="font-size:11px; color:var(--text-faint); font-family:var(--font-mono); margin-top:2px;">${escapeHtml(p.url)}</div>
        </td>
        <td style="font-family:var(--font-mono); font-size:11.5px; color:var(--text-dim);">${escapeHtml(typeof p.last_fetched === 'number' ? new Date(p.last_fetched * 1000).toLocaleTimeString() : String(p.last_fetched))}</td>
        <td>${featuresHtml}</td>
      </tr>`;
  }).join('');
}

document.getElementById('sync-btn').addEventListener('click', async () => {
  const btn = document.getElementById('sync-btn');
  btn.textContent = 'Syncing live pages…';
  btn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/docs/sync`, { method: 'POST' });
    const data = await res.json();
    if (data.pages && data.pages.length) {
      renderDocsTable(data.pages);
    } else {
      loadDocsTab();
    }
  } catch (e) {
    document.querySelector('#docs-table tbody').innerHTML = `<tr><td colspan="4" style="color:var(--accent-rose)">Sync failed: ${escapeHtml(String(e))}</td></tr>`;
  }
  btn.textContent = 'Trigger sync';
  btn.disabled = false;
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

// ============================= Init & SSE =============================
function initSSE() {
  window.addEventListener('resize', () => {
    if (cy) {
      cy.resize();
      cy.fit(30);
    }
  });

  if (window.EventSource) {
    const sse = new EventSource(`${API_BASE}/api/graph/events`);
    sse.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data);
        if (payload.event === 'KNOWLEDGE_GRAPH_UPDATED') {
          console.log('[SSE] KNOWLEDGE_GRAPH_UPDATED Event received:', payload);
          if (typeof loadFullGraph === 'function') loadFullGraph();
        }
      } catch (e) {}
    };
  }
}

(async function init() {
  initSSE();
  try {
    const res = await fetch(`${API_BASE}/api/graph/stats`);
    const stats = await res.json();
    document.getElementById('rail-node-count').innerHTML =
      `<span class="dot dot-live"></span> ${stats.total_nodes || stats.node_count} nodes indexed`;
  } catch (e) { /* backend not reachable yet — non-fatal */ }
})();
