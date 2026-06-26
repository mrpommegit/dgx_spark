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

if (statsRefreshBtn) {
  statsRefreshBtn.addEventListener('click', loadStatistics);
}

async function loadStatistics() {
  if (statsLoading) statsLoading.hidden = false;
  if (statsContent) statsContent.hidden = true;
  if (statsError) statsError.hidden = true;

  try {
    const response = await fetch('/api/litellm-stats', { cache: 'no-store' });
    if (!response.ok) throw new Error('Failed to fetch stats');

    const data = await response.json();
    renderStatistics(data);

    // Update timestamp
    if (statsTime) {
      statsTime.textContent = new Date().toLocaleTimeString();
    }

    // Auto-refresh every 10 seconds when on stats tab
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
  if (statsLoading) statsLoading.hidden = true;
  if (statsContent) statsContent.hidden = false;

  const models = data.models || [];

  if (models.length === 0) {
    statsContent.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 40px;">No model statistics available yet. Make some requests to see data.</p>';
    return;
  }

  statsContent.innerHTML = '';

  for (const model of models) {
    const card = createStatsCard(model);
    statsContent.appendChild(card);
  }
}

function createStatsCard(model) {
  const card = document.createElement('div');
  card.className = 'stats-card';

  const modelName = model.model_name || 'Unknown Model';
  const tpp = model.prompt_tokens_per_second || model.tpp || 0;
  const tft = model.prompt_time_to_first_token || model.tft || 0;
  const toks = model.tokens_per_second || model.toks || 0;

  // Calculate max for chart scaling
  const maxTok = Math.max(toks, 1);
  const barHeight = Math.min(100, (toks / maxTok) * 100);

  card.innerHTML = `
    <div class="stats-card-header">
      <span class="stats-model-name">${modelName}</span>
      <span class="stats-model-badge">${model.type || 'LLM'}</span>
    </div>
    <div class="stats-metrics">
      <div class="metric">
        <div class="metric-label">TPP</div>
        <div class="metric-value">${formatNumber(tpp)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">TFT (ms)</div>
        <div class="metric-value">${formatNumber(tft * 1000)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Tok/s</div>
        <div class="metric-value">${formatNumber(toks)}</div>
      </div>
    </div>
    <div class="stats-chart">
      <div class="chart-bar-container">
        <div class="chart-bar" style="height: ${barHeight}%"></div>
      </div>
    </div>
  `;

  return card;
}

function formatNumber(num) {
  if (num === 0) return '0';
  if (!num || isNaN(num)) return '--';
  return num.toFixed(1);
}
