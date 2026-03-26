// Context Pilot — Frontend Logic

let debounceTimers = {};
let bulkMode = false;
let currentPage = 1;
let PAGE_SIZE = 50;
let blockIndex = 1;
let graphNetwork = null;
let graphDataCache = null;
let graphNodesDataSet = null;
let secretsData = null;

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════

function init() {
    document.querySelectorAll('.tab[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => showTab(btn.dataset.tab, btn));
    });

    document.getElementById('modal-close-btn').addEventListener('click', closeModal);
    document.getElementById('modal-overlay').addEventListener('click', e => {
        if (e.target === e.currentTarget) closeModal();
    });

    document.querySelectorAll('[data-import]').forEach(input => {
        input.addEventListener('change', () => importFile(input, input.dataset.import));
    });

    initTheme();
    initKeyboardShortcuts();
    startup();
}

// ═══════════════════════════════════════════════════════════════
// DARK MODE
// ═══════════════════════════════════════════════════════════════

function initTheme() {
    const saved = localStorage.getItem('cp-theme');
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
    updateThemeIcon();
}

function toggleTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('cp-theme', 'light');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('cp-theme', 'dark');
    }
    updateThemeIcon();
}

function updateThemeIcon() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    btn.innerHTML = isDark ? '&#9788;' : '&#9789;';
    btn.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
}

// ═══════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ═══════════════════════════════════════════════════════════════

function initKeyboardShortcuts() {
    document.addEventListener('keydown', e => {
        const modal = document.getElementById('modal-overlay');
        const isModalOpen = modal && modal.classList.contains('active');
        const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

        // Escape — close global search or modal
        if (e.key === 'Escape') {
            const gs = document.getElementById('global-search-overlay');
            if (gs && gs.classList.contains('active')) {
                closeGlobalSearch();
                e.preventDefault();
                return;
            }
            if (isModalOpen) {
                closeModal();
                e.preventDefault();
                return;
            }
        }

        // Ctrl+K / Cmd+K — open global search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            openGlobalSearch();
            return;
        }

        // Shortcuts only when not in an input
        if (isInput || isModalOpen) return;

        // N — new memory
        if (e.key === 'n') {
            e.preventDefault();
            showTab('memories', null);
            setTimeout(() => document.getElementById('memory-key')?.focus(), 100);
        }

        // 1-7 — tab navigation
        const tabKeys = { '1': 'dashboard', '2': 'memories', '3': 'skills', '4': 'graph', '5': 'secrets', '6': 'sources', '7': 'assembler' };
        if (tabKeys[e.key]) {
            e.preventDefault();
            showTab(tabKeys[e.key], null);
        }
    });
}

async function startup() {
    const status = document.getElementById('startup-status');
    const bar = document.getElementById('startup-bar');
    const steps = [
        ['Connecting event stream...', 15, () => connectSSE()],
        ['Loading version...', 30, () => loadVersion()],
        ['Loading profiles...', 50, () => loadProfiles()],
        ['Loading dashboard...', 70, () => loadDashboard()],
        ['Building search index...', 90, () => rebuildIndex({silent: true})],
        ['Ready', 100, () => {}],
    ];

    for (const [label, pct, fn] of steps) {
        if (status) status.textContent = label;
        if (bar) bar.style.width = pct + '%';
        try { await fn(); } catch (e) { console.error(e); }
        await new Promise(r => setTimeout(r, 120));
    }

    // Fade out loader
    const loader = document.getElementById('startup-loader');
    if (loader) {
        loader.style.opacity = '0';
        setTimeout(() => loader.remove(), 400);
    }

    checkWelcome();
}

function checkWelcome() {
    const overlay = document.getElementById('welcome-overlay');
    if (!overlay) return;

    const btn = document.getElementById('welcome-dismiss-btn');
    if (btn) btn.addEventListener('click', dismissWelcome);

    overlay.addEventListener('click', e => {
        if (e.target === overlay) dismissWelcome();
    });

    const WELCOME_KEY = 'cp-welcome-v2';
    const dismissed = localStorage.getItem(WELCOME_KEY);
    if (!dismissed) {
        requestAnimationFrame(() => overlay.classList.add('active'));
    }
}

function dismissWelcome() {
    localStorage.setItem('cp-welcome-v2', '1');
    const overlay = document.getElementById('welcome-overlay');
    if (overlay) overlay.classList.remove('active');
}

function showWelcomeForNewProfile(profileName) {
    const overlay = document.getElementById('welcome-overlay');
    if (!overlay) return;
    const card = overlay.querySelector('.welcome-card');
    card.querySelector('h2').textContent = 'Profile "' + profileName + '" created';
    card.querySelector('p').textContent = 'Your new profile is ready. Start by importing knowledge or creating memories.';
    overlay.classList.add('active');
}

// ═══════════════════════════════════════════════════════════════
// TABS
// ═══════════════════════════════════════════════════════════════

function showTab(name, clickedBtn) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');

    if (clickedBtn) {
        clickedBtn.classList.add('active');
    } else {
        document.querySelectorAll('.tab').forEach(b => {
            if (b.dataset.tab === name) b.classList.add('active');
        });
    }

    const main = document.querySelector('main');
    if (name === 'graph') {
        main.style.maxWidth = 'none';
        main.style.padding = '0';
    } else {
        main.style.maxWidth = '';
        main.style.padding = '';
    }

    if (name === 'dashboard') loadDashboard();
    if (name === 'memories') loadMemories();
    if (name === 'skills') loadSkills();
    if (name === 'graph') loadGraph();
    if (name === 'secrets') loadSecrets();
    if (name === 'sources') { loadScheduler(); loadConnectors(); loadFolders(); loadWebhooks(); }
    if (name === 'assembler') loadTemplates();
}

// ═══════════════════════════════════════════════════════════════
// LIVE ACTIVITY (SSE)
// ═══════════════════════════════════════════════════════════════

let eventSource = null;
let activityBuffer = [];
const MAX_ACTIVITY = 100;

function connectSSE() {
    if (eventSource) eventSource.close();

    eventSource = new EventSource('/api/events/stream');

    eventSource.onopen = () => {
        const el = document.getElementById('sse-status');
        if (el) el.innerHTML = '<span class="sse-dot connected"></span>live';
    };

    eventSource.onmessage = (e) => {
        try {
            const event = JSON.parse(e.data);
            activityBuffer.unshift(event);
            if (activityBuffer.length > MAX_ACTIVITY) activityBuffer.pop();
            appendActivityItem(event);
            // Pulse the bot on non-api events
            if (event.category !== 'api') { botBusy(); setTimeout(botIdle, 600); }
        } catch (err) { console.error('SSE parse error:', err); }
    };

    eventSource.onerror = () => {
        const el = document.getElementById('sse-status');
        if (el) el.innerHTML = '<span class="sse-dot disconnected"></span>reconnecting...';
    };
}

function appendActivityItem(event) {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;

    const filter = document.getElementById('activity-filter')?.value;
    if (filter && event.category !== filter) return;

    const html = renderActivityItem(event);
    feed.insertAdjacentHTML('afterbegin', html);

    // Trim old items
    while (feed.children.length > MAX_ACTIVITY) {
        feed.removeChild(feed.lastChild);
    }
}

function renderActivityItem(e) {
    const catClass = 'cat-' + e.category;
    const detail = e.detail ? ` <span class="activity-detail">${escapeHtml(e.detail)}</span>` : '';
    return `<div class="activity-item">
        <span class="activity-cat ${catClass}">${e.category}</span>
        <div class="activity-body">
            <span class="activity-action">${escapeHtml(e.action)}</span>
            <span class="activity-subject">${escapeHtml(e.subject)}</span>${detail}
        </div>
        <span class="activity-age">${escapeHtml(e.age)}</span>
    </div>`;
}

async function loadActivityHistory() {
    try {
        const res = await fetch('/api/events?limit=50');
        const events = await res.json();
        activityBuffer = events;
        renderActivityFeed();
    } catch (e) { console.error(e); }
}

function renderActivityFeed() {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;
    const filter = document.getElementById('activity-filter')?.value;
    const filtered = filter ? activityBuffer.filter(e => e.category === filter) : activityBuffer;

    if (filtered.length === 0) {
        feed.innerHTML = '<p class="muted" style="padding:12px 0;">No activity yet. Events will appear here in real-time.</p>';
        return;
    }
    feed.innerHTML = filtered.map(e => renderActivityItem(e)).join('');
}

function filterActivity() {
    renderActivityFeed();
}

function clearActivityFeed() {
    activityBuffer = [];
    const feed = document.getElementById('activity-feed');
    if (feed) feed.innerHTML = '<p class="muted" style="padding:12px 0;">Cleared. New events will appear in real-time.</p>';
}

// ═══════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════

const OP_COLORS = {
    created: 'var(--success)', updated: 'var(--warning)', deleted: 'var(--danger)',
    loaded: 'var(--info)', searched: 'var(--accent)',
};

async function loadDashboard() {
    botBusy();
    try {
        const res = await fetch('/api/dashboard');
        const d = await res.json();

        document.getElementById('dash-memories').textContent = d.memory_count;
        document.getElementById('dash-memories-detail').textContent = d.memory_count === 1 ? '1 memory' : d.memory_count + ' memories';

        document.getElementById('dash-tokens').textContent = d.memory_tokens.toLocaleString();

        const skillEl = document.getElementById('dash-skills');
        skillEl.textContent = `${d.skill_alive}/${d.skill_total}`;
        skillEl.className = 'card-value' + (d.skill_alive > 0 ? ' green' : '');
        document.getElementById('dash-skills-detail').textContent = 'connected';

        // Load activity history on first dashboard load
        if (activityBuffer.length === 0) loadActivityHistory();

        // Connector + scheduler stats for dashboard cards
        try {
            const cRes = await fetch('/api/connectors');
            const connectors = await cRes.json();
            const configured = connectors.filter(c => c.configured).length;
            document.getElementById('dash-connectors').textContent = `${configured}/${connectors.length}`;
            document.getElementById('dash-connectors-detail').textContent = 'configured';
        } catch (e) {}
        try {
            const sRes = await fetch('/api/scheduler');
            const sched = await sRes.json();
            const el = document.getElementById('dash-scheduler');
            if (sched.running) { el.textContent = 'ON'; el.className = 'card-value green'; }
            else { el.textContent = 'OFF'; el.className = 'card-value'; }
            document.getElementById('dash-scheduler-detail').textContent =
                sched.running ? `every ${sched.interval_minutes}m` : 'not running';
        } catch (e) {}
    } catch (e) { console.error('Dashboard load failed:', e); } finally { botIdle(); }

    try {
        const mcpRes = await fetch('/api/mcp-status');
        const mcp = await mcpRes.json();
        const mcpEl = document.getElementById('dash-mcp-status');
        const mcpDetail = document.getElementById('dash-mcp-detail');
        if (mcp.registered) {
            mcpEl.textContent = 'ON';
            mcpEl.className = 'card-value green';
            mcpDetail.textContent = mcp.config?.url || 'SSE registered';
        } else {
            mcpEl.textContent = 'OFF';
            mcpEl.className = 'card-value red';
            mcpDetail.textContent = 'Not registered in Claude';
        }
    } catch (e) {}

    loadDashboardStats();
}

async function loadDashboardStats() {
    try {
        const res = await fetch('/api/dashboard/stats');
        const d = await res.json();

        // New today / this week
        const newEl = document.getElementById('dash-new-today');
        if (newEl) {
            const totalToday = d.new_today + (d.updated_today || 0);
            newEl.textContent = totalToday;
        }
        const weekEl = document.getElementById('dash-new-today-detail');
        if (weekEl) { weekEl.textContent = `${d.new_today} new, ${d.updated_today || 0} updated`; }
        const trashEl = document.getElementById('dash-trash');
        if (trashEl) { trashEl.textContent = d.trash_count; }

        // Top tags chart
        const tagsEl = document.getElementById('dash-top-tags');
        if (tagsEl && d.top_tags.length) {
            const maxCount = d.top_tags[0].count;
            tagsEl.innerHTML = d.top_tags.map(t => {
                const pct = Math.round((t.count / maxCount) * 100);
                return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
                    <span style="font-size:11px;min-width:70px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(t.tag)}</span>
                    <div style="flex:1;height:6px;background:var(--surface-alt);border-radius:3px;overflow:hidden;">
                        <div style="width:${pct}%;height:100%;background:var(--accent);border-radius:3px;"></div>
                    </div>
                    <span style="font-size:10px;color:var(--text-muted);min-width:20px;text-align:right;">${t.count}</span>
                </div>`;
            }).join('');
        } else if (tagsEl) {
            tagsEl.innerHTML = '<span class="muted">No tags yet</span>';
        }

        // Size distribution
        const sizeEl = document.getElementById('dash-size-dist');
        if (sizeEl) {
            const total = d.size_distribution.small + d.size_distribution.medium + d.size_distribution.large;
            if (total > 0) {
                sizeEl.innerHTML = ['small', 'medium', 'large'].map(s => {
                    const count = d.size_distribution[s];
                    const pct = Math.round((count / total) * 100);
                    const colors = {small: 'var(--success)', medium: 'var(--warning)', large: 'var(--accent)'};
                    const labels = {small: '<100 tok', medium: '100-500', large: '500+'};
                    return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
                        <span style="font-size:11px;min-width:60px;">${labels[s]}</span>
                        <div style="flex:1;height:6px;background:var(--surface-alt);border-radius:3px;overflow:hidden;">
                            <div style="width:${pct}%;height:100%;background:${colors[s]};border-radius:3px;"></div>
                        </div>
                        <span style="font-size:10px;color:var(--text-muted);">${count}</span>
                    </div>`;
                }).join('');
            }
        }
    } catch (e) { console.error('Stats load failed:', e); }

    // Connector health
    try {
        const hRes = await fetch('/api/connectors/health');
        const health = await hRes.json();
        const hEl = document.getElementById('dash-connector-health');
        if (hEl) {
            if (health.length === 0) {
                hEl.innerHTML = '<span class="muted">No connectors</span>';
            } else {
                hEl.innerHTML = health.map(c => {
                    const dotClass = c.reachable === true ? 'ok' : c.reachable === false ? 'fail' : 'unknown';
                    return `<div style="font-size:12px;margin-bottom:3px;">
                        <span class="health-dot ${dotClass}"></span>
                        ${escapeHtml(c.display_name || c.name)}
                        <span style="color:var(--text-muted);font-size:10px;">${escapeHtml(c.detail || '')}</span>
                    </div>`;
                }).join('');
            }
        }
    } catch (e) {}
}

// ═══════════════════════════════════════════════════════════════
// CONTEXT PREVIEW
// ═══════════════════════════════════════════════════════════════

async function previewContext() {
    const budget = parseInt(document.getElementById('preview-budget').value) || 8000;
    const el = document.getElementById('preview-result');
    const tid = showToast('Context Preview', `Assembling with ${budget} token budget...`);
    botBusy();

    try {
        const res = await fetch('/api/preview-context?budget=' + budget, { method: 'POST' });
        const d = await res.json();
        const pct = Math.min(100, (d.used_tokens / d.budget) * 100);
        const color = pct > 90 ? 'var(--danger)' : pct > 70 ? 'var(--warning)' : 'var(--success)';

        let html = `
            <div class="preview-bar-container">
                <div class="preview-bar" style="width:${pct}%;background:${color};"></div>
                <span class="preview-bar-label">${d.used_tokens.toLocaleString()} / ${d.budget.toLocaleString()} tokens (${pct.toFixed(1)}%)</span>
            </div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">
                ${d.block_count} blocks included | ${d.dropped_count} dropped | ${d.input_count} total
            </div>`;

        if (d.blocks.length > 0) {
            html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:8px 0 4px;">Included:</div>';
            d.blocks.forEach(b => {
                const hint = b.compress_hint ? ` | ${b.compress_hint}` : '';
                html += `<div class="result-block priority-${b.priority}">
                    <div class="meta">${b.priority.toUpperCase()} | ${b.token_count} tokens${hint}</div>
                    <pre>${escapeHtml(b.content.substring(0, 200))}${b.content.length > 200 ? '...' : ''}</pre>
                </div>`;
            });
        }

        if (d.dropped.length > 0) {
            html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:8px 0 4px;">Dropped:</div>';
            d.dropped.forEach(b => {
                html += `<div class="result-block dropped">
                    <div class="meta">${b.token_count} tokens (dropped)</div>
                    <pre>${escapeHtml(b.content_preview)}</pre>
                </div>`;
            });
        }

        el.innerHTML = html;
        completeToast(tid, `${d.used_tokens}/${d.budget} tokens, ${d.block_count} blocks`, false);
    } catch (e) {
        el.innerHTML = '<p style="color:var(--danger);">Error: ' + escapeHtml(e.message) + '</p>';
        completeToast(tid, 'Failed: ' + e.message, true);
    } finally { botIdle(); }
}

// ═══════════════════════════════════════════════════════════════
// SKILLS
// ═══════════════════════════════════════════════════════════════

function renderSkillCard(s) {
    const alive = s.is_alive !== false && s.status !== 'stale';
    const hints = (s.context_hints || []).slice(0, 6);
    const hintsHtml = hints.length
        ? hints.map(h => `<span class="skill-hint">${escapeHtml(h)}</span>`).join('')
        : '<span class="muted">no hints</span>';
    const blocks = s.blocks_served || 0;
    return `<div class="skill-card">
        <span class="skill-dot ${alive ? 'alive' : 'stale'}"></span>
        <div class="skill-info">
            <div class="skill-name">${escapeHtml(s.name)}</div>
            <div class="skill-desc">${escapeHtml(s.description || '')}</div>
            <div class="skill-hints">${hintsHtml}</div>
            <div class="skill-meta">${blocks} blocks served | ${alive ? 'CONNECTED' : 'STALE'}</div>
        </div>
    </div>`;
}

async function loadSkills() {
    try {
        const res = await fetch('/api/skills');
        const skills = await res.json();
        const list = document.getElementById('skill-list');
        if (skills.length === 0) {
            list.innerHTML = '<p class="muted">No skills connected</p>';
        } else {
            list.innerHTML = skills.map(s => renderSkillCard(s)).join('');
        }
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// MEMORIES
// ═══════════════════════════════════════════════════════════════

async function loadMemories() {
    botBusy();
    const source = document.getElementById('memory-source-filter')?.value || '';
    const sort = document.getElementById('memory-sort')?.value || 'updated';
    const order = document.getElementById('memory-order')?.value || 'desc';
    try {
        const memRes = await fetch(`/api/memories?page=${currentPage}&page_size=${PAGE_SIZE}&source=${encodeURIComponent(source)}&sort=${sort}&order=${order}`);
        const data = await memRes.json();
        renderMemories(data.memories);
        renderPagination(data);
        const countEl = document.getElementById('memory-count');
        if (countEl) countEl.textContent = `${data.total} memories (page ${data.page}/${data.pages})`;
    } catch (e) { console.error('loadMemories failed:', e); } finally { botIdle(); }
    // Load filters and presets independently (non-blocking)
    try {
        const tagRes = await fetch('/api/memory-tags');
        renderTagFilter(await tagRes.json());
    } catch (e) {}
    try {
        const srcRes = await fetch('/api/memories/sources');
        const source2 = document.getElementById('memory-source-filter')?.value || '';
        renderSourceFilter(await srcRes.json(), source2);
    } catch (e) {}
    try {
        const presetRes = await fetch('/api/memory-presets');
        if (presetRes.ok) renderPresets(await presetRes.json());
    } catch (e) {}
}

function renderTagFilter(tags) {
    const sel = document.getElementById('memory-tag-filter');
    const current = sel.value;
    sel.innerHTML = '<option value="">All Tags</option>';
    tags.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        if (t === current) opt.selected = true;
        sel.appendChild(opt);
    });
}

function renderSourceFilter(sources, current) {
    const sel = document.getElementById('memory-source-filter');
    if (!sel) return;
    const prevVal = current || sel.value;
    sel.innerHTML = '<option value="">All Sources</option>';
    sources.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.source;
        opt.textContent = `${s.source} (${s.count})`;
        if (s.source === prevVal) opt.selected = true;
        sel.appendChild(opt);
    });
}

function renderPagination(data) {
    const el = document.getElementById('pagination');
    if (!el) return;
    if (data.pages <= 1) { el.innerHTML = ''; return; }

    const from = (data.page - 1) * data.page_size + 1;
    const to = Math.min(data.page * data.page_size, data.total);

    let html = '';
    html += `<button class="btn btn-small" ${data.page <= 1 ? 'disabled' : ''} onclick="goToPage(1)" title="First">&laquo;</button>`;
    html += `<button class="btn btn-small" ${data.page <= 1 ? 'disabled' : ''} onclick="goToPage(${data.page - 1})">&lsaquo;</button>`;

    const start = Math.max(1, data.page - 2);
    const end = Math.min(data.pages, data.page + 2);
    for (let i = start; i <= end; i++) {
        html += `<button class="btn btn-small ${i === data.page ? 'btn-primary' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    html += `<button class="btn btn-small" ${data.page >= data.pages ? 'disabled' : ''} onclick="goToPage(${data.page + 1})">&rsaquo;</button>`;
    html += `<button class="btn btn-small" ${data.page >= data.pages ? 'disabled' : ''} onclick="goToPage(${data.pages})" title="Last">&raquo;</button>`;
    html += `<span style="font-size:11px;color:var(--text-muted);">${from}-${to} of ${data.total}</span>`;
    el.innerHTML = html;
}

function goToPage(page) {
    currentPage = page;
    const q = document.getElementById('memory-search').value.trim();
    if (q) { filterByTag(); } else { loadMemories(); }
}

function changePageSize() {
    PAGE_SIZE = parseInt(document.getElementById('page-size-select')?.value || '50');
    currentPage = 1;
    loadMemories();
}

async function filterByTag() {
    const tag = document.getElementById('memory-tag-filter').value;
    const source = document.getElementById('memory-source-filter')?.value || '';
    const q = document.getElementById('memory-search').value.trim();
    try {
        let url = `/api/memories/search?q=${encodeURIComponent(q)}&page=${currentPage}&page_size=${PAGE_SIZE}`;
        if (tag) url += '&tags=' + encodeURIComponent(tag);
        if (source) url += '&source=' + encodeURIComponent(source);
        const res = await fetch(url);
        const data = await res.json();
        renderMemories(data.memories);
        renderPagination(data);
        const countEl = document.getElementById('memory-count');
        if (countEl) countEl.textContent = `${data.total} results (page ${data.page}/${data.pages})`;
    } catch (e) { console.error(e); }
}

function renderMemories(data) {
    const list = document.getElementById('memory-list');

    if (!data || data.length === 0) {
        list.innerHTML = '<div class="empty-state">No memories found.</div>';
        return;
    }

    const now = Date.now() / 1000;
    const RECENT = 86400;

    list.innerHTML = data.map(m => {
        const isNew = m.created_at && (now - m.created_at) < RECENT;
        const isModified = !isNew && m.updated_at && m.created_at
            && Math.abs(m.updated_at - m.created_at) > 2
            && (now - m.updated_at) < RECENT;

        let badge = '';
        if (isNew) badge = '<span class="badge badge-new">NEW</span> ';
        else if (isModified) badge = '<span class="badge badge-upd">UPD</span> ';

        let age = '';
        const ts = m.updated_at || m.created_at;
        if (ts) {
            const delta = now - ts;
            if (delta < 3600) age = Math.floor(delta / 60) + 'm ago';
            else if (delta < 86400) age = Math.floor(delta / 3600) + 'h ago';
            else age = Math.floor(delta / 86400) + 'd ago';
        }

        const stateClass = isNew ? ' new' : isModified ? ' updated' : '';
        const cbHtml = bulkMode ? '<input type="checkbox" class="bulk-cb" data-key="' + escapeAttr(m.key) + '" onclick="event.stopPropagation()">' : '';
        const tagsHtml = (m.tags || []).length
            ? m.tags.map(t => '<span class="tag" onclick="event.stopPropagation();clickTag(\'' + escapeAttr(t) + '\')">#' + escapeHtml(t) + '</span>').join(' ')
            : '';

        const pinned = m.pinned || false;
        const pinIcon = pinned ? '<span class="pin-badge" title="Pinned">P</span>' : '';

        // Size info
        const tokens = m.tokens || 0;
        const bytes = m.bytes || 0;
        let sizeStr = '';
        if (tokens > 0) {
            const byteLabel = bytes >= 1024 ? (bytes / 1024).toFixed(1) + ' KB' : bytes + ' B';
            sizeStr = '<span class="token-count">' + tokens + ' tok / ' + byteLabel + '</span>';
        }

        const ek = escapeAttr(m.key);

        return '<div class="memory-item' + stateClass + '" onclick="viewMemory(\'' + ek + '\')">'
            + cbHtml
            + '<div class="main">'
            + '<div class="key">' + pinIcon + badge + escapeHtml(m.key) + '</div>'
            + '<div class="preview">' + escapeHtml((m.value || '').substring(0, 120)) + '</div>'
            + '<div class="meta">'
            + tagsHtml
            + sizeStr
            + (age ? ' <span class="age">' + age + '</span>' : '')
            + '</div>'
            + '</div>'
            + '<div class="actions" onclick="event.stopPropagation()">'
            + '<button class="btn btn-small" onclick="togglePin(\'' + ek + '\',' + !pinned + ')" title="' + (pinned ? 'Unpin' : 'Pin') + '">' + (pinned ? 'Unpin' : 'Pin') + '</button>'
            + '<button class="btn btn-small btn-danger" onclick="deleteMemory(\'' + ek + '\')">Del</button>'
            + '</div>'
            + '</div>';
    }).join('');
}

// --- Memory CRUD ---

function memoryUrl(key) {
    return '/api/memories/' + key.split('/').map(encodeURIComponent).join('/');
}

function openModal(title, bodyHtml, footerHtml) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-footer').innerHTML = footerHtml || '';
    document.getElementById('modal-overlay').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    destroyEditor();
    document.getElementById('modal-overlay').classList.remove('active');
    document.body.style.overflow = '';
}

let activeEditor = null;

async function viewMemory(key) {
    try {
        const res = await fetch(memoryUrl(key));
        if (!res.ok) return;
        const m = await res.json();
        const tagsHtml = m.tags.length
            ? m.tags.map(t => `<span class="tag" onclick="event.stopPropagation();clickTag('${escapeAttr(t)}');closeModal();">#${escapeHtml(t)}</span>`).join(' ')
            : '<span class="muted">none</span>';

        // Render markdown to HTML for preview
        const rendered = typeof EasyMDE !== 'undefined'
            ? EasyMDE.prototype.markdown(m.value)
            : '<pre>' + escapeHtml(m.value) + '</pre>';

        openModal(m.key, `
            <label>Tags</label>
            <div style="margin-bottom:16px;">${tagsHtml}</div>
            <label>Content</label>
            <div class="md-preview">${rendered}</div>
        `, `
            <button class="btn" onclick="showVersions('${escapeAttr(m.key)}')">History</button>
            <button class="btn btn-primary" onclick="editMemory('${escapeAttr(m.key)}')">Edit</button>
            <button class="btn" onclick="closeModal()">Close</button>
        `);
    } catch (e) { console.error(e); }
}

async function editMemory(key) {
    destroyEditor();
    try {
        const res = await fetch(memoryUrl(key));
        if (!res.ok) return;
        const m = await res.json();

        openModal('Edit: ' + m.key, `
            <label>Key</label>
            <input type="text" id="edit-key" value="${escapeHtml(m.key)}" readonly style="background:var(--surface-alt);cursor:not-allowed;">
            <label>Value</label>
            <textarea id="edit-value">${escapeHtml(m.value)}</textarea>
            <label>Tags (comma-separated)</label>
            <input type="text" id="edit-tags" value="${escapeHtml(m.tags.join(', '))}">
        `, `
            <button class="btn btn-primary" id="save-memory-btn">Save</button>
            <button class="btn" id="cancel-memory-btn">Cancel</button>
        `);

        // Initialize EasyMDE on the textarea
        initEditor('edit-value');

        document.getElementById('save-memory-btn').addEventListener('click', () => saveEditedMemory(m.key));
        document.getElementById('cancel-memory-btn').addEventListener('click', () => { destroyEditor(); closeModal(); });
    } catch (e) { console.error(e); }
}

function initEditor(textareaId) {
    destroyEditor();
    const el = document.getElementById(textareaId);
    if (!el || typeof EasyMDE === 'undefined') return;

    activeEditor = new EasyMDE({
        element: el,
        spellChecker: false,
        autofocus: true,
        status: ['lines', 'words'],
        minHeight: '250px',
        toolbar: [
            'bold', 'italic', 'heading', '|',
            'code', 'quote', 'unordered-list', 'ordered-list', '|',
            'link', 'table', 'horizontal-rule', '|',
            'preview', 'side-by-side', 'fullscreen', '|',
            'guide',
        ],
    });
}

function destroyEditor() {
    if (activeEditor) {
        activeEditor.toTextArea();
        activeEditor = null;
    }
}

async function saveEditedMemory(key) {
    const value = activeEditor ? activeEditor.value() : document.getElementById('edit-value').value;
    const tagsStr = document.getElementById('edit-tags').value;
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
    destroyEditor();
    const tid = showToast('Saving memory', key);
    try {
        const res = await fetch(memoryUrl(key), {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value, tags})
        });
        if (res.ok) {
            completeToast(tid, 'Saved', false);
            closeModal();
            loadMemories();
        } else {
            completeToast(tid, 'Save failed: ' + res.status, true);
        }
    } catch (e) { completeToast(tid, 'Error: ' + e.message, true); }
}

async function saveNewMemory() {
    const key = document.getElementById('memory-key').value.trim();
    const value = document.getElementById('memory-value').value.trim();
    if (!key || !value) return;
    const tagsStr = document.getElementById('memory-tags').value.trim();
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
    try {
        await fetch('/api/memories', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value, tags})
        });
        document.getElementById('memory-key').value = '';
        document.getElementById('memory-value').value = '';
        document.getElementById('memory-tags').value = '';
        loadMemories();
    } catch (e) { console.error(e); }
}

async function deleteMemory(key) {
    if (!confirm(`Delete "${key}"?`)) return;
    try {
        await fetch(memoryUrl(key), {method: 'DELETE'});
        loadMemories();
    } catch (e) { console.error(e); }
}

async function searchMemories() {
    currentPage = 1;
    clearTimeout(debounceTimers['memSearch']);
    const semantic = document.getElementById('semantic-toggle')?.checked;
    if (semantic) {
        debounceTimers['memSearch'] = setTimeout(() => semanticSearch(), 500);
    } else {
        debounceTimers['memSearch'] = setTimeout(() => filterByTag(), 300);
    }
}

async function semanticSearch() {
    const q = document.getElementById('memory-search').value.trim();
    if (!q) { loadMemories(); return; }
    const tid = showToast('Semantic search', q);
    botBusy();
    try {
        const res = await fetch(`/api/semantic-search?q=${encodeURIComponent(q)}&limit=20`);
        const data = await res.json();
        // Add similarity badge to rendering
        const list = document.getElementById('memory-list');
        const countEl = document.getElementById('memory-count');
        if (countEl) countEl.textContent = `${data.length} results (semantic)`;
        if (data.length === 0) {
            list.innerHTML = '<div class="empty-state">No semantic matches. Try rebuilding the index.</div>';
            return;
        }
        list.innerHTML = data.map(m => {
            const pct = Math.round((m.similarity || 0) * 100);
            const tagsHtml = (m.tags || []).map(t => `<span class="tag" onclick="event.stopPropagation();clickTag('${escapeAttr(t)}')">#${escapeHtml(t)}</span>`).join(' ');
            return `<div class="memory-item" onclick="viewMemory('${escapeAttr(m.key)}')">
                <div class="main">
                    <div class="key"><span class="badge badge-upd">${pct}%</span> ${escapeHtml(m.key)}</div>
                    <div class="preview">${escapeHtml((m.value || '').substring(0, 150))}</div>
                    <div class="meta">${tagsHtml}</div>
                </div>
            </div>`;
        }).join('');
        completeToast(tid, `${data.length} results`, false);
    } catch (e) { completeToast(tid, 'Failed', true); console.error(e); }
    finally { botIdle(); }
}

async function rebuildIndex({silent = false} = {}) {
    const tid = silent ? null : showToast('Building search index', 'Computing embeddings...');
    if (!silent) botBusy();
    try {
        const res = await fetch('/api/embeddings/index', { method: 'POST' });
        const d = await res.json();
        if (tid) completeToast(tid, `${d.indexed} indexed, ${d.skipped} skipped (${d.backend})`, false);
    } catch (e) {
        if (tid) completeToast(tid, 'Failed: ' + e.message, true);
        console.error('rebuildIndex failed:', e);
    }
    finally { if (!silent) botIdle(); }
}

// ═══════════════════════════════════════════════════════════════
// SMART TAG SUGGESTIONS
// ═══════════════════════════════════════════════════════════════

async function suggestTags() {
    clearTimeout(debounceTimers['tagSuggest']);
    debounceTimers['tagSuggest'] = setTimeout(async () => {
        const key = document.getElementById('memory-key').value.trim();
        const value = document.getElementById('memory-value').value.trim();
        const container = document.getElementById('tag-suggestions');
        if (!key && !value) { container.style.display = 'none'; return; }
        try {
            const res = await fetch('/api/memories/suggest-tags', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key, value})
            });
            const d = await res.json();
            if (d.tags.length === 0) { container.style.display = 'none'; return; }
            container.style.display = 'flex';
            container.innerHTML = d.tags.map(t =>
                `<span class="tag-suggestion" onclick="addSuggestedTag('${escapeAttr(t)}')">#${escapeHtml(t)}</span>`
            ).join('');
        } catch (e) { container.style.display = 'none'; }
    }, 600);
}

function addSuggestedTag(tag) {
    const input = document.getElementById('memory-tags');
    const current = input.value.split(',').map(t => t.trim()).filter(Boolean);
    if (!current.includes(tag)) {
        current.push(tag);
        input.value = current.join(', ');
    }
}

function clickTag(tag) {
    const sel = document.getElementById('memory-tag-filter');
    for (let i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === tag) {
            sel.selectedIndex = i;
            filterByTag();
            showTab('memories');
            return;
        }
    }
}

// --- Bulk Operations ---

function toggleBulkMode() {
    bulkMode = !bulkMode;
    document.getElementById('bulk-delete-btn').style.display = bulkMode ? '' : 'none';
    document.getElementById('bulk-tag-btn').style.display = bulkMode ? '' : 'none';
    document.getElementById('bulk-toggle-btn').textContent = bulkMode ? 'Cancel' : 'Select';
    loadMemories();
}

async function bulkDeleteSelected() {
    const checked = document.querySelectorAll('.bulk-cb:checked');
    if (checked.length === 0) { alert('No memories selected.'); return; }
    const keys = Array.from(checked).map(cb => cb.dataset.key);
    if (!confirm(`Delete ${keys.length} memories?`)) return;
    const tid = showToast('Deleting memories', `${keys.length} selected...`);
    try {
        const res = await fetch('/api/memories/bulk-delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(keys)
        });
        const d = await res.json();
        completeToast(tid, `${d.count} deleted`, false);
        loadMemories();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function exportMemories() {
    const tag = document.getElementById('memory-tag-filter').value;
    const url = tag ? `/api/export-memories?tag=${encodeURIComponent(tag)}` : '/api/export-memories';
    try {
        const res = await fetch(url);
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `context-pilot-export${tag ? '-' + tag : ''}.json`;
        a.click();
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// BLOCK MANAGEMENT + ASSEMBLY
// ═══════════════════════════════════════════════════════════════

function estimateTokens(textarea) {
    const entry = textarea.closest('.block-entry');
    const badge = entry.querySelector('.token-badge');
    const text = textarea.value;
    clearTimeout(debounceTimers[entry.dataset.index]);
    debounceTimers[entry.dataset.index] = setTimeout(async () => {
        if (!text.trim()) { badge.textContent = '0 tokens'; return; }
        try {
            const res = await fetch('/api/estimate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text})
            });
            const data = await res.json();
            badge.textContent = data.tokens + ' tokens';
        } catch (e) { badge.textContent = '? tokens'; }
    }, 300);
}

function _blockTemplate(idx) {
    return `<div class="block-header">
        <span class="block-label">Block ${idx}</span>
        <select class="block-priority">
            <option value="high">High</option>
            <option value="medium" selected>Medium</option>
            <option value="low">Low</option>
        </select>
        <select class="block-hint">
            <option value="">No compression</option>
            <option value="bullet_extract">Bullet Extract</option>
            <option value="yaml_struct">YAML Struct</option>
            <option value="mermaid">Mermaid</option>
            <option value="table">Table</option>
            <option value="code_compact">Code Compact</option>
        </select>
        <span class="token-badge">0 tokens</span>
        <button class="btn btn-small" onclick="testCompressBlock(this)">Test</button>
        <button class="btn btn-small" onclick="duplicateBlock(this)">Dup</button>
        <button class="btn btn-small btn-danger" onclick="removeBlock(this)">Del</button>
    </div>
    <textarea class="block-content" rows="4" placeholder="Enter block content..."
              oninput="estimateTokens(this)"></textarea>`;
}

function addBlock() {
    const list = document.getElementById('block-list');
    blockIndex++;
    const div = document.createElement('div');
    div.className = 'block-entry';
    div.dataset.index = blockIndex;
    div.innerHTML = _blockTemplate(blockIndex);
    list.appendChild(div);
}

function removeBlock(btn) {
    const entry = btn.closest('.block-entry');
    const list = document.getElementById('block-list');
    if (list.children.length > 1) entry.remove();
}

function duplicateBlock(btn) {
    const entry = btn.closest('.block-entry');
    const content = entry.querySelector('.block-content').value;
    const priority = entry.querySelector('.block-priority').value;
    const hint = entry.querySelector('.block-hint').value;

    blockIndex++;
    const div = document.createElement('div');
    div.className = 'block-entry';
    div.dataset.index = blockIndex;
    div.innerHTML = _blockTemplate(blockIndex);

    div.querySelector('.block-content').value = content;
    div.querySelector('.block-priority').value = priority;
    div.querySelector('.block-hint').value = hint;

    entry.parentElement.insertBefore(div, entry.nextSibling);
    estimateTokens(div.querySelector('.block-content'));
}

async function testCompressBlock(btn) {
    const entry = btn.closest('.block-entry');
    const content = entry.querySelector('.block-content').value.trim();
    const hint = entry.querySelector('.block-hint').value;

    if (!content) return;
    if (!hint) { alert('Select a compression hint first.'); return; }

    const tid = showToast('Compressing block', hint);
    try {
        const res = await fetch('/api/test-compress', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content, compress_hint: hint})
        });
        const d = await res.json();
        if (d.error) { completeToast(tid, d.error, true); return; }

        completeToast(tid, `${d.original_tokens} → ${d.compressed_tokens} tokens (-${d.savings_pct}%)`, false);
        const panel = document.getElementById('compress-result');
        panel.style.display = 'block';
        document.getElementById('compress-meta').innerHTML =
            `<strong>${hint}</strong>: ${d.original_tokens} → ${d.compressed_tokens} tokens ` +
            `(<span style="color:var(--success);">-${d.savings_pct}%</span>)`;
        document.getElementById('compress-preview').textContent = d.compressed_content;
        panel.scrollIntoView({ behavior: 'smooth' });
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
}

async function runAssemble() {
    const budget = parseInt(document.getElementById('budget').value) || 4000;
    const entries = document.querySelectorAll('.block-entry');
    const blocks = [];
    entries.forEach(entry => {
        const content = entry.querySelector('.block-content').value.trim();
        if (!content) return;
        blocks.push({
            content,
            priority: entry.querySelector('.block-priority').value,
            compress_hint: entry.querySelector('.block-hint').value || null
        });
    });
    if (blocks.length === 0) return;

    const tid = showToast('Assembling context', `${blocks.length} blocks, budget ${budget}`);
    botBusy();
    try {
        const res = await fetch('/api/assemble', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({blocks, budget})
        });
        const data = await res.json();
        completeToast(tid, `${data.used_tokens}/${data.budget} tokens, ${data.block_count} blocks`, false);
        showAssemblyResult(data);
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

function showAssemblyResult(data) {
    const panel = document.getElementById('assembly-result');
    panel.style.display = 'block';
    const pct = Math.min(100, (data.used_tokens / data.budget) * 100);
    document.getElementById('budget-bar').style.width = pct + '%';
    document.getElementById('budget-label').textContent =
        `${data.used_tokens} / ${data.budget} tokens (${pct.toFixed(1)}%)`;
    document.getElementById('assembly-meta').innerHTML =
        `Assembly ID: <code>${data.assembly_id}</code> | ${data.block_count} included, ${data.dropped_count} dropped`;

    document.getElementById('assembly-blocks').innerHTML = data.blocks.map(b =>
        `<div class="result-block priority-${b.priority}">
            <div class="meta">${b.priority.toUpperCase()} | ${b.token_count} tokens${b.compress_hint ? ' | ' + b.compress_hint : ''}</div>
            <pre>${escapeHtml(b.content)}</pre>
        </div>`
    ).join('');

    let droppedHtml = '';
    if (data.dropped.length > 0) {
        droppedHtml = '<h3 style="font-size:14px;margin:12px 0 8px;">Dropped Blocks</h3>' + data.dropped.map(b =>
            `<div class="result-block dropped">
                <div class="meta">${b.priority.toUpperCase()} | ${b.token_count} tokens (dropped)</div>
                <pre>${escapeHtml(b.content)}</pre>
            </div>`
        ).join('');
    }
    document.getElementById('assembly-dropped').innerHTML = droppedHtml;
}

// ═══════════════════════════════════════════════════════════════
// KNOWLEDGE GRAPH
// ═══════════════════════════════════════════════════════════════

async function loadGraph() {
    try {
        const res = await fetch('/api/knowledge-graph');
        const data = await res.json();
        renderGraph(data);
    } catch (e) { console.error('Graph load failed:', e); }
}

function renderGraph(data) {
    graphDataCache = data;
    const container = document.getElementById('graph-container');

    const nodes = new vis.DataSet(data.nodes.map(n => ({
        id: n.id, label: n.label, group: n.group,
        title: n.title, value: n.value,
        font: { color: 'var(--text)', size: 11 }, shape: 'dot',
    })));
    const edges = new vis.DataSet(data.edges);

    const options = {
        groups: data.groups,
        physics: {
            enabled: true, solver: 'forceAtlas2Based',
            forceAtlas2Based: {
                gravitationalConstant: -40, centralGravity: 0.008,
                springLength: 120, springConstant: 0.02,
                damping: 0.5, avoidOverlap: 0.3,
            },
            stabilization: { iterations: 200, fit: true },
        },
        interaction: { hover: true, tooltipDelay: 100, keyboard: { enabled: true }, zoomView: true },
        nodes: { scaling: { min: 8, max: 40 }, borderWidth: 2, shadow: { enabled: true, size: 6, color: 'rgba(0,0,0,0.1)' } },
        edges: { smooth: { type: 'continuous' }, color: { color: '#c4c4be', highlight: '#c4703f' } },
    };

    graphNodesDataSet = nodes;
    graphNetwork = new vis.Network(container, { nodes, edges }, options);

    graphNetwork.on('click', function(params) {
        const detail = document.getElementById('graph-detail');
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const node = data.nodes.find(n => n.id === nodeId);
            if (node) {
                detail.style.display = 'block';
                const tagHtml = node.tags.length
                    ? node.tags.map(t => `<span class="badge" style="background:var(--surface-alt);color:var(--text-secondary);">${escapeHtml(t)}</span>`).join(' ')
                    : '<span class="muted">none</span>';
                detail.innerHTML = `
                    <div style="font-weight:600;font-size:14px;margin-bottom:6px;">${escapeHtml(node.id)}</div>
                    <div style="color:var(--text-secondary);margin-bottom:8px;">Group: ${escapeHtml(node.group)}</div>
                    <div style="margin-bottom:8px;">Tags: ${tagHtml}</div>
                    <button class="btn btn-small" onclick="fetchMemoryDetail('${escapeAttr(node.id)}')">Load content</button>
                    <div id="graph-memory-content" style="margin-top:8px;"></div>`;
            }
        } else {
            detail.style.display = 'none';
        }
    });

    document.getElementById('graph-stats').textContent =
        `${data.stats.total_memories} memories | ${data.stats.total_groups} groups | ${data.stats.total_edges} edges`;

    const legend = document.getElementById('graph-legend');
    legend.innerHTML = '<div style="font-weight:600;margin-bottom:4px;">Groups</div>' +
        Object.entries(data.groups).map(([name, cfg]) => {
            const count = data.nodes.filter(n => n.group === name).length;
            return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
                <span style="width:10px;height:10px;border-radius:50%;background:${cfg.color.background};display:inline-block;flex-shrink:0;"></span>
                <span>${escapeHtml(name)} (${count})</span></div>`;
        }).join('');
}

async function fetchMemoryDetail(key) {
    const el = document.getElementById('graph-memory-content');
    try {
        const res = await fetch(memoryUrl(key));
        const m = await res.json();
        const preview = m.value.length > 500 ? m.value.substring(0, 500) + '...' : m.value;
        el.innerHTML = `<pre style="white-space:pre-wrap;font-size:11px;max-height:200px;overflow-y:auto;background:var(--surface-alt);padding:8px;border-radius:6px;">${escapeHtml(preview)}</pre>`;
    } catch (e) {
        el.innerHTML = '<span style="color:var(--danger);">Error</span>';
    }
}

function searchGraph() {
    if (!graphNetwork || !graphNodesDataSet || !graphDataCache) return;
    const q = document.getElementById('graph-search').value.trim().toLowerCase();
    const countEl = document.getElementById('graph-search-count');

    if (!q) {
        graphNodesDataSet.update(graphDataCache.nodes.map(n => ({
            id: n.id, opacity: 1.0, font: { color: '#1a1a1a', size: 11 },
        })));
        countEl.textContent = '';
        return;
    }

    let matchCount = 0;
    graphNodesDataSet.update(graphDataCache.nodes.map(n => {
        const hay = (n.id + ' ' + n.label + ' ' + (n.tags || []).join(' ')).toLowerCase();
        const isMatch = hay.includes(q);
        if (isMatch) matchCount++;
        return { id: n.id, opacity: isMatch ? 1.0 : 0.15, font: { color: isMatch ? '#1a1a1a' : '#c4c4be', size: isMatch ? 13 : 9 } };
    }));
    countEl.textContent = matchCount + ' matches';

    const first = graphDataCache.nodes.find(n =>
        (n.id + ' ' + n.label + ' ' + (n.tags || []).join(' ')).toLowerCase().includes(q));
    if (first) graphNetwork.focus(first.id, { scale: 1.2, animation: true });
}

function togglePhysics() {
    if (graphNetwork) graphNetwork.setOptions({ physics: { enabled: document.getElementById('graph-physics').checked } });
}

function graphFitAll() {
    if (graphNetwork) graphNetwork.fit({ animation: true });
}

async function detectDependencies() {
    const tid = showToast('Detecting dependencies', 'Analyzing memories...');
    try {
        const res = await fetch('/api/dependencies/detect', { method: 'POST' });
        if (res.ok) {
            const d = await res.json();
            completeToast(tid, `${d.added} dependencies detected`, false);
            loadGraph();
        } else {
            completeToast(tid, 'Detection failed', true);
        }
    } catch (e) {
        completeToast(tid, 'Error: ' + e.message, true);
    }
}

// ═══════════════════════════════════════════════════════════════
// IMPORT
// ═══════════════════════════════════════════════════════════════

async function importFile(input, type) {
    const file = input.files[0];
    if (!file) return;
    const statusEl = document.getElementById('import-status');
    statusEl.textContent = 'Importing...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`/api/import/${type}`, { method: 'POST', body: formData });
        const d = await res.json();
        if (d.status === 'imported') {
            statusEl.textContent = `${d.count} memories imported from ${d.filename}`;
            loadDashboard();
        } else {
            statusEl.textContent = d.message || 'Import failed';
        }
    } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
    }
    input.value = '';
}

// ═══════════════════════════════════════════════════════════════
// PROFILES
// ═══════════════════════════════════════════════════════════════

async function loadProfiles() {
    try {
        const res = await fetch('/api/profiles');
        const d = await res.json();
        const sel = document.getElementById('profile-select');
        sel.innerHTML = '';
        d.profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = `${p.name} (${p.memory_count})`;
            if (p.is_active) opt.selected = true;
            sel.appendChild(opt);
        });
        const active = d.profiles.find(p => p.is_active);
        const notDefault = active && !active.is_default;
        document.getElementById('profile-delete-btn').style.display = notDefault ? '' : 'none';
        document.getElementById('profile-rename-btn').style.display = notDefault ? '' : 'none';
        document.getElementById('profile-import-btn').style.display = d.profiles.length > 1 ? '' : 'none';
        document.getElementById('profile-export-btn').style.display = '';
    } catch (e) { console.error(e); }
}

async function switchProfile() {
    const pid = document.getElementById('profile-select').value;
    const tid = showToast('Switching profile', 'Loading...');
    try {
        await fetch(`/api/profiles/${encodeURIComponent(pid)}/switch`, { method: 'POST' });
        completeToast(tid, 'Switched', false);
        loadProfiles();
        const activeTab = document.querySelector('.tab.active');
        if (activeTab) showTab(activeTab.dataset.tab, activeTab);
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function showNewProfileDialog() {
    let profiles = [];
    try {
        const res = await fetch('/api/profiles');
        const d = await res.json();
        profiles = d.profiles;
    } catch (e) { console.error(e); }

    const profileOpts = profiles.map(p =>
        `<option value="${escapeAttr(p.id)}">${escapeHtml(p.name)} (${p.memory_count})</option>`
    ).join('');

    openModal('Create New Profile', `
        <label>Name</label>
        <input type="text" id="new-profile-name" placeholder="Alphanumeric, -, _">
        <label>Description</label>
        <input type="text" id="new-profile-desc" placeholder="Optional">
        <label style="margin-top:12px;">Copy knowledge from</label>
        <select id="new-profile-source" onchange="toggleCopyTags()" style="width:100%;">
            <option value="">— Empty profile —</option>
            ${profileOpts}
        </select>
        <div id="copy-tags-section" style="display:none;margin-top:12px;">
            <label>Filter by tags (empty = all)</label>
            <input type="text" id="new-profile-tags" placeholder="e.g. smarthome, network">
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Comma-separated. Click tags below to add them.</div>
            <div id="available-tags" style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;"></div>
        </div>
    `, `
        <button class="btn btn-primary" id="create-profile-btn">Create</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);

    document.getElementById('create-profile-btn').addEventListener('click', submitNewProfile);
}

function toggleCopyTags() {
    const source = document.getElementById('new-profile-source').value;
    const section = document.getElementById('copy-tags-section');
    section.style.display = source ? '' : 'none';
    if (source) loadSourceTags(source);
}

async function loadSourceTags(profileName) {
    const container = document.getElementById('available-tags');
    container.innerHTML = '';

    try {
        const res = await fetch('/api/profiles');
        const d = await res.json();

        if (profileName === d.active) {
            const tagRes = await fetch('/api/memory-tags');
            const tags = await tagRes.json();
            if (tags.length > 0) {
                container.innerHTML = tags.map(t =>
                    `<span class="tag" onclick="addTagToInput('${escapeAttr(t)}')" style="cursor:pointer;">#${escapeHtml(t)}</span>`
                ).join(' ');
            }
        } else {
            container.innerHTML = '<span class="muted">Tags available after switching to this profile</span>';
        }
    } catch (e) {}
}

function addTagToInput(tag) {
    const input = document.getElementById('new-profile-tags');
    const current = input.value.split(',').map(t => t.trim()).filter(Boolean);
    if (!current.includes(tag)) {
        current.push(tag);
        input.value = current.join(', ');
    }
}

async function submitNewProfile() {
    const name = document.getElementById('new-profile-name').value.trim();
    if (!name) { alert('Name is required.'); return; }

    const description = document.getElementById('new-profile-desc').value.trim();
    const copyFrom = document.getElementById('new-profile-source').value;
    const tagsStr = document.getElementById('new-profile-tags')?.value || '';
    const copyTags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

    const body = { name, description };
    if (copyFrom) {
        body.copy_from = copyFrom;
        if (copyTags.length > 0) body.copy_tags = copyTags;
    }

    try {
        const res = await fetch('/api/profiles', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        if (res.ok) {
            const d = await res.json();
            closeModal();
            loadProfiles();
            if (d.imported > 0) {
                document.getElementById('import-status').textContent = `Profile "${name}" created, ${d.imported} memories imported.`;
            } else {
                showWelcomeForNewProfile(name);
            }
        } else {
            const d = await res.json();
            alert(d.detail || 'Failed to create profile');
        }
    } catch (e) { alert('Error: ' + e.message); }
}

async function renameActiveProfile() {
    const pid = document.getElementById('profile-select').value;
    const sel = document.getElementById('profile-select');
    const currentName = sel.options[sel.selectedIndex]?.textContent.replace(/\s*\(\d+\)$/, '') || '';
    const newName = prompt('New name:', currentName);
    if (!newName || newName === currentName) return;
    const desc = prompt('Description (optional):', '') || '';
    try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(pid)}?new_name=${encodeURIComponent(newName)}&description=${encodeURIComponent(desc)}`, { method: 'PUT' });
        if (res.ok) {
            loadProfiles();
        } else {
            const d = await res.json();
            alert(d.detail || 'Error');
        }
    } catch (e) { console.error(e); }
}

async function deleteActiveProfile() {
    const pid = document.getElementById('profile-select').value;
    const sel = document.getElementById('profile-select');
    const name = sel.options[sel.selectedIndex]?.textContent.replace(/\s*\(\d+\)$/, '') || pid;
    if (!confirm(`Delete profile "${name}"? All memories will be lost!`)) return;
    try {
        await fetch(`/api/profiles/${encodeURIComponent(pid)}`, { method: 'DELETE' });
        loadProfiles();
        loadDashboard();
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// PROFILE EXPORT / IMPORT ZIP
// ═══════════════════════════════════════════════════════════════

async function exportActiveProfile() {
    const pid = document.getElementById('profile-select').value;
    const tid = showToast('Exporting profile', 'Creating ZIP...');
    try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(pid)}/export`);
        if (!res.ok) throw new Error('Export failed');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = res.headers.get('Content-Disposition')?.match(/filename="(.+)"/)?.[1] || 'profile.zip';
        a.click();
        URL.revokeObjectURL(url);
        completeToast(tid, 'Download started', false);
    } catch (e) {
        completeToast(tid, 'Export failed: ' + e.message, true);
    }
}

async function importProfileZip(input) {
    const file = input.files[0];
    if (!file) return;
    input.value = '';

    const tid = showToast('Importing profile', `Uploading ${file.name}...`);
    try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch('/api/profiles/import-zip', { method: 'POST', body: form });
        if (res.ok) {
            const d = await res.json();
            completeToast(tid, `Profile "${d.name}" imported`, false);
            loadProfiles();
        } else {
            const d = await res.json();
            completeToast(tid, d.detail || 'Import failed', true);
        }
    } catch (e) {
        completeToast(tid, 'Error: ' + e.message, true);
    }
}

// ═══════════════════════════════════════════════════════════════
// IMPORT MEMORIES FROM ANOTHER PROFILE
// ═══════════════════════════════════════════════════════════════

async function showImportMemoriesDialog() {
    let profiles = [];
    try {
        const res = await fetch('/api/profiles');
        const d = await res.json();
        profiles = d.profiles.filter(p => !p.is_active);
    } catch (e) { console.error(e); return; }

    if (profiles.length === 0) {
        alert('No other profiles available to import from.');
        return;
    }

    const profileOpts = profiles.map(p =>
        `<option value="${escapeAttr(p.id)}">${escapeHtml(p.name)} (${p.memory_count})</option>`
    ).join('');

    openModal('Import Memories', `
        <label>Source profile</label>
        <select id="import-source-profile" onchange="loadImportTags()" style="width:100%;">
            ${profileOpts}
        </select>
        <div id="import-tags-section" style="margin-top:12px;">
            <label>Filter by tags (empty = all)</label>
            <input type="text" id="import-tags-input" placeholder="e.g. smarthome, network" oninput="updateImportPreview()">
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Comma-separated. Click tags below to add them.</div>
            <div id="import-available-tags" style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;"></div>
        </div>
        <div id="import-preview" style="margin-top:12px;padding:8px;background:var(--bg-secondary);border-radius:6px;font-size:13px;color:var(--text-muted);">
            Select a source profile to see preview...
        </div>
        <div id="import-conflict-section" style="display:none;margin-top:12px;">
            <label>Conflict resolution</label>
            <div style="display:flex;flex-direction:column;gap:6px;margin-top:4px;">
                <label style="font-size:13px;font-weight:normal;cursor:pointer;">
                    <input type="radio" name="conflict-resolution" value="skip" checked> Skip duplicates
                </label>
                <label style="font-size:13px;font-weight:normal;cursor:pointer;">
                    <input type="radio" name="conflict-resolution" value="overwrite"> Overwrite with source version
                </label>
                <label style="font-size:13px;font-weight:normal;cursor:pointer;">
                    <input type="radio" name="conflict-resolution" value="keep_both"> Keep both (suffix _imported)
                </label>
            </div>
            <div id="import-conflict-list" style="margin-top:8px;max-height:150px;overflow-y:auto;font-size:12px;"></div>
        </div>
    `, `
        <button class="btn btn-primary" id="import-memories-btn">Import</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);

    document.getElementById('import-memories-btn').addEventListener('click', submitImportMemories);
    loadImportTags();
}

async function loadImportTags() {
    const pid = document.getElementById('import-source-profile').value;
    const container = document.getElementById('import-available-tags');
    container.innerHTML = '';

    try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(pid)}/tags`);
        const tags = await res.json();
        if (tags.length > 0) {
            container.innerHTML = tags.map(t =>
                `<span class="tag" onclick="addImportTag('${escapeAttr(t)}')" style="cursor:pointer;">#${escapeHtml(t)}</span>`
            ).join(' ');
        } else {
            container.innerHTML = '<span class="muted">No tags in this profile</span>';
        }
    } catch (e) {
        container.innerHTML = '<span class="muted">Error loading tags</span>';
    }

    updateImportPreview();
}

function addImportTag(tag) {
    const input = document.getElementById('import-tags-input');
    const current = input.value.split(',').map(t => t.trim()).filter(Boolean);
    if (!current.includes(tag)) {
        current.push(tag);
        input.value = current.join(', ');
    }
    updateImportPreview();
}

async function updateImportPreview() {
    const sourcePid = document.getElementById('import-source-profile').value;
    const tagsStr = document.getElementById('import-tags-input').value;
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
    const preview = document.getElementById('import-preview');
    const conflictSection = document.getElementById('import-conflict-section');
    const conflictList = document.getElementById('import-conflict-list');

    const activePid = document.getElementById('profile-select').value;

    try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(activePid)}/preview-import`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_id: sourcePid, tags })
        });
        const d = await res.json();
        preview.innerHTML = `<strong>${d.new}</strong> new memories` +
            (d.conflicts > 0 ? ` &middot; <strong style="color:var(--warning)">${d.conflicts}</strong> conflicts` : '') +
            ` &middot; ${d.total} total`;

        if (d.conflicts > 0) {
            conflictSection.style.display = '';
            conflictList.innerHTML = d.conflict_keys.map(c =>
                `<div style="padding:4px 0;border-bottom:1px solid var(--border);">
                    <strong>${escapeHtml(c.key)}</strong>
                    <div style="display:flex;gap:8px;margin-top:2px;">
                        <span style="color:var(--text-muted);">Source: ${escapeHtml(c.source_preview.substring(0, 80))}...</span>
                    </div>
                </div>`
            ).join('');
        } else {
            conflictSection.style.display = 'none';
            conflictList.innerHTML = '';
        }
    } catch (e) {
        preview.innerHTML = 'Error loading preview';
    }
}

async function submitImportMemories() {
    const sourcePid = document.getElementById('import-source-profile').value;
    const tagsStr = document.getElementById('import-tags-input').value;
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
    const activePid = document.getElementById('profile-select').value;
    const conflictEl = document.querySelector('input[name="conflict-resolution"]:checked');
    const conflictResolution = conflictEl ? conflictEl.value : 'skip';

    const tid = showToast('Importing memories', 'Loading...');
    try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(activePid)}/import-memories`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_id: sourcePid, tags, conflict_resolution: conflictResolution })
        });
        if (res.ok) {
            const d = await res.json();
            closeModal();
            let msg = `${d.imported} imported`;
            if (d.overwritten) msg += `, ${d.overwritten} overwritten`;
            if (d.skipped) msg += `, ${d.skipped} skipped`;
            completeToast(tid, msg, false);
            loadProfiles();
            const activeTab = document.querySelector('.tab.active');
            if (activeTab) showTab(activeTab.dataset.tab, activeTab);
        } else {
            const d = await res.json();
            completeToast(tid, d.detail || 'Import failed', true);
        }
    } catch (e) {
        completeToast(tid, 'Error: ' + e.message, true);
    }
}

// ═══════════════════════════════════════════════════════════════
// SECRETS / SENSITIVITY
// ═══════════════════════════════════════════════════════════════

const SEV_BADGE_CLASS = {
    critical: 'badge-critical', high: 'badge-high', medium: 'badge-medium', low: 'badge-low',
};
const SEV_COLORS = {
    critical: 'var(--danger)', high: '#c27a1a', medium: 'var(--warning)', low: 'var(--info)', none: 'var(--text-muted)',
};

async function loadSecrets() {
    const tid = showToast('Secret scan', 'Scanning all memories...');
    try {
        const res = await fetch('/api/sensitivity');
        secretsData = await res.json();
        renderSecretsStats(secretsData);
        renderSecretsList(secretsData.memories);
        const s = secretsData.sensitive;
        completeToast(tid, s ? `${s} sensitive of ${secretsData.total}` : `${secretsData.total} memories clean`);
    } catch (e) {
        console.error(e);
        completeToast(tid, 'Scan failed', true);
    }
}

function renderSecretsStats(d) {
    document.getElementById('sec-total').textContent = d.total;
    document.getElementById('sec-sensitive').textContent = d.sensitive;
    const crit = (d.by_severity.critical || 0) + (d.by_severity.high || 0);
    document.getElementById('sec-critical').textContent = crit;
    document.getElementById('sec-clean').textContent = d.total - d.sensitive;
}

function filterSecrets() {
    if (!secretsData) return;
    const filter = document.getElementById('sec-filter').value;
    let filtered = secretsData.memories;
    if (filter === 'sensitive') filtered = filtered.filter(m => m.severity !== 'none');
    else if (filter !== 'all') filtered = filtered.filter(m => m.severity === filter);
    renderSecretsList(filtered);
}

function renderSecretsList(memories) {
    const el = document.getElementById('secrets-list');
    if (!memories.length) {
        el.innerHTML = '<p class="muted">No results</p>';
        return;
    }
    el.innerHTML = memories.map(m => {
        const color = SEV_COLORS[m.severity] || 'var(--text-muted)';
        const label = m.severity.toUpperCase();
        const badgeClass = SEV_BADGE_CLASS[m.severity] || '';
        const findingsHtml = m.findings.map(f =>
            `<span class="badge ${SEV_BADGE_CLASS[f.severity] || ''}">${f.pattern}: ${escapeHtml(f.preview)}</span>`
        ).join(' ');

        return `<div class="memory-item" style="border-left:3px solid ${color};cursor:default;">
            <div class="main">
                <div class="key">
                    <span class="badge ${badgeClass}">${label}</span>
                    ${escapeHtml(m.key)}
                </div>
                <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">${findingsHtml || '<span class="muted">no findings</span>'}</div>
            </div>
            <div class="actions">
                ${m.severity !== 'none' ? `<button class="btn btn-small" onclick="viewRedacted('${escapeAttr(m.key)}')">Redacted</button>` : ''}
            </div>
        </div>`;
    }).join('');
}

async function viewRedacted(key) {
    try {
        const res = await fetch('/api/redacted?key=' + encodeURIComponent(key));
        const d = await res.json();
        openModal('Redacted: ' + d.key, `
            <div style="margin-bottom:8px;"><span class="badge ${SEV_BADGE_CLASS[d.severity] || ''}">${d.severity.toUpperCase()}</span></div>
            <pre>${escapeHtml(d.value)}</pre>
        `, `<button class="btn" onclick="closeModal()">Close</button>`);
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// CONNECTORS (Plugin Architecture)
// ═══════════════════════════════════════════════════════════════

async function loadConnectors() {
    const el = document.getElementById('connectors-list');
    try {
        const res = await fetch('/api/connectors');
        const connectors = await res.json();
        if (connectors.length === 0) {
            el.innerHTML = '<div class="panel"><p class="muted">No connectors available.</p></div>';
            return;
        }
        el.innerHTML = connectors.map(c => renderConnectorPanel(c)).join('');
    } catch (e) { console.error(e); }
}

function renderConnectorPanel(c) {
    const lastSync = c.last_sync ? new Date(c.last_sync * 1000).toLocaleString() : 'never';
    let actions, statusHtml;

    if (!c.configured) {
        actions = `<button class="btn btn-small btn-primary" onclick="showConnectorSetup('${escapeAttr(c.name)}')">Connect</button>`;
        statusHtml = `<div class="empty-state">Not connected. Click "Connect" to set up.</div>`;
    } else {
        const statusClass = c.enabled ? 'success' : 'danger';
        const statusLabel = c.enabled ? 'connected' : 'disabled';

        // Build config summary from non-password fields
        const summary = c.schema
            .filter(f => f.type !== 'password' && c.config[f.name])
            .map(f => `<span class="age">${escapeHtml(f.label)}: ${escapeHtml(String(c.config[f.name]))}</span>`)
            .join('');

        actions = `
            <button class="btn btn-small btn-primary" onclick="syncConnector('${escapeAttr(c.name)}')">Sync</button>
            <button class="btn btn-small" onclick="testConnector('${escapeAttr(c.name)}')">Test</button>
            <button class="btn btn-small" onclick="showConnectorSetup('${escapeAttr(c.name)}')">Settings</button>
            <button class="btn btn-small btn-danger" onclick="removeConnector('${escapeAttr(c.name)}')">Disconnect</button>
        `;

        statusHtml = `<div class="memory-item" style="cursor:default;">
            <div class="main">
                <div class="key">
                    <span class="badge" style="background:var(--${statusClass}-light);color:var(--${statusClass});">${statusLabel}</span>
                    ${escapeHtml(c.display_name)}
                </div>
                <div class="meta">
                    <span class="age">${c.synced_count} items synced</span>
                    <span class="age">last sync: ${lastSync}</span>
                    ${summary}
                </div>
            </div>
        </div>`;
    }

    return `<div class="panel">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <h2>${escapeHtml(c.display_name)}</h2>
            <div style="display:flex;gap:8px;">${actions}</div>
        </div>
        <p class="muted" style="margin-bottom:12px;">${escapeHtml(c.description)}</p>
        ${statusHtml}
    </div>`;
}

function showConnectorSetup(name) {
    if (name === 'email') { showEmailSetup(); return; }
    fetch(`/api/connectors/${encodeURIComponent(name)}`).then(r => r.json()).then(c => {
        const fields = c.schema.map(f => {
            const val = c.config[f.name] || f.default || '';
            const inputType = f.type === 'password' ? 'text' : 'text';
            const displayVal = f.type === 'password' && c.configured ? '••••••••' : escapeHtml(String(val));
            return `<label>${escapeHtml(f.label)}${f.required ? ' *' : ''}</label>
                <input type="${inputType}" id="conn-${f.name}" placeholder="${escapeHtml(f.placeholder)}" value="${displayVal}">`;
        }).join('');

        openModal(`${c.display_name} Setup`, fields, `
            <button class="btn btn-primary" id="conn-save-btn">Save & Test</button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        `);

        document.getElementById('conn-save-btn').addEventListener('click', () => submitConnectorSetup(name, c));
    });
}

async function submitConnectorSetup(name, connectorInfo) {
    const values = {};
    let hasPasswordPlaceholder = false;

    for (const f of connectorInfo.schema) {
        const el = document.getElementById(`conn-${f.name}`);
        if (!el) continue;
        const val = el.value.trim();

        if (f.type === 'password' && val === '••••••••') {
            hasPasswordPlaceholder = true;
            continue; // skip unchanged password
        }
        if (f.required && !val) {
            alert(`${f.label} is required.`);
            return;
        }
        values[f.name] = val;
    }

    // If only updating non-password fields
    if (hasPasswordPlaceholder && connectorInfo.configured) {
        const tid = showToast(`Updating ${name}`, 'Saving settings...');
        try {
            const res = await fetch(`/api/connectors/${encodeURIComponent(name)}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(values)
            });
            if (res.ok) { completeToast(tid, 'Settings saved', false); closeModal(); loadConnectors(); }
            else { const d = await res.json(); completeToast(tid, d.detail || 'Update failed', true); }
        } catch (e) { completeToast(tid, 'Error: ' + e.message, true); }
        return;
    }

    const tid = showToast(`Connecting ${name}`, 'Testing connection...');
    try {
        const res = await fetch(`/api/connectors/${encodeURIComponent(name)}/setup`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(values)
        });
        const d = await res.json();
        if (d.test?.ok) {
            const info = Object.entries(d.test).filter(([k]) => k !== 'ok').map(([k, v]) => `${k}: ${v}`).join(', ');
            completeToast(tid, `Connected! ${info}`, false);
            closeModal();
            loadConnectors();
        } else {
            completeToast(tid, d.test?.error || 'Connection failed', true);
        }
    } catch (e) { completeToast(tid, 'Error: ' + e.message, true); }
}

async function testConnector(name) {
    const tid = showToast(`Testing ${name}`, 'Connecting...');
    botBusy();
    try {
        const res = await fetch(`/api/connectors/${encodeURIComponent(name)}/test`, { method: 'POST' });
        const d = await res.json();
        if (d.ok) {
            const info = Object.entries(d).filter(([k]) => k !== 'ok').map(([k, v]) => `${k}: ${v}`).join(', ');
            completeToast(tid, info, false);
        } else {
            completeToast(tid, d.error || 'Unknown error', true);
        }
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

async function syncConnector(name) {
    const tid = showToast(`Syncing ${name}`, 'Connecting to source...');
    botBusy();
    try {
        const res = await fetch(`/api/connectors/${encodeURIComponent(name)}/sync`, { method: 'POST' });
        const d = await res.json();
        const summary = `+${d.added} ~${d.updated} -${d.removed} (${d.skipped} unchanged)`;
        const hasErrors = d.errors?.length > 0;
        completeToast(tid, hasErrors ? `${summary} | Errors: ${d.errors.join(', ')}` : summary, hasErrors);
        loadConnectors();
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

async function removeConnector(name) {
    if (!confirm(`Disconnect "${name}"?`)) return;
    const purge = confirm('Also delete all synced memories?');
    try {
        await fetch(`/api/connectors/${encodeURIComponent(name)}?purge=${purge}`, { method: 'DELETE' });
        loadConnectors();
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// EMAIL CONNECTOR SETUP
// ═══════════════════════════════════════════════════════════════

async function showEmailSetup() {
    let accounts = [];
    let connectorInfo = {};
    try {
        const [accRes, cRes] = await Promise.all([
            fetch('/api/connectors/email/accounts'),
            fetch('/api/connectors/email'),
        ]);
        accounts = await accRes.json();
        connectorInfo = await cRes.json();
    } catch (e) { console.error(e); }

    const maxEmails = connectorInfo.config?.max_emails || 50;
    const sinceDays = connectorInfo.config?.since_days || 30;
    const maxBody = connectorInfo.config?.max_body_length || 2000;

    const accountListHtml = accounts.length > 0
        ? accounts.map(a => `<div class="memory-item" style="cursor:default;padding:8px 12px;">
            <div class="main">
                <div class="key">${escapeHtml(a.name)}</div>
                <div class="preview">${escapeHtml(a.user)} @ ${escapeHtml(a.host)}:${a.port} | Folders: ${escapeHtml((a.folders || []).join(', '))} | Tags: ${escapeHtml((a.tags || []).join(', '))}</div>
            </div>
            <div class="actions" onclick="event.stopPropagation()">
                <button class="btn btn-small btn-danger" onclick="removeEmailAccount('${escapeAttr(a.name)}')">Del</button>
            </div>
        </div>`).join('')
        : '<p class="muted">No accounts configured. Add one below.</p>';

    openModal('Email (IMAP) Setup', `
        <label>Accounts</label>
        <div id="email-account-list" style="margin-bottom:16px;">${accountListHtml}</div>

        <div style="border:1px solid var(--border);border-radius:var(--radius);padding:12px;margin-bottom:16px;">
            <div style="font-size:12px;font-weight:600;margin-bottom:8px;">Add Account</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <div><label>Name *</label><input type="text" id="email-acc-name" placeholder="e.g. Work, Private"></div>
                <div><label>IMAP Host *</label><input type="text" id="email-acc-host" placeholder="imap.gmail.com"></div>
                <div><label>User *</label><input type="text" id="email-acc-user" placeholder="user@example.com"></div>
                <div><label>Password *</label><input type="text" id="email-acc-pass" placeholder="App password"></div>
                <div><label>Port</label><input type="number" id="email-acc-port" value="993"></div>
                <div><label>Folders (comma-sep.)</label><input type="text" id="email-acc-folders" value="INBOX" placeholder="INBOX, Sent"></div>
                <div><label>Tags (comma-sep.)</label><input type="text" id="email-acc-tags" placeholder="email, work"></div>
                <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary btn-small" id="email-add-btn" style="width:100%;">Add Account</button></div>
            </div>
        </div>

        <div style="border:1px solid var(--border);border-radius:var(--radius);padding:12px;">
            <div style="font-size:12px;font-weight:600;margin-bottom:8px;">Sync Settings</div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
                <div><label>Max emails/folder</label><input type="number" id="email-max" value="${maxEmails}"></div>
                <div><label>Since (days)</label><input type="number" id="email-days" value="${sinceDays}"></div>
                <div><label>Max body length</label><input type="number" id="email-body" value="${maxBody}"></div>
            </div>
        </div>
    `, `
        <button class="btn btn-primary" id="email-save-settings">Save Settings</button>
        <button class="btn" onclick="closeModal()">Close</button>
    `);

    document.getElementById('email-add-btn').addEventListener('click', addEmailAccount);
    document.getElementById('email-save-settings').addEventListener('click', saveEmailSettings);
}

async function addEmailAccount() {
    const name = document.getElementById('email-acc-name').value.trim();
    const host = document.getElementById('email-acc-host').value.trim();
    const user = document.getElementById('email-acc-user').value.trim();
    const password = document.getElementById('email-acc-pass').value.trim();
    if (!name || !host || !user || !password) { alert('Name, Host, User and Password are required.'); return; }

    const port = parseInt(document.getElementById('email-acc-port').value) || 993;
    const folders = document.getElementById('email-acc-folders').value.split(',').map(f => f.trim()).filter(Boolean);
    const tags = document.getElementById('email-acc-tags').value.split(',').map(t => t.trim()).filter(Boolean);

    const tid = showToast('Adding email account', name);
    try {
        const res = await fetch('/api/connectors/email/accounts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, host, port, user, password, ssl: port === 993, folders, tags })
        });
        if (res.ok) {
            const d = await res.json();
            completeToast(tid, `Added (${d.total} accounts total)`, false);
            showEmailSetup(); // reload modal
        } else {
            const d = await res.json();
            completeToast(tid, d.detail || 'Failed', true);
        }
    } catch (e) { completeToast(tid, 'Error: ' + e.message, true); }
}

async function removeEmailAccount(name) {
    if (!confirm(`Remove account "${name}"?`)) return;
    try {
        await fetch(`/api/connectors/email/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' });
        showEmailSetup(); // reload
        loadConnectors();
    } catch (e) { console.error(e); }
}

async function saveEmailSettings() {
    const values = {
        max_emails: parseInt(document.getElementById('email-max').value) || 50,
        since_days: parseInt(document.getElementById('email-days').value) || 30,
        max_body_length: parseInt(document.getElementById('email-body').value) || 2000,
    };
    try {
        await fetch('/api/connectors/email', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(values)
        });
        closeModal();
        loadConnectors();
    } catch (e) { alert('Error: ' + e.message); }
}

// ═══════════════════════════════════════════════════════════════
// FOLDER SOURCES
// ═══════════════════════════════════════════════════════════════

async function loadFolders() {
    const el = document.getElementById('folder-list');
    try {
        const res = await fetch('/api/folders');
        const folders = await res.json();
        if (folders.length === 0) {
            el.innerHTML = '<div class="empty-state">No folder sources configured. Click "+ Add Folder" to map a directory.</div>';
            return;
        }
        el.innerHTML = folders.map(f => {
            const lastScan = f.last_scan
                ? new Date(f.last_scan * 1000).toLocaleString()
                : 'never';
            const extList = f.extensions.length
                ? f.extensions.join(', ')
                : 'all supported';
            const statusClass = f.enabled ? 'green' : 'red';
            const statusText = f.enabled ? 'enabled' : 'disabled';

            return `<div class="memory-item" style="cursor:default;">
                <div class="main">
                    <div class="key">
                        <span class="badge" style="background:var(--accent-light);color:var(--accent);">${escapeHtml(f.indexed_files + '')} files</span>
                        ${escapeHtml(f.name)}
                    </div>
                    <div class="preview">${escapeHtml(f.path)}</div>
                    <div class="meta">
                        <span class="age">${extList}</span>
                        <span class="age">${f.recursive ? 'recursive' : 'top-level'}</span>
                        <span class="age">scanned: ${lastScan}</span>
                        <span class="badge" style="background:var(--${statusClass === 'green' ? 'success' : 'danger'}-light);color:var(--${statusClass === 'green' ? 'success' : 'danger'});">${statusText}</span>
                    </div>
                    ${f.description ? '<div class="preview" style="margin-top:2px;">' + escapeHtml(f.description) + '</div>' : ''}
                </div>
                <div class="actions" style="display:flex;flex-direction:column;gap:4px;">
                    <button class="btn btn-small btn-primary" onclick="scanFolder('${escapeAttr(f.name)}')">Scan</button>
                    <button class="btn btn-small" onclick="toggleFolder('${escapeAttr(f.name)}', ${!f.enabled})">${f.enabled ? 'Disable' : 'Enable'}</button>
                    <button class="btn btn-small btn-danger" onclick="removeFolder('${escapeAttr(f.name)}')">Remove</button>
                </div>
            </div>`;
        }).join('');
    } catch (e) { console.error(e); }
}

function showAddFolderDialog() {
    openModal('Add Folder Source', `
        <label>Name</label>
        <input type="text" id="folder-name" placeholder="e.g. docs, configs, notes">
        <label>Path</label>
        <input type="text" id="folder-path" placeholder="/path/to/folder">
        <label>Description</label>
        <input type="text" id="folder-desc" placeholder="Optional">
        <label>File extensions (empty = all supported)</label>
        <input type="text" id="folder-ext" placeholder="e.g. .pdf, .md, .txt">
        <div style="margin-top:8px;">
            <label style="display:inline;cursor:pointer;">
                <input type="checkbox" id="folder-recursive" checked> Scan subfolders recursively
            </label>
        </div>
    `, `
        <button class="btn btn-primary" id="add-folder-btn">Add</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);

    document.getElementById('add-folder-btn').addEventListener('click', submitAddFolder);
}

async function submitAddFolder() {
    const name = document.getElementById('folder-name').value.trim();
    const path = document.getElementById('folder-path').value.trim();
    if (!name || !path) { alert('Name and path are required.'); return; }

    const description = document.getElementById('folder-desc').value.trim();
    const extStr = document.getElementById('folder-ext').value.trim();
    const extensions = extStr ? extStr.split(',').map(e => e.trim()).filter(Boolean) : [];
    const recursive = document.getElementById('folder-recursive').checked;

    try {
        const res = await fetch('/api/folders', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, path, extensions, recursive, description })
        });
        if (res.ok) {
            closeModal();
            loadFolders();
        } else {
            const d = await res.json();
            alert(d.detail || 'Failed to add folder');
        }
    } catch (e) { alert('Error: ' + e.message); }
}

async function scanFolder(name) {
    const tid = showToast(`Scanning ${name}`, 'Reading files...');
    botBusy();
    try {
        const res = await fetch(`/api/folders/${encodeURIComponent(name)}/scan`, { method: 'POST' });
        const d = await res.json();
        const summary = `+${d.added} ~${d.updated} -${d.removed} (${d.skipped} unchanged)`;
        completeToast(tid, summary, d.errors.length > 0);
        loadFolders();
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

async function scanAllFolders() {
    const tid = showToast('Scanning all folders', 'Starting...');
    botBusy();
    try {
        const res = await fetch('/api/folders/scan-all', { method: 'POST' });
        const d = await res.json();
        const entries = Object.entries(d);
        const summary = entries.length
            ? entries.map(([n, r]) => `${n}: +${r.added} ~${r.updated} -${r.removed}`).join(' | ')
            : 'No sources configured';
        completeToast(tid, summary, false);
        loadFolders();
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

async function toggleFolder(name, enabled) {
    try {
        await fetch(`/api/folders/${encodeURIComponent(name)}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ enabled })
        });
        loadFolders();
    } catch (e) { console.error(e); }
}

async function removeFolder(name) {
    const purge = confirm(`Remove folder source "${name}"?\n\nClick OK to also delete all indexed memories, or Cancel to keep them.`);
    // If they clicked Cancel on the first confirm, they don't want to remove at all
    if (!confirm(`Remove source "${name}"?`)) return;

    try {
        await fetch(`/api/folders/${encodeURIComponent(name)}?purge=${purge}`, { method: 'DELETE' });
        loadFolders();
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// SCHEDULER
// ═══════════════════════════════════════════════════════════════

async function loadScheduler() {
    try {
        const res = await fetch('/api/scheduler');
        const d = await res.json();
        const actions = document.getElementById('scheduler-actions');
        const status = document.getElementById('scheduler-status');
        const dashVal = document.getElementById('dash-scheduler');
        const dashDetail = document.getElementById('dash-scheduler-detail');

        if (d.running) {
            actions.innerHTML = `
                <button class="btn btn-small" onclick="runSchedulerNow()">Run Now</button>
                <button class="btn btn-small btn-danger" onclick="stopScheduler()">Stop</button>`;
            status.textContent = `Running every ${d.interval_minutes} minutes` +
                (d.last_run ? ` | Last: ${new Date(d.last_run * 1000).toLocaleString()}` : '');
            if (dashVal) { dashVal.textContent = 'ON'; dashVal.className = 'card-value green'; }
            if (dashDetail) dashDetail.textContent = `every ${d.interval_minutes}m`;
        } else {
            actions.innerHTML = `
                <select id="sched-interval" style="width:auto;font-size:12px;padding:2px 8px;">
                    <option value="15">15 min</option><option value="30" selected>30 min</option>
                    <option value="60">1 hour</option><option value="360">6 hours</option>
                </select>
                <button class="btn btn-small btn-primary" onclick="startScheduler()">Start</button>`;
            status.textContent = 'Not running' + (d.last_run ? ` | Last: ${new Date(d.last_run * 1000).toLocaleString()}` : '');
            if (dashVal) { dashVal.textContent = 'OFF'; dashVal.className = 'card-value'; }
            if (dashDetail) dashDetail.textContent = 'not running';
        }
    } catch (e) { console.error(e); }
}

async function startScheduler() {
    const interval = document.getElementById('sched-interval')?.value || 30;
    await fetch(`/api/scheduler/start?interval=${interval}`, { method: 'POST' });
    loadScheduler();
}

async function stopScheduler() {
    await fetch('/api/scheduler/stop', { method: 'POST' });
    loadScheduler();
}

async function runSchedulerNow() {
    const tid = showToast('Running full sync', 'Syncing all sources...');
    botBusy();
    try {
        const res = await fetch('/api/scheduler/run-now', { method: 'POST' });
        const d = await res.json();
        const folders = Object.entries(d.folders || {}).map(([n, r]) => `${n}: +${r.added}`);
        const connectors = Object.entries(d.connectors || {}).map(([n, r]) => r.error ? `${n}: err` : `${n}: +${r.added}`);
        const all = [...folders, ...connectors];
        completeToast(tid, all.length ? all.join(' | ') : 'No sources configured', false);
        loadScheduler();
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

// ═══════════════════════════════════════════════════════════════
// TEMPLATES
// ═══════════════════════════════════════════════════════════════

async function loadTemplates() {
    const el = document.getElementById('template-list');
    if (!el) return;
    try {
        const res = await fetch('/api/templates');
        const templates = await res.json();
        if (templates.length === 0) {
            el.innerHTML = '<p class="muted">No templates. Create one to quickly assemble context.</p>';
            return;
        }
        el.innerHTML = templates.map(t => `<div class="memory-item" style="cursor:default;">
            <div class="main">
                <div class="key">${escapeHtml(t.name)}</div>
                <div class="preview">${escapeHtml(t.description || '')}</div>
                <div class="meta">
                    <span class="age">budget: ${t.budget} tokens</span>
                    <span class="age">tags: ${t.tag_filter.length ? t.tag_filter.join(', ') : 'all'}</span>
                    ${t.key_filter ? '<span class="age">prefix: ' + escapeHtml(t.key_filter) + '</span>' : ''}
                </div>
            </div>
            <div class="actions" style="display:flex;flex-direction:column;gap:4px;">
                <button class="btn btn-small btn-primary" onclick="assembleTemplate('${escapeAttr(t.name)}')">Assemble</button>
                <button class="btn btn-small" onclick="editTemplate('${escapeAttr(t.name)}')">Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteTemplate('${escapeAttr(t.name)}')">Delete</button>
            </div>
        </div>`).join('');
    } catch (e) { console.error(e); }
}

function showAddTemplate() {
    openModal('Create Context Template', `
        <label>Name</label>
        <input type="text" id="tpl-name" placeholder="e.g. smarthome, dev-context">
        <label>Description</label>
        <input type="text" id="tpl-desc" placeholder="Optional">
        <label>Tag filter (comma-separated, empty = all)</label>
        <input type="text" id="tpl-tags" placeholder="e.g. smarthome, network">
        <label>Key prefix filter (empty = all)</label>
        <input type="text" id="tpl-prefix" placeholder="e.g. folder/docs">
        <label>Token budget</label>
        <input type="number" id="tpl-budget" value="4000" min="100">
    `, `
        <button class="btn btn-primary" id="tpl-save-btn">Create</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);
    document.getElementById('tpl-save-btn').addEventListener('click', submitTemplate);
}

async function submitTemplate() {
    const name = document.getElementById('tpl-name').value.trim();
    if (!name) { alert('Name is required.'); return; }
    const body = {
        name,
        description: document.getElementById('tpl-desc').value.trim(),
        tag_filter: document.getElementById('tpl-tags').value.split(',').map(t => t.trim()).filter(Boolean),
        key_filter: document.getElementById('tpl-prefix').value.trim(),
        budget: parseInt(document.getElementById('tpl-budget').value) || 4000,
    };
    try {
        const res = await fetch('/api/templates', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        if (res.ok) { closeModal(); loadTemplates(); }
        else alert('Failed to create template');
    } catch (e) { alert('Error: ' + e.message); }
}

async function assembleTemplate(name) {
    const tid = showToast(`Assembling "${name}"`, 'Selecting memories...');
    botBusy();
    try {
        const res = await fetch(`/api/templates/${encodeURIComponent(name)}/assemble`, { method: 'POST' });
        const d = await res.json();
        completeToast(tid, `${d.used_tokens}/${d.budget} tokens, ${d.included}/${d.total_matching} memories`, false);
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

async function editTemplate(name) {
    try {
        const res = await fetch('/api/templates');
        const templates = await res.json();
        const t = templates.find(x => x.name === name);
        if (!t) return;

        openModal('Edit Template: ' + name, `
            <label>Name</label>
            <input type="text" id="tpl-name" value="${escapeHtml(t.name)}" readonly style="background:var(--surface-alt);cursor:not-allowed;">
            <label>Description</label>
            <input type="text" id="tpl-desc" value="${escapeHtml(t.description || '')}">
            <label>Tag filter (comma-separated, empty = all)</label>
            <input type="text" id="tpl-tags" value="${escapeHtml(t.tag_filter.join(', '))}">
            <label>Key prefix filter (empty = all)</label>
            <input type="text" id="tpl-prefix" value="${escapeHtml(t.key_filter || '')}">
            <label>Token budget</label>
            <input type="number" id="tpl-budget" value="${t.budget}" min="100">
        `, `
            <button class="btn btn-primary" id="tpl-save-btn">Save</button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        `);
        document.getElementById('tpl-save-btn').addEventListener('click', submitTemplate);
    } catch (e) { console.error(e); }
}

async function deleteTemplate(name) {
    if (!confirm(`Delete template "${name}"?`)) return;
    await fetch(`/api/templates/${encodeURIComponent(name)}`, { method: 'DELETE' });
    loadTemplates();
}

// ═══════════════════════════════════════════════════════════════
// EXPORT & DUPLICATES
// ═══════════════════════════════════════════════════════════════

async function exportClaudeMd() {
    const tags = document.getElementById('export-tags')?.value.trim() || '';
    const url = `/api/export-claude-md${tags ? '?tags=' + encodeURIComponent(tags) : ''}`;
    const tid = showToast('Exporting CLAUDE.md', 'Generating...');
    try {
        const res = await fetch(url);
        const d = await res.json();
        const blob = new Blob([d.content], {type: 'text/markdown'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'CLAUDE.md';
        a.click();
        completeToast(tid, `${d.memory_count} memories, ${d.token_count} tokens`, false);
        document.getElementById('export-result').innerHTML =
            `<p class="muted" style="margin-top:8px;">${d.memory_count} memories, ${d.token_count} tokens exported.</p>`;
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
}

async function findDuplicates() {
    const el = document.getElementById('duplicate-list');
    const tid = showToast('Duplicate scan', 'Comparing memories...');
    botBusy();
    try {
        const res = await fetch('/api/duplicates?threshold=0.6');
        const groups = await res.json();
        completeToast(tid, `${groups.length} duplicate groups found`, false);
        if (groups.length === 0) {
            el.innerHTML = '<p class="muted">No duplicates found.</p>';
            return;
        }
        el.innerHTML = groups.map(g => `<div class="memory-item" style="cursor:default;">
            <div class="main">
                <div class="key"><span class="badge badge-upd">${Math.round(g.similarity * 100)}%</span> ${g.keys.length} similar memories</div>
                <div class="preview">${escapeHtml(g.sample)}</div>
                <div class="meta">${g.keys.map(k => '<span class="tag">' + escapeHtml(k) + '</span>').join(' ')}</div>
            </div>
        </div>`).join('');
    } catch (e) { el.innerHTML = '<p style="color:var(--danger);">Error: ' + escapeHtml(e.message) + '</p>'; completeToast(tid, 'Failed', true); }
    finally { botIdle(); }
}

// ═══════════════════════════════════════════════════════════════
// WEBHOOKS
// ═══════════════════════════════════════════════════════════════

async function loadWebhooks() {
    const el = document.getElementById('webhook-list');
    if (!el) return;
    try {
        const res = await fetch('/api/webhooks');
        const hooks = await res.json();
        if (hooks.length === 0) {
            el.innerHTML = '<p class="muted">No webhooks configured.</p>';
            return;
        }
        el.innerHTML = hooks.map(h => `<div class="memory-item" style="cursor:default;">
            <div class="main">
                <div class="key">
                    <span class="badge" style="background:var(--accent-light);color:var(--accent);">${escapeHtml(h.type)}</span>
                    ${escapeHtml(h.name)}
                </div>
                <div class="preview">${escapeHtml(h.url)}</div>
                <div class="meta">
                    <span class="age">events: ${h.events.length ? h.events.join(', ') : 'all'}</span>
                    ${h.chat_id ? '<span class="age">chat: ' + escapeHtml(h.chat_id) + '</span>' : ''}
                </div>
            </div>
            <div class="actions">
                <button class="btn btn-small btn-danger" onclick="removeWebhook('${escapeAttr(h.name)}')">Remove</button>
            </div>
        </div>`).join('');
    } catch (e) { console.error(e); }
}

function showAddWebhook() {
    openModal('Add Webhook', `
        <label>Name</label>
        <input type="text" id="wh-name" placeholder="e.g. whatsapp-alerts">
        <label>Type</label>
        <select id="wh-type" style="width:100%;">
            <option value="waha">WAHA (WhatsApp)</option>
            <option value="generic">Generic HTTP</option>
        </select>
        <label>URL</label>
        <input type="text" id="wh-url" placeholder="http://<server-ip>:3033">
        <label>Chat ID (WAHA only)</label>
        <input type="text" id="wh-chat" placeholder="491234567890@c.us">
        <label>Events (comma-separated, empty = all)</label>
        <input type="text" id="wh-events" placeholder="e.g. secrets.found, sync.error">
    `, `
        <button class="btn btn-primary" id="wh-save-btn">Add</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);
    document.getElementById('wh-save-btn').addEventListener('click', submitWebhook);
}

async function submitWebhook() {
    const name = document.getElementById('wh-name').value.trim();
    const url = document.getElementById('wh-url').value.trim();
    if (!name || !url) { alert('Name and URL are required.'); return; }
    const body = {
        name, url,
        type: document.getElementById('wh-type').value,
        chat_id: document.getElementById('wh-chat').value.trim(),
        events: document.getElementById('wh-events').value.split(',').map(e => e.trim()).filter(Boolean),
    };
    try {
        const res = await fetch('/api/webhooks', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        if (res.ok) { closeModal(); loadWebhooks(); }
        else alert('Failed');
    } catch (e) { alert('Error: ' + e.message); }
}

async function removeWebhook(name) {
    if (!confirm(`Remove webhook "${name}"?`)) return;
    await fetch(`/api/webhooks/${encodeURIComponent(name)}`, { method: 'DELETE' });
    loadWebhooks();
}

// ═══════════════════════════════════════════════════════════════
// VERSION HISTORY & DIFF VIEW
// ═══════════════════════════════════════════════════════════════

async function showVersions(key) {
    try {
        const [memRes, verRes] = await Promise.all([
            fetch(memoryUrl(key)),
            fetch(`/api/memories/${encodeURIComponent(key)}/versions`)
        ]);
        const current = await memRes.json();
        const versions = await verRes.json();

        if (versions.length === 0) {
            openModal('History: ' + key, '<p class="muted">No version history available.</p>',
                `<button class="btn" onclick="viewMemory('${escapeAttr(key)}')">Back</button>`);
            return;
        }

        const versionList = versions.map((v, i) => {
            const date = new Date(v.created_at * 1000).toLocaleString();
            const preview = (v.value || '').substring(0, 80);
            return `<div class="version-item" onclick="showDiff('${escapeAttr(key)}', ${i})" id="ver-${i}">
                <div style="display:flex;justify-content:space-between;">
                    <span style="font-weight:600;font-size:12px;">v${versions.length - i}</span>
                    <span class="version-meta">${escapeHtml(date)}${v.changed_by ? ' by ' + escapeHtml(v.changed_by) : ''}</span>
                </div>
                <div class="version-preview">${escapeHtml(preview)}</div>
            </div>`;
        }).join('');

        openModal('History: ' + key, `
            <div style="display:grid;grid-template-columns:1fr 1.5fr;gap:16px;min-height:300px;">
                <div>
                    <label>Versions (click to compare with current)</label>
                    <div style="max-height:400px;overflow-y:auto;">${versionList}</div>
                </div>
                <div>
                    <label>Diff</label>
                    <div id="diff-output" class="diff-container">
                        <div class="diff-header">Select a version to see changes</div>
                    </div>
                </div>
            </div>
        `, `<button class="btn" onclick="viewMemory('${escapeAttr(key)}')">Back</button>`);

        // Store data for diff
        window._versionData = { current, versions };
    } catch (e) { console.error(e); }
}

function showDiff(key, versionIndex) {
    const { current, versions } = window._versionData;
    const old = versions[versionIndex];

    // Highlight selected
    document.querySelectorAll('.version-item').forEach(el => el.classList.remove('selected'));
    document.getElementById('ver-' + versionIndex)?.classList.add('selected');

    const oldLines = (old.value || '').split('\n');
    const newLines = (current.value || '').split('\n');
    const diff = computeDiff(oldLines, newLines);

    const date = new Date(old.created_at * 1000).toLocaleString();
    const header = `v${versions.length - versionIndex} (${date}) → current`;

    const diffEl = document.getElementById('diff-output');
    diffEl.innerHTML = `<div class="diff-header">${escapeHtml(header)}</div>` +
        diff.map(line => {
            if (line.startsWith('+')) return `<div class="diff-line diff-add">${escapeHtml(line)}</div>`;
            if (line.startsWith('-')) return `<div class="diff-line diff-del">${escapeHtml(line)}</div>`;
            return `<div class="diff-line diff-ctx">${escapeHtml(line)}</div>`;
        }).join('');
}

function computeDiff(oldLines, newLines) {
    // Simple line-based diff (LCS approach)
    const m = oldLines.length, n = newLines.length;
    // For very large texts, fall back to simple comparison
    if (m + n > 2000) {
        const result = [];
        oldLines.forEach(l => result.push('- ' + l));
        newLines.forEach(l => result.push('+ ' + l));
        return result;
    }

    // Build LCS table
    const dp = Array(m + 1).fill(null).map(() => Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            dp[i][j] = oldLines[i-1] === newLines[j-1]
                ? dp[i-1][j-1] + 1
                : Math.max(dp[i-1][j], dp[i][j-1]);
        }
    }

    // Backtrack
    const result = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && oldLines[i-1] === newLines[j-1]) {
            result.unshift('  ' + oldLines[i-1]);
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
            result.unshift('+ ' + newLines[j-1]);
            j--;
        } else {
            result.unshift('- ' + oldLines[i-1]);
            i--;
        }
    }
    return result;
}

// ═══════════════════════════════════════════════════════════════
// MARKDOWN EXPORT
// ═══════════════════════════════════════════════════════════════

async function exportMarkdown() {
    const tags = document.getElementById('export-tags').value.trim();
    const tid = showToast('Exporting Markdown', 'Generating...');
    try {
        let url = '/api/export-markdown';
        if (tags) url += '?tags=' + encodeURIComponent(tags);
        const res = await fetch(url);
        const d = await res.json();
        const blob = new Blob([d.content], { type: 'text/markdown' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'context-pilot-export.md';
        a.click();
        URL.revokeObjectURL(a.href);
        completeToast(tid, `${d.memory_count} memories, ${d.token_count} tokens`, false);
    } catch (e) {
        completeToast(tid, 'Failed: ' + e.message, true);
    }
}

// ═══════════════════════════════════════════════════════════════
// PINNING
// ═══════════════════════════════════════════════════════════════

async function togglePin(key, pinned) {
    try {
        await fetch(`/api/memories/${encodeURIComponent(key)}/pin?pinned=${pinned}`, { method: 'POST' });
        loadMemories();
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// TRASH
// ═══════════════════════════════════════════════════════════════

async function showTrash() {
    try {
        const res = await fetch('/api/trash');
        const items = await res.json();

        if (items.length === 0) {
            openModal('Trash', '<p class="muted">Trash is empty.</p>',
                '<button class="btn" onclick="closeModal()">Close</button>');
            return;
        }

        const listHtml = items.map(m => {
            const date = new Date(m.deleted_at * 1000).toLocaleString();
            return `<div class="memory-item trash-item" style="cursor:default;">
                <div class="main">
                    <div class="key">${escapeHtml(m.key)}</div>
                    <div class="preview">${escapeHtml((m.value || '').substring(0, 100))}</div>
                    <div class="meta"><span class="age">deleted ${date}</span></div>
                </div>
                <div class="actions" style="display:flex;gap:4px;">
                    <button class="btn btn-small" onclick="restoreFromTrash('${escapeAttr(m.key)}')">Restore</button>
                    <button class="btn btn-small btn-danger" onclick="purgeFromTrash('${escapeAttr(m.key)}')">Purge</button>
                </div>
            </div>`;
        }).join('');

        openModal('Trash', `
            <div style="margin-bottom:8px;font-size:12px;color:var(--text-muted);">${items.length} items in trash</div>
            <div style="max-height:50vh;overflow-y:auto;">${listHtml}</div>
        `, `
            <button class="btn btn-danger" onclick="emptyTrash()">Empty Trash</button>
            <button class="btn" onclick="closeModal()">Close</button>
        `);
    } catch (e) { console.error(e); }
}

async function restoreFromTrash(key) {
    try {
        await fetch(`/api/trash/${encodeURIComponent(key)}/restore`, { method: 'POST' });
        showTrash();
        loadMemories();
    } catch (e) { console.error(e); }
}

async function purgeFromTrash(key) {
    if (!confirm(`Permanently delete "${key}"?`)) return;
    try {
        await fetch(`/api/trash/${encodeURIComponent(key)}`, { method: 'DELETE' });
        showTrash();
    } catch (e) { console.error(e); }
}

async function emptyTrash() {
    if (!confirm('Permanently delete all items in trash?')) return;
    try {
        await fetch('/api/trash', { method: 'DELETE' });
        closeModal();
    } catch (e) { console.error(e); }
}

// ═══════════════════════════════════════════════════════════════
// BULK TAG OPERATIONS
// ═══════════════════════════════════════════════════════════════

function showBulkTagDialog() {
    const checked = document.querySelectorAll('.bulk-cb:checked');
    if (checked.length === 0) { alert('No memories selected.'); return; }
    const keys = Array.from(checked).map(cb => cb.dataset.key);

    openModal(`Tag ${keys.length} memories`, `
        <label>Add tags (comma-separated)</label>
        <input type="text" id="bulk-add-tags" placeholder="e.g. important, reviewed">
        <label>Remove tags (comma-separated)</label>
        <input type="text" id="bulk-remove-tags" placeholder="e.g. draft, temp">
    `, `
        <button class="btn btn-primary" id="bulk-tag-submit">Apply</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);
    document.getElementById('bulk-tag-submit').addEventListener('click', () => submitBulkTags(keys));
}

async function submitBulkTags(keys) {
    const addTags = document.getElementById('bulk-add-tags').value.split(',').map(t => t.trim()).filter(Boolean);
    const removeTags = document.getElementById('bulk-remove-tags').value.split(',').map(t => t.trim()).filter(Boolean);
    if (addTags.length === 0 && removeTags.length === 0) { alert('Enter tags to add or remove.'); return; }

    const tid = showToast('Bulk tagging', `${keys.length} memories...`);
    try {
        const res = await fetch('/api/memories/bulk-tags', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ keys, add: addTags, remove: removeTags })
        });
        const d = await res.json();
        completeToast(tid, `${d.updated} updated`, false);
        closeModal();
        loadMemories();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

// ═══════════════════════════════════════════════════════════════
// MEMORY PRESETS
// ═══════════════════════════════════════════════════════════════

function renderPresets(presets) {
    const el = document.getElementById('memory-presets');
    if (!el) return;
    if (presets.length === 0) { el.style.display = 'none'; return; }
    el.style.display = 'flex';
    el.innerHTML = presets.map(p =>
        `<span class="preset-chip" onclick="applyPreset('${escapeAttr(p.name)}', '${escapeAttr(p.key_prefix)}', '${escapeAttr(p.default_tags.join(', '))}')">
            ${escapeHtml(p.name)}
        </span>`
    ).join('') + ' <span class="preset-chip" onclick="showPresetManager()" style="color:var(--accent);">+ Manage</span>';
}

function applyPreset(name, prefix, tags) {
    const keyEl = document.getElementById('memory-key');
    const tagEl = document.getElementById('memory-tags');
    if (prefix && keyEl) keyEl.value = prefix;
    if (tags && tagEl) tagEl.value = tags;
    keyEl?.focus();
}

async function showPresetManager() {
    try {
        const res = await fetch('/api/memory-presets');
        const presets = await res.json();
        const listHtml = presets.map(p => `<div class="memory-item" style="cursor:default;">
            <div class="main">
                <div class="key">${escapeHtml(p.name)}</div>
                <div class="preview">prefix: ${escapeHtml(p.key_prefix || '-')} | tags: ${escapeHtml(p.default_tags.join(', ') || '-')}</div>
            </div>
            <div class="actions">
                <button class="btn btn-small btn-danger" onclick="deletePreset('${escapeAttr(p.name)}')">Del</button>
            </div>
        </div>`).join('') || '<p class="muted">No presets. Create one below.</p>';

        openModal('Memory Presets', `
            <div style="max-height:200px;overflow-y:auto;margin-bottom:16px;">${listHtml}</div>
            <label>New Preset Name</label>
            <input type="text" id="preset-name" placeholder="e.g. Device, Script, Password">
            <label>Key Prefix</label>
            <input type="text" id="preset-prefix" placeholder="e.g. devices/, scripts/">
            <label>Default Tags (comma-separated)</label>
            <input type="text" id="preset-tags" placeholder="e.g. smarthome, config">
        `, `
            <button class="btn btn-primary" id="preset-save-btn">Save</button>
            <button class="btn" onclick="closeModal()">Close</button>
        `);
        document.getElementById('preset-save-btn').addEventListener('click', savePreset);
    } catch (e) { console.error(e); }
}

async function savePreset() {
    const name = document.getElementById('preset-name').value.trim();
    if (!name) { alert('Name required.'); return; }
    const body = {
        name,
        key_prefix: document.getElementById('preset-prefix').value.trim(),
        default_tags: document.getElementById('preset-tags').value.split(',').map(t => t.trim()).filter(Boolean),
    };
    try {
        await fetch('/api/memory-presets', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
        closeModal();
        loadMemories();
    } catch (e) { alert('Error: ' + e.message); }
}

async function deletePreset(name) {
    await fetch(`/api/memory-presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
    showPresetManager();
}

// ═══════════════════════════════════════════════════════════════
// GLOBAL SEARCH
// ═══════════════════════════════════════════════════════════════

function openGlobalSearch() {
    const overlay = document.getElementById('global-search-overlay');
    overlay.classList.add('active');
    const input = document.getElementById('global-search-input');
    input.value = '';
    input.focus();
    document.getElementById('global-search-results').innerHTML = '';

    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeGlobalSearch();
    });
}

function closeGlobalSearch() {
    document.getElementById('global-search-overlay').classList.remove('active');
}

async function globalSearch() {
    const q = document.getElementById('global-search-input').value.trim();
    const el = document.getElementById('global-search-results');
    if (!q) { el.innerHTML = ''; return; }

    clearTimeout(debounceTimers['globalSearch']);
    debounceTimers['globalSearch'] = setTimeout(async () => {
        try {
            const res = await fetch(`/api/global-search?q=${encodeURIComponent(q)}`);
            const d = await res.json();
            let items = [];
            d.memories.forEach(m => items.push({ type: 'memory', label: m.key, detail: m.preview }));
            d.templates.forEach(t => items.push({ type: 'template', label: t.name, detail: t.description }));
            d.connectors.forEach(c => items.push({ type: 'connector', label: c.display_name || c.name, detail: '' }));
            d.folders.forEach(f => items.push({ type: 'folder', label: f.name, detail: f.path }));

            if (items.length === 0) {
                el.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">No results</div>';
                return;
            }

            el.innerHTML = items.map(item => `<div class="global-search-item" onclick="globalSearchSelect('${escapeAttr(item.type)}', '${escapeAttr(item.label)}')">
                <span class="global-search-type">${item.type}</span>
                <div style="flex:1;min-width:0;">
                    <div style="font-weight:500;">${escapeHtml(item.label)}</div>
                    ${item.detail ? '<div style="font-size:11px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(item.detail) + '</div>' : ''}
                </div>
            </div>`).join('');
        } catch (e) { console.error(e); }
    }, 300);
}

function globalSearchSelect(type, label) {
    closeGlobalSearch();
    if (type === 'memory') { showTab('memories', null); setTimeout(() => { document.getElementById('memory-search').value = label; searchMemories(); }, 100); }
    else if (type === 'template') { showTab('assembler', null); }
    else if (type === 'connector' || type === 'folder') { showTab('sources', null); }
}

// ═══════════════════════════════════════════════════════════════
// SCHEDULED REPORTS
// ═══════════════════════════════════════════════════════════════

async function sendReport() {
    const tid = showToast('Generating report', 'Sending via webhooks...');
    try {
        const res = await fetch('/api/reports/summary', { method: 'POST' });
        const d = await res.json();
        completeToast(tid, `Report sent to ${d.webhooks_sent} webhook(s)`, false);
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
}

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// Version
async function loadVersion() {
    try {
        const res = await fetch('/health');
        const d = await res.json();
        const el = document.getElementById('app-version');
        if (el) el.textContent = 'v' + d.version;
    } catch (e) {}
}

// ═══════════════════════════════════════════════════════════════
// PROGRESS TOASTS
// ═══════════════════════════════════════════════════════════════

let toastCounter = 0;

function showToast(title, detail) {
    const id = 'toast-' + (++toastCounter);
    const container = document.getElementById('progress-toast');
    const html = `<div class="toast running" id="${id}">
        <div class="toast-spinner"></div>
        <div class="toast-body">
            <div class="toast-title">${escapeHtml(title)}</div>
            <div class="toast-detail">${escapeHtml(detail || 'Starting...')}</div>
        </div>
    </div>`;
    container.insertAdjacentHTML('beforeend', html);
    return id;
}

function updateToast(id, detail) {
    const el = document.getElementById(id);
    if (!el) return;
    const detailEl = el.querySelector('.toast-detail');
    if (detailEl) detailEl.textContent = detail;
}

function completeToast(id, detail, isError) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = `toast ${isError ? 'error' : 'done'}`;
    el.querySelector('.toast-spinner')?.remove();
    const icon = document.createElement('div');
    icon.className = 'toast-check';
    icon.textContent = isError ? '!' : '\u2713';
    if (isError) icon.style.color = 'var(--danger)';
    el.prepend(icon);
    const detailEl = el.querySelector('.toast-detail');
    if (detailEl) detailEl.textContent = detail;

    setTimeout(() => {
        el.style.animation = 'toastOut 0.3s ease forwards';
        setTimeout(() => el.remove(), 300);
    }, isError ? 8000 : 4000);
}

// Bot animation
let botTimer = null;
function botBusy() {
    const bot = document.getElementById('header-bot');
    if (bot) bot.classList.add('speaking');
    clearTimeout(botTimer);
}
function botIdle() {
    clearTimeout(botTimer);
    botTimer = setTimeout(() => {
        const bot = document.getElementById('header-bot');
        if (bot) bot.classList.remove('speaking');
    }, 400);
}
