const appsEl = document.querySelector('#apps');
const emptyEl = document.querySelector('#empty');
const titleEl = document.querySelector('#title');
const refreshLabel = document.querySelector('#refresh-label');
const ipTable = document.querySelector('#ip-table');
const tailscaleState = document.querySelector('#tailscale-state');

// Tab switching
const tabs = document.querySelectorAll('.tab');
const tabContents = document.querySelectorAll('.tab-content');
let currentTab = 'apps';
let statsInterval = null;

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const targetTab = tab.dataset.tab;
    switchTab(targetTab);
  });
});

function switchTab(tabName) {
  currentTab = tabName;

  // Update tab buttons
  tabs.forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === tabName);
  });

  // Update tab content
  tabContents.forEach(content => {
    content.classList.toggle('active', content.id === `tab-${tabName}`);
  });

  // Handle stats loading
  if (tabName === 'stats') {
    loadStatistics();
  } else {
    // Clear stats interval when not on stats tab
    if (statsInterval) {
      clearInterval(statsInterval);
      statsInterval = null;
    }
  }
}

const iconText = (name) => {
  const words = name.trim().split(/\s+/).slice(0, 2);
  return words.map((word) => word[0] || '').join('').toUpperCase() || 'A';
};

const formatBytes = (value) => {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let current = value;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  return `${current.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

const setGauge = (id, percent, detailId, detail) => {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  const gauge = document.querySelector(id);
  gauge.classList.remove('loading');
  gauge.style.setProperty('--value', value);
  gauge.querySelector('span').textContent = `${value}%`;
  document.querySelector(detailId).textContent = detail;
};

const renderLoadingSystem = () => {
  for (const id of ['#gauge-ram', '#gauge-cpu', '#gauge-disk']) {
    const gauge = document.querySelector(id);
    gauge.classList.add('loading');
    gauge.style.setProperty('--value', 0);
    gauge.querySelector('span').textContent = '--';
  }
  document.querySelector('#ram-detail').textContent = 'Loading metrics';
  document.querySelector('#cpu-detail').textContent = 'Loading metrics';
  document.querySelector('#disk-detail').textContent = 'Loading metrics';
  tailscaleState.textContent = 'Checking Tailscale';
  tailscaleState.classList.remove('online');
  ipTable.innerHTML = '<tr class="loading-row"><td colspan="4"><span class="loading-line wide"></span></td></tr>';
};

const renderLoadingApps = (apps = []) => {
  emptyEl.hidden = true;
  appsEl.innerHTML = '';
  // Use provided apps list or show generic loading placeholders
  const appsToRender = apps.length > 0 ? apps : [
    { name: 'Loading apps...', description: 'Discovering containers', port: '', container: '', stats: {} }
  ];

  for (const app of appsToRender) {
    const card = document.createElement('article');
    card.className = 'card loading-card';
    card.innerHTML = `
      <div class="card-head">
        <div class="icon loading-pulse" aria-hidden="true">${iconText(app.name)}</div>
        <span class="badge loading-pulse">loading</span>
      </div>
      <div>
        <h2>${app.name}</h2>
        <p><span class="loading-line wide"></span><span class="loading-line short"></span></p>
        <div class="app-stats">
          <span class="stat-pill">CPU<strong>--</strong></span>
          <span class="stat-pill">RAM<strong>--</strong></span>
          <span class="stat-pill">Disk<strong>--</strong></span>
        </div>
      </div>
      <div class="meta">
        <span>checking</span>
        <span>Docker</span>
      </div>
    `;
    appsEl.appendChild(card);
  }
};

const renderSystem = (payload) => {
  const metrics = payload.metrics || {};
  const ram = metrics.ram || {};
  const cpu = metrics.cpu || {};
  const disk = metrics.disk || {};

  setGauge('#gauge-ram', ram.percent, '#ram-detail', `${formatBytes(ram.used)} / ${formatBytes(ram.total)}`);
  setGauge('#gauge-cpu', cpu.percent, '#cpu-detail', 'Current load');
  setGauge('#gauge-disk', disk.percent, '#disk-detail', `${formatBytes(disk.used)} / ${formatBytes(disk.total)}`);

  const network = payload.network || {};
  const tailscale = network.tailscale || {};
  tailscaleState.textContent = tailscale.online ? 'Tailscale on' : 'Tailscale off';
  tailscaleState.classList.toggle('online', Boolean(tailscale.online));

  ipTable.innerHTML = '';
  for (const row of network.addresses || []) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td></td><td></td><td></td><td></td>';
    const cells = tr.querySelectorAll('td');
    cells[0].textContent = row.interface || '';
    cells[1].textContent = row.address || '';
    cells[2].textContent = row.family || '';
    cells[3].textContent = row.tailscale ? 'yes' : 'no';
    ipTable.appendChild(tr);
  }
};

const renderApps = (payload) => {
  titleEl.textContent = payload.title || 'DGX Spark Portal';
  const apps = payload.apps || [];
  emptyEl.hidden = apps.length !== 0;
  appsEl.innerHTML = '';

  for (const app of apps) {
    const card = document.createElement('a');
    card.className = 'card';
    card.href = app.url || '#';
    card.target = '_blank';
    card.rel = 'noreferrer';
    card.setAttribute('aria-label', `Open ${app.name}`);

    const port = app.port ? `:${app.port}` : 'Docker';
    card.innerHTML = `
      <div class="card-head">
        <div class="icon" aria-hidden="true">${iconText(app.name)}</div>
        <span class="badge">${app.status || 'running'}</span>
      </div>
      <div>
        <h2></h2>
        <p></p>
        <div class="app-stats">
          <span class="stat-pill">CPU<strong></strong></span>
          <span class="stat-pill">RAM<strong></strong></span>
          <span class="stat-pill">Disk<strong></strong></span>
        </div>
      </div>
      <div class="meta">
        <span></span>
        <span></span>
      </div>
    `;
    card.querySelector('h2').textContent = app.name;
    card.querySelector('p').textContent = app.description || 'Published container application';
    const stats = app.stats || {};
    const statValues = card.querySelectorAll('.stat-pill strong');
    statValues[0].textContent = stats.cpu_percent == null ? '--' : `${stats.cpu_percent}%`;
    statValues[1].textContent = stats.memory_percent == null ? '--' : `${stats.memory_percent}%`;
    statValues[2].textContent = stats.block_io == null ? '--' : formatBytes(stats.block_io);
    const meta = card.querySelectorAll('.meta span');
    meta[0].textContent = port;
    meta[1].textContent = app.container || '';
    appsEl.appendChild(card);
  }

  refreshLabel.textContent = `Live · ${payload.refreshSeconds || 5}s`;
};

const load = async () => {
  try {
    // Fetch apps first to show actual running containers immediately
    const appsResponse = await fetch('/api/apps', { cache: 'no-store' });
    if (!appsResponse.ok) throw new Error('HTTP error');
    const appsPayload = await appsResponse.json();

    // Render apps with current stats (may show zeros on first load)
    renderApps(appsPayload);

    // Then fetch system metrics independently
    const systemResponse = await fetch('/api/system', { cache: 'no-store' });
    if (systemResponse.ok) {
      const systemPayload = await systemResponse.json();
      renderSystem(systemPayload);
    }

    window.setTimeout(load, (appsPayload.refreshSeconds || 5) * 1000);
  } catch (error) {
    refreshLabel.textContent = 'Disconnected';
    window.setTimeout(load, 5000);
  }
};

renderLoadingSystem();
renderLoadingApps();
load();

// Setup network panel collapse toggle
const networkPanel = document.querySelector('.network-panel');
const collapseToggle = document.querySelector('.collapse-toggle');
if (collapseToggle && networkPanel) {
  collapseToggle.addEventListener('click', () => {
    networkPanel.classList.toggle('collapsed');
    const isExpanded = !networkPanel.classList.contains('collapsed');
    collapseToggle.setAttribute('aria-expanded', isExpanded);
  });
}

// Statistics functionality
const statsContent = document.querySelector('#stats-content');
const statsLoading = document.querySelector('#stats-loading');
const statsError = document.querySelector('#stats-error');
const statsTime = document.querySelector('#stats-time');
const statsRefreshBtn = document.querySelector('#stats-refresh-btn');
const statsRangeButtons = document.querySelectorAll('.range-btn');
let statsRange = 'hour';

if (statsRefreshBtn) {
  statsRefreshBtn.addEventListener('click', () => loadStatistics());
}

statsRangeButtons.forEach(button => {
  button.addEventListener('click', () => {
    statsRange = button.dataset.range || 'hour';
    statsRangeButtons.forEach(item => {
      item.classList.toggle('active', item === button);
    });
    loadStatistics();
  });
});

async function loadStatistics() {
  if (statsLoading) statsLoading.hidden = false;
  if (statsContent) statsContent.hidden = true;
  if (statsError) statsError.hidden = true;

  try {
    const params = new URLSearchParams({ range: statsRange });
    const response = await fetch(`/api/litellm-stats?${params}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Failed to fetch stats');

    const data = await response.json();
    renderStatistics(data);

    if (statsTime) {
      statsTime.textContent = new Date().toLocaleTimeString();
    }

    if (statsInterval) clearInterval(statsInterval);
    if (currentTab === 'stats') {
      statsInterval = setInterval(loadStatistics, 10000);
    }
  } catch (error) {
    if (statsLoading) statsLoading.hidden = true;
    if (statsError) statsError.hidden = false;
    console.error('Failed to load statistics:', error);
  }
}

function renderStatistics(data) {
  if (!statsContent) return;

  if (statsLoading) statsLoading.hidden = true;
  statsContent.hidden = false;

  const engines = data.engines || groupLegacyModels(data.models || []);

  if (engines.length === 0) {
    statsContent.innerHTML = '<p class="stats-empty">No model statistics available yet. Make some requests to see data.</p>';
    return;
  }

  statsContent.innerHTML = '';
  for (const engine of engines) {
    statsContent.appendChild(createEngineStatsCard(engine));
  }
}

function groupLegacyModels(models) {
  if (!models.length) return [];
  return [{ engine_key: 'legacy', engine_name: 'LLM runtime', type: 'LLM', models }];
}

function createEngineStatsCard(engine) {
  const card = document.createElement('div');
  card.className = 'stats-card';

  const models = engine.models || [];
  const latestToks = models.reduce((total, model) => total + Number(model.tokens_per_second || model.toks || 0), 0);
  const chart = createLineChart(models, statsRange);

  card.innerHTML = `
    <div class="stats-card-header">
      <span class="stats-model-name"></span>
      <span class="stats-model-badge">${engine.type || 'LLM'}</span>
    </div>
    <div class="stats-metrics">
      <div class="metric">
        <div class="metric-label">Models</div>
        <div class="metric-value">${models.length}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Engine Tok/s</div>
        <div class="metric-value">${formatNumber(latestToks)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Samples</div>
        <div class="metric-value">${models.reduce((total, model) => total + (model.history || []).length, 0)}</div>
      </div>
    </div>
    <div class="stats-chart-shell">
      <div class="chart-title-row">
        <span>Tokens per second by model</span>
        <strong>${formatNumber(latestToks)} tok/s</strong>
      </div>
      ${chart}
      <div class="chart-legend">
        ${models.map((model, index) => `<span><i class="legend-dot" style="background:${seriesColor(index)}"></i>${escapeHtml(model.model_name || 'Unknown Model')}</span>`).join('')}
      </div>
    </div>
  `;

  card.querySelector('.stats-model-name').textContent = engine.engine_name || 'LLM engine';
  return card;
}

function normalizeHistory(history) {
  return history
    .map(sample => ({
      ts: Number(sample.ts) || 0,
      toks: Number(sample.toks) || 0,
      tpp: Number(sample.tpp) || 0,
      tft: Number(sample.tft) || 0,
    }))
    .filter(sample => sample.ts > 0)
    .sort((a, b) => a.ts - b.ts);
}

function createLineChart(models, rangeName) {
  const width = 680;
  const height = 280;
  const padding = { top: 18, right: 18, bottom: 34, left: 44 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const now = Math.floor(Date.now() / 1000);
  const windowSeconds = rangeToSeconds(rangeName);
  const minTs = now - windowSeconds;
  const series = models.map((model, index) => ({
    modelName: model.model_name || 'Unknown Model',
    color: seriesColor(index),
    points: normalizeHistory(model.history || [])
      .filter(sample => sample.ts >= minTs)
      .map(sample => ({
        sample,
        x: padding.left + ((sample.ts - minTs) / windowSeconds) * plotWidth,
        y: 0,
      })),
  }));
  const allValues = series.flatMap(item => item.points.map(point => point.sample.toks));
  const maxValue = Math.max(...allValues, 1);
  const ticks = [0, maxValue / 2, maxValue];

  for (const item of series) {
    for (const point of item.points) {
      point.x = clamp(point.x, padding.left, padding.left + plotWidth);
      point.y = padding.top + plotHeight - (point.sample.toks / maxValue) * plotHeight;
    }
  }

  const lines = series.map(item => {
    const path = linePath(item.points);
    if (!path) return '';
    const points = item.points.map(point => `
      <circle class="chart-point" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="4" style="stroke:${item.color}">
        <title>${escapeHtml(item.modelName)} - ${formatDate(point.sample.ts)} - ${formatNumber(point.sample.toks)} tok/s</title>
      </circle>
    `).join('');
    return `<path class="chart-line" d="${path}" style="stroke:${item.color}"></path>${points}`;
  }).join('');

  const emptyText = allValues.length === 0 ? '<text class="chart-empty-text" x="340" y="142" text-anchor="middle">Collecting history...</text>' : '';

  return `
    <svg class="area-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Tokens per second history by model">
      ${ticks.map(value => {
        const y = padding.top + plotHeight - (value / maxValue) * plotHeight;
        return `<g class="chart-gridline"><line x1="${padding.left}" x2="${padding.left + plotWidth}" y1="${y.toFixed(2)}" y2="${y.toFixed(2)}"></line><text x="${padding.left - 10}" y="${(y + 4).toFixed(2)}" text-anchor="end">${formatNumber(value)}</text></g>`;
      }).join('')}
      <text class="chart-axis-label" x="${padding.left}" y="${height - 8}">${rangeStartLabel(rangeName)}</text>
      <text class="chart-axis-label" x="${padding.left + plotWidth}" y="${height - 8}" text-anchor="end">Now</text>
      ${lines}
      ${emptyText}
    </svg>
  `;
}

function linePath(points) {
  if (points.length === 0) return '';
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ');
}

function seriesColor(index) {
  return ['#157f72', '#2563eb', '#c2410c', '#7c3aed', '#be123c', '#0f766e'][index % 6];
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  }[char]));
}

function rangeToSeconds(rangeName) {
  if (rangeName === 'day') return 24 * 60 * 60;
  if (rangeName === '7days') return 7 * 24 * 60 * 60;
  return 60 * 60;
}

function rangeStartLabel(rangeName) {
  if (rangeName === 'day') return '24h ago';
  if (rangeName === '7days') return '7d ago';
  return '1h ago';
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatDate(timestamp) {
  return new Date(timestamp * 1000).toLocaleString();
}

function formatNumber(num) {
  if (num === 0) return '0';
  if (!num || isNaN(num)) return '--';
  return Number(num).toFixed(1);
}

// Add debug logging for stats loading
window.addEventListener('DOMContentLoaded', () => {
  console.log('Portal loaded - tabs ready');
});
