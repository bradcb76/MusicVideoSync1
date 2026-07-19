const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const page = document.body.dataset.page;

function toast(message, error = false) {
  const item = document.createElement('div');
  item.className = `toast ${error ? 'error' : ''}`;
  item.textContent = message;
  $('#toast-region')?.append(item);
  setTimeout(() => item.remove(), 4500);
}

async function api(url, options = {}) {
  const opts = {...options, headers: {...(options.headers || {}), Accept: 'application/json'}};
  if (opts.body && typeof opts.body !== 'string') {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(opts.method)) {
    opts.headers['X-CSRF-Token'] = csrf;
  }
  const response = await fetch(url, opts);
  if (response.status === 401 && page !== 'login') {
    window.location.assign('/login');
    throw new Error('Your session has expired');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error?.message || data.detail || 'Request failed');
  return data;
}

function bytes(value) {
  if (value === undefined || value === null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = Number(value), unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function setStatus(node, label, tone = 'neutral') {
  if (!node) return;
  node.textContent = label;
  node.className = `status-pill ${tone}`;
}

function titleCase(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function renderActivity(items, target = '#activity') {
  const root = $(target);
  if (!root) return;
  root.textContent = '';
  if (!items?.length) {
    const empty = document.createElement('div');
    empty.className = 'empty compact';
    empty.textContent = 'No recent activity yet.';
    root.append(empty);
    return;
  }
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'activity-row';
    const event = document.createElement('strong');
    event.textContent = titleCase(item.event || item.level || 'Event');
    const message = document.createElement('span');
    message.textContent = item.message || 'Activity recorded';
    const time = document.createElement('time');
    time.textContent = item.created_at ? new Date(item.created_at).toLocaleString() : '';
    row.append(event, message, time);
    root.append(row);
  });
}

async function loadDashboard() {
  try {
    const [data, scanner, scheduler, integrations] = await Promise.all([
      api('/api/dashboard'),
      api('/api/library/status'),
      api('/api/scheduler/status'),
      api('/api/integrations/status')
    ]);

    const values = {
      tracks: data.tracks,
      identified: data.identified,
      artists: data.artists,
      completed: data.jobs.completed || 0,
      pending: data.jobs.queued || 0,
      failed: data.jobs.failed || 0
    };
    $$('[data-metric]').forEach(item => {
      item.textContent = Number(values[item.dataset.metric] || 0).toLocaleString();
      item.closest('.metric')?.classList.remove('skeleton');
    });

    const percent = data.daily_limit ? Math.min(100, data.downloads_today / data.daily_limit * 100) : 0;
    $('#daily-progress').style.width = `${percent}%`;
    $('#daily-percent').textContent = `${Math.round(percent)}%`;
    $('#daily-count').textContent = `${data.downloads_today} / ${data.daily_limit}`;
    $('#daily-copy').textContent = 'downloads used today';

    const disk = data.disk || {};
    const usedPercent = disk.total ? Math.min(100, disk.used / disk.total * 100) : 0;
    $('#disk-free').textContent = bytes(disk.free);
    $('#disk-used').style.width = `${usedPercent}%`;
    $('#disk-used-copy').textContent = `${bytes(disk.used)} used`;
    $('#disk-total-copy').textContent = `${bytes(disk.total)} total`;

    const scanState = scanner.running ? 'Scanning' : 'Ready';
    setStatus($('#scan-state'), scanState, scanner.error ? 'bad' : scanner.running ? 'warn' : 'good');
    $('#scan-copy').textContent = scanner.error || (scanner.running
      ? `${scanner.scanned || 0} tracks checked · ${scanner.current_file || 'Starting…'}`
      : `${data.tracks.toLocaleString()} tracks indexed and ready`);
    $('#scan-progress').style.height = scanner.running ? '100%' : '0';

    const schedulerState = scheduler.control?.state || 'paused';
    const queued = data.jobs.queued || 0;
    setStatus($('#scheduler-state'), titleCase(schedulerState), schedulerState === 'running' ? 'good' : 'neutral');
    $('#scheduler-copy').textContent = `${queued} queued · ${data.jobs.failed || 0} failed · ${data.jobs.completed || 0} completed`;
    const totalJobs = Object.values(data.jobs).reduce((sum, count) => sum + count, 0);
    $('#scheduler-progress').style.height = totalJobs ? `${Math.min(100, (data.jobs.completed || 0) / totalJobs * 100)}%` : '0';

    let enabledServers = 0, healthyServers = 0;
    ['plex', 'emby'].forEach(provider => {
      const item = integrations[provider] || {};
      const card = document.querySelector(`[data-summary-provider="${provider}"]`);
      const status = $('[data-server-status]', card);
      const detail = $('[data-server-detail]', card);
      if (item.enabled) enabledServers += 1;
      if (item.enabled && ['ready', 'connected', 'ok', 'refreshed'].includes(item.status)) healthyServers += 1;
      setStatus(status, item.enabled ? titleCase(item.status || 'Configured') : 'Disabled',
        !item.enabled ? 'neutral' : item.status === 'error' ? 'bad' : 'good');
      detail.textContent = item.server_name || item.last_result || (item.enabled ? 'Configured, not tested yet' : 'Not configured');
    });
    $('#servers-copy').textContent = enabledServers
      ? `${healthyServers} of ${enabledServers} configured servers reporting ready`
      : 'Plex and Emby are available to configure';
    setStatus($('#servers-state'), enabledServers ? `${healthyServers}/${enabledServers} Ready` : 'Not set up',
      enabledServers && healthyServers === enabledServers ? 'good' : 'neutral');

    renderActivity(data.activity);
    $('#metrics')?.setAttribute('aria-busy', 'false');
  } catch (error) {
    toast(error.message, true);
    $('#connection')?.classList.add('offline');
    $('#connection span').textContent = 'Connection issue';
  }
}

async function loadTracks() {
  const marker = $('#tracks-page');
  const currentPage = Number(marker?.dataset.page || 1);
  const search = $('#track-search')?.value || '';
  const sort = $('#track-sort')?.value || 'artist';
  try {
    const data = await api(`/api/library/tracks?page=${currentPage}&search=${encodeURIComponent(search)}&sort=${encodeURIComponent(sort)}`);
    const body = $('#track-table');
    if (!body) return;
    body.textContent = '';
    data.items.forEach(item => {
      const row = document.createElement('tr');
      const duration = item.duration_seconds
        ? `${Math.floor(item.duration_seconds / 60)}:${String(Math.floor(item.duration_seconds % 60)).padStart(2, '0')}`
        : '—';
      [item.artist, item.album, item.title, duration, titleCase(item.video_status)].forEach(value => {
        const cell = document.createElement('td');
        cell.textContent = value || '—';
        row.append(cell);
      });
      body.append(row);
    });
    marker.textContent = `Page ${data.page} · ${data.total.toLocaleString()} tracks`;
    marker.dataset.page = data.page;
  } catch (error) { toast(error.message, true); }
}

async function loadJobs() {
  const fixed = $('[data-fixed-state]')?.dataset.fixedState;
  const state = fixed || window.jobState || '';
  try {
    const data = await api(`/api/jobs?state=${encodeURIComponent(state)}`);
    const list = $('#job-list');
    if (!list) return;
    list.textContent = '';
    if (!data.items.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No jobs in this view.';
      list.append(empty);
    }
    data.items.forEach(item => {
      const card = document.createElement('article');
      card.className = 'job';
      const heading = document.createElement('strong');
      heading.textContent = item.artist || `Job ${item.id}`;
      const stateNode = document.createElement('span');
      stateNode.className = `status-pill ${item.state === 'failed' ? 'bad' : item.state === 'completed' ? 'good' : 'neutral'}`;
      stateNode.textContent = titleCase(item.state);
      const detail = document.createElement('p');
      detail.textContent = `${item.message || 'Queued'} · ${item.progress}%`;
      card.append(heading, stateNode, detail);
      list.append(card);
    });
  } catch (error) { toast(error.message, true); }
}

async function loadScheduler() {
  try {
    const data = await api('/api/scheduler/status');
    $('#scheduler-state').textContent = titleCase(data.control.state);
    $('#scheduler-today').textContent = `${data.downloads_today}/${data.daily_limit}`;
    $('#scheduler-lock').textContent = data.control.owner ? 'This service' : 'Available';
    const root = $('#artist-progress');
    root.textContent = '';
    if (!data.progress.length) {
      root.className = 'empty';
      root.textContent = 'No queued artists.';
    } else {
      root.className = 'job-list';
      data.progress.forEach(item => {
        const row = document.createElement('div');
        row.className = 'job';
        row.textContent = `${item.artist || 'Unassigned'} · ${titleCase(item.state)} · ${item.count}`;
        root.append(row);
      });
    }
  } catch (error) { toast(error.message, true); }
}

async function loadIntegrations() {
  try {
    const data = await api('/api/integrations/status');
    $$('.integration-card').forEach(card => {
      const item = data[card.dataset.provider] || {};
      $('[data-field="server_name"]', card).textContent = item.server_name || (item.enabled ? 'Not tested' : 'Disabled');
      $('[data-field="server_version"]', card).textContent = item.server_version || '—';
      $('[data-field="last_refresh_at"]', card).textContent = item.last_refresh_at || 'Never';
      $('[data-field="last_result"]', card).textContent = item.last_result || 'Connection has not been tested.';
      setStatus($('.status-pill', card), item.enabled ? titleCase(item.status || 'Configured') : 'Disabled',
        !item.enabled ? 'neutral' : item.status === 'error' ? 'bad' : 'good');
    });
  } catch (error) { toast(error.message, true); }
}

async function loadDiagnostics() {
  try {
    const data = await api('/api/diagnostics');
    const root = $('#diagnostics');
    root.textContent = '';
    Object.entries(data).forEach(([key, value]) => {
      const card = document.createElement('article');
      card.className = 'panel diagnostic';
      const title = document.createElement('h2');
      title.textContent = titleCase(key);
      const detail = document.createElement('pre');
      detail.textContent = JSON.stringify(value, null, 2);
      card.append(title, detail);
      root.append(card);
    });
  } catch (error) { toast(error.message, true); }
}

async function loadSettings() {
  try {
    const data = await api('/api/settings');
    const form = $('#settings-form');
    if (!form) return;
    form.elements.daily_limit.value = data.daily_limit;
    form.elements.retry_delay_seconds.value = data.retry_delay_seconds;
  } catch (error) { toast(error.message, true); }
}

async function runAction(name, endpoint, body) {
  try {
    const result = await api(endpoint, {method: 'POST', body});
    toast(result.count !== undefined ? `${name}: ${result.count} item(s)` : name);
    await refresh();
    return result;
  } catch (error) {
    toast(error.message, true);
    throw error;
  }
}

async function refresh() {
  if (page === 'dashboard') return loadDashboard();
  if (page === 'library') return loadTracks();
  if (['queue', 'completed', 'failed'].includes(page)) return loadJobs();
  if (page === 'scheduler') return loadScheduler();
  if (page === 'integrations') return loadIntegrations();
  if (page === 'system') return loadDiagnostics();
  if (page === 'settings') return loadSettings();
  if (page === 'logs') {
    const data = await api('/api/dashboard');
    return renderActivity(data.activity);
  }
}

document.addEventListener('click', async event => {
  const actionName = event.target.closest('[data-action]')?.dataset.action;
  if (actionName === 'menu-toggle') document.body.classList.toggle('nav-open');
  if (actionName === 'menu-close') document.body.classList.remove('nav-open');
  if (actionName === 'logout') {
    try { await runAction('Signed out', '/api/auth/logout'); } finally { window.location.assign('/login'); }
  }
  const actions = {
    scan: ['Library scan started', '/api/library/scan'],
    'scheduler-start': ['Scheduler started', '/api/scheduler/start', {dry_run: document.body.dataset.dryRun === 'true'}],
    'scheduler-pause': ['Scheduler paused', '/api/scheduler/pause'],
    'scheduler-resume': ['Scheduler resumed', '/api/scheduler/resume'],
    'scheduler-stop': ['Stop requested', '/api/scheduler/stop-after-current'],
    'retry-failed': ['Failed jobs returned to queue', '/api/scheduler/retry-failed']
  };
  if (actions[actionName]) await runAction(...actions[actionName]);

  const test = event.target.closest('[data-integration-test]')?.dataset.integrationTest;
  if (test) await runAction(`${titleCase(test)} connection tested`, `/api/integrations/${test}/test`);
  const provider = event.target.closest('[data-integration-refresh]')?.dataset.integrationRefresh;
  if (provider) await runAction(`${titleCase(provider)} refresh requested`, `/api/integrations/${provider}/refresh`);

  const filter = event.target.closest('[data-job-state]');
  if (filter) {
    window.jobState = filter.dataset.jobState;
    $$('[data-job-state]').forEach(item => item.classList.toggle('active', item === filter));
    await loadJobs();
  }
});

$('#track-search')?.addEventListener('input', () => {
  clearTimeout(window.trackTimer);
  window.trackTimer = setTimeout(() => { $('#tracks-page').dataset.page = 1; loadTracks(); }, 300);
});
$('#track-sort')?.addEventListener('change', loadTracks);
$('#tracks-prev')?.addEventListener('click', () => {
  const node = $('#tracks-page');
  node.dataset.page = Math.max(1, Number(node.dataset.page || 1) - 1);
  loadTracks();
});
$('#tracks-next')?.addEventListener('click', () => {
  const node = $('#tracks-page');
  node.dataset.page = Number(node.dataset.page || 1) + 1;
  loadTracks();
});

$('#search-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const root = $('#search-results');
  root.textContent = 'Searching…';
  try {
    const result = await api(`/api/youtube/search?artist=${encodeURIComponent(data.artist)}&title=${encodeURIComponent(data.title)}`);
    root.textContent = '';
    result.items.forEach(item => {
      const card = document.createElement('article');
      card.className = 'panel result';
      const title = document.createElement('h3');
      title.textContent = item.title;
      const channel = document.createElement('p');
      channel.className = 'muted';
      channel.textContent = item.channel;
      const meta = document.createElement('small');
      meta.textContent = item.duration ? `${Math.floor(item.duration / 60)}:${String(item.duration % 60).padStart(2, '0')}` : '';
      card.append(title, channel, meta);
      root.append(card);
    });
    if (!result.items.length) root.textContent = 'No candidates found.';
  } catch (error) { root.textContent = error.message; }
});

$('#settings-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    await api('/api/settings', {method: 'POST', body: {
      daily_limit: Number(data.daily_limit),
      retry_delay_seconds: Number(data.retry_delay_seconds)
    }});
    toast('Settings saved');
  } catch (error) { toast(error.message, true); }
});

refresh();
if (['dashboard', 'scheduler', 'queue'].includes(page)) setInterval(refresh, 5000);