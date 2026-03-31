// Context Pilot — Frontend Logic

const _mdRenderer = (function() {
    try {
        if (typeof EasyMDE !== 'undefined') {
            const el = document.createElement('textarea');
            document.body.appendChild(el);
            const inst = new EasyMDE({ element: el, autoDownloadFontAwesome: false, toolbar: false, status: false });
            inst.toTextArea();
            el.remove();
            return text => inst.markdown(text);
        }
    } catch (_) {}
    return null;
})();

function renderMarkdown(text) {
    let html;
    if (_mdRenderer) {
        try { html = _mdRenderer(text); } catch (_) { html = null; }
    }
    if (!html) html = '<pre>' + escapeHtml(text) + '</pre>';
    return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
}

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
    initMobileNav();
    initCollapsibleHeader();
    updateFabVisibility('dashboard');
    startup();
}

// ═══════════════════════════════════════════════════════════════
// MOBILE NAVIGATION
// ═══════════════════════════════════════════════════════════════

function initMobileNav() {
    const moreBtn = document.getElementById('mobile-more-btn');
    const moreMenu = document.getElementById('mobile-more-menu');
    if (!moreBtn || !moreMenu) return;

    const hiddenTabs = document.querySelectorAll('nav#main-nav .tab[data-mobile-priority="0"]');
    hiddenTabs.forEach(tab => {
        const clone = tab.cloneNode(true);
        clone.style.display = '';
        clone.addEventListener('click', () => {
            showTab(clone.dataset.tab, clone);
            moreMenu.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            clone.classList.add('active');
            document.querySelectorAll('nav#main-nav .tab[data-tab]').forEach(t => t.classList.remove('active'));
            moreBtn.classList.add('active');
            moreMenu.classList.remove('active');
        });
        moreMenu.appendChild(clone);
    });

    moreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        moreMenu.classList.toggle('active');
    });

    document.addEventListener('click', (e) => {
        if (!moreMenu.contains(e.target) && e.target !== moreBtn) {
            moreMenu.classList.remove('active');
        }
    });
}

function initCollapsibleHeader() {
    const header = document.querySelector('header');
    if (!header) return;
    let lastScrollY = 0;
    const threshold = 60;

    const onScroll = () => {
        const y = window.scrollY;
        if (y > threshold && y > lastScrollY) {
            header.classList.add('header-collapsed');
        } else if (y < lastScrollY - 10 || y <= threshold) {
            header.classList.remove('header-collapsed');
        }
        lastScrollY = y;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
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
        const tabKeys = { '1': 'dashboard', '2': 'memories', '3': 'skills', '4': 'graph', '5': 'secrets', '6': 'sources', '7': 'assembler', '8': 'settings' };
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

    // Show setup wizard for fresh installs, otherwise show welcome
    const wizardShown = await checkSetupWizard();
    if (!wizardShown) checkWelcome();
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
// SETUP WIZARD
// ═══════════════════════════════════════════════════════════════

const WIZARD_TOTAL_STEPS = 7;
let wizardCurrentStep = 0;

async function checkSetupWizard() {
    if (localStorage.getItem('cp-setup-complete')) return false;
    try {
        const res = await fetch('/api/setup-status');
        const data = await res.json();
        if (!data.is_fresh) {
            localStorage.setItem('cp-setup-complete', '1');
            return false;
        }
        showWizard(data);
        return true;
    } catch (e) {
        console.error('Setup status check failed:', e);
        return false;
    }
}

function showWizard(setupData) {
    const overlay = document.getElementById('wizard-overlay');
    if (!overlay) return;

    // Set data dir
    const dirEl = document.getElementById('wizard-data-dir');
    if (dirEl && setupData.data_dir) dirEl.textContent = setupData.data_dir;

    // Build dots
    const dotsContainer = document.getElementById('wizard-dots');
    dotsContainer.innerHTML = '';
    for (let i = 0; i < WIZARD_TOTAL_STEPS; i++) {
        const dot = document.createElement('div');
        dot.className = 'wizard-dot' + (i === 0 ? ' active' : '');
        dot.dataset.step = i;
        dotsContainer.appendChild(dot);
    }

    wizardCurrentStep = 0;
    updateWizardUI();
    requestAnimationFrame(() => overlay.classList.add('active'));
}

function updateWizardUI() {
    const fill = document.getElementById('wizard-progress-fill');
    const pct = ((wizardCurrentStep) / (WIZARD_TOTAL_STEPS - 1)) * 100;
    fill.style.width = pct + '%';

    document.querySelectorAll('.wizard-dot').forEach((dot, i) => {
        dot.className = 'wizard-dot';
        if (i < wizardCurrentStep) dot.classList.add('done');
        if (i === wizardCurrentStep) dot.classList.add('active');
    });

    const label = document.getElementById('wizard-step-label');
    const stepNames = ['Welcome', 'Storage', 'Profile', 'Connectors', 'Assembler', 'Memories', 'Finish'];
    label.textContent = stepNames[wizardCurrentStep] + ' \u2014 Step ' + (wizardCurrentStep + 1) + ' of ' + WIZARD_TOTAL_STEPS;

    const backBtn = document.getElementById('wizard-back-btn');
    const nextBtn = document.getElementById('wizard-next-btn');
    const skipBtn = document.getElementById('wizard-skip-btn');

    backBtn.style.display = wizardCurrentStep > 0 ? '' : 'none';
    skipBtn.style.display = wizardCurrentStep < WIZARD_TOTAL_STEPS - 1 ? '' : 'none';

    if (wizardCurrentStep === 0) {
        nextBtn.textContent = 'Get Started';
    } else if (wizardCurrentStep === WIZARD_TOTAL_STEPS - 1) {
        nextBtn.textContent = 'Launch Context Pilot';
    } else {
        nextBtn.textContent = 'Continue';
    }
}

function wizardGoToStep(target) {
    const steps = document.querySelectorAll('.wizard-step');
    const current = steps[wizardCurrentStep];
    const next = steps[target];
    if (!current || !next) return;

    const goingForward = target > wizardCurrentStep;

    current.classList.remove('active');
    current.classList.add(goingForward ? 'exit-left' : '');
    current.style.transform = goingForward ? 'translateX(-60px)' : 'translateX(60px)';
    current.style.opacity = '0';

    next.style.transform = goingForward ? 'translateX(60px)' : 'translateX(-60px)';
    next.style.opacity = '0';
    next.classList.remove('exit-left');

    requestAnimationFrame(() => {
        next.classList.add('active');
        next.style.transform = 'translateX(0)';
        next.style.opacity = '1';
    });

    wizardCurrentStep = target;
    updateWizardUI();
}

async function wizardNext() {
    if (wizardCurrentStep === 2) {
        await wizardCreateProfile();
    }

    if (wizardCurrentStep < WIZARD_TOTAL_STEPS - 1) {
        wizardGoToStep(wizardCurrentStep + 1);
    } else {
        wizardFinish();
    }
}

function wizardBack() {
    if (wizardCurrentStep > 0) {
        wizardGoToStep(wizardCurrentStep - 1);
    }
}

async function wizardCreateProfile() {
    const nameInput = document.getElementById('wizard-profile-name');
    const name = (nameInput?.value || '').trim();
    if (!name || name.toLowerCase() === 'default') return;

    try {
        await fetch('/api/profiles', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name}),
        });
        await fetch('/api/profiles/' + encodeURIComponent(name) + '/switch', {method: 'POST'});
    } catch (e) {
        console.error('Profile creation failed:', e);
    }
}

function wizardSkip() {
    wizardFinish();
}

function wizardFinish() {
    localStorage.setItem('cp-setup-complete', '1');
    localStorage.setItem('cp-welcome-v2', '1');
    const overlay = document.getElementById('wizard-overlay');
    if (overlay) {
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.4s ease';
        setTimeout(() => {
            overlay.classList.remove('active');
            overlay.remove();
        }, 400);
    }
    loadProfiles();
    loadDashboard();
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

    // Sync More menu active state on mobile
    const _mm = document.getElementById('mobile-more-menu');
    const _mb = document.getElementById('mobile-more-btn');
    if (_mm && _mb) {
        _mm.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
        _mb.classList.toggle('active', !!_mm.querySelector('.tab.active'));
        _mm.classList.remove('active');
    }

    const main = document.querySelector('main');
    if (name === 'graph') {
        main.style.maxWidth = 'none';
        main.style.padding = '0';
    } else {
        main.style.maxWidth = '';
        main.style.padding = '';
    }

    if (name === 'dashboard') { resetEventBadge(); loadDashboard(); }
    if (name === 'memories') loadMemories();
    if (name === 'skills') loadSkills();
    if (name === 'graph') loadGraph();
    if (name === 'secrets') loadSecrets();
    if (name === 'sources') { loadScheduler(); loadConnectors(); loadFolders(); loadWebhooks(); }
    if (name === 'assembler') loadTemplates();
    if (name === 'settings') loadSettings();

    updateFabVisibility(name);
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
        setBotState('connected');
    };

    eventSource.onmessage = (e) => {
        try {
            const event = JSON.parse(e.data);
            activityBuffer.unshift(event);
            if (activityBuffer.length > MAX_ACTIVITY) activityBuffer.pop();
            appendActivityItem(event);
            // Pulse the bot on non-api events
            if (event.category !== 'api') { botBusy(); setTimeout(botIdle, 600); }
            // Increment event badge when not on dashboard
            if (event.category !== 'api') incrementEventBadge();
        } catch (err) { console.error('SSE parse error:', err); }
    };

    eventSource.onerror = () => {
        const el = document.getElementById('sse-status');
        if (el) el.innerHTML = '<span class="sse-dot disconnected"></span>reconnecting...';
        setBotState('error');
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
            mcpDetail.innerHTML = '<a href="#" onclick="showTab(\'settings\');return false;" style="font-size:11px;color:var(--accent);">Register in Settings</a>';
        }
    } catch (e) {}

    // TTL stats
    try {
        const ttlRes = await fetch('/api/memories/ttl-stats');
        const ttl = await ttlRes.json();
        const card = document.getElementById('dash-expiring-card');
        if (ttl.total_with_ttl > 0 || ttl.expired > 0 || ttl.expiring_24h > 0) {
            card.style.display = '';
            const val = ttl.expired + ttl.expiring_24h;
            document.getElementById('dash-expiring').textContent = val;
            if (ttl.expired > 0) {
                // Auto-cleanup expired
                fetch('/api/memories/cleanup-expired', {method: 'POST'});
            }
        } else {
            card.style.display = 'none';
        }
    } catch (e) {}

    loadDashboardStats();
}

async function showExpiringMemories() {
    try {
        const res = await fetch('/api/memories/expiring?hours=168');
        const memories = await res.json();
        if (!memories.length) {
            openModal('Expiring Memories', '<p class="muted">No memories expiring in the next 7 days.</p>');
            return;
        }
        const now = Date.now() / 1000;
        const html = memories.map(m => {
            const rem = m.expires_at - now;
            const label = m.ttl_label || '?';
            const urgent = rem < 86400;
            return `<div class="memory-item" style="cursor:pointer;border-left:3px solid ${urgent ? 'var(--warning)' : 'var(--border)'};" onclick="closeModal();viewMemory('${escapeAttr(m.key)}')">
                <div class="main">
                    <div class="key"><span class="badge ${urgent ? 'badge-ttl-urgent' : 'badge-ttl'}">${label}</span> ${escapeHtml(m.key)}</div>
                    <div class="preview">${escapeHtml((m.value||'').substring(0,80))}</div>
                </div>
            </div>`;
        }).join('');
        openModal(`Expiring Memories (${memories.length})`, html);
    } catch (e) { console.error(e); }
}

async function loadDashboardStats() {
    showSkeleton('dash-top-tags', {rows: 4, type: 'text'});
    showSkeleton('dash-size-dist', {rows: 4, type: 'text'});
    showSkeleton('dash-connector-health', {rows: 3, type: 'text'});
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
        if (d.top_tags && d.top_tags.length) updateTagColors(d.top_tags);
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
    showSkeleton('skill-list', {rows: 3, type: 'list'});
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
    showSkeleton('memory-list', {rows: 6, type: 'list'});
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

    // Client-side lifetime filter
    const lifetimeFilter = document.getElementById('memory-lifetime-filter')?.value || '';
    let filtered = data;
    if (lifetimeFilter === 'permanent') {
        filtered = data.filter(m => !m.expires_at);
    } else if (lifetimeFilter === 'expiring') {
        filtered = data.filter(m => m.expires_at && m.expires_at > now);
    } else if (lifetimeFilter === 'urgent') {
        filtered = data.filter(m => m.expires_at && m.expires_at > now && (m.expires_at - now) < 86400);
    } else if (lifetimeFilter === 'week') {
        filtered = data.filter(m => m.expires_at && m.expires_at > now && (m.expires_at - now) < 604800);
    }

    if (filtered.length === 0) {
        list.innerHTML = '<div class="empty-state">No memories match the lifetime filter.</div>';
        return;
    }

    list.innerHTML = filtered.map(m => {
        const isNew = m.created_at && (now - m.created_at) < RECENT;
        const isModified = !isNew && m.updated_at && m.created_at
            && Math.abs(m.updated_at - m.created_at) > 2
            && (now - m.updated_at) < RECENT;

        let badge = '';
        if (isNew) badge = '<span class="badge badge-new">NEW</span> ';
        else if (isModified) badge = '<span class="badge badge-upd">UPD</span> ';

        const ts = m.updated_at || m.created_at;
        const age = ts ? 'vor ' + relativeTime(ts) : '';

        const stateClass = isNew ? ' new' : isModified ? ' updated' : '';
        const cbHtml = bulkMode ? '<input type="checkbox" class="bulk-cb" data-key="' + escapeAttr(m.key) + '" onclick="event.stopPropagation()">' : '';
        const tagsHtml = (m.tags || []).length
            ? m.tags.map(t => '<span class="tag' + getTagColorClass(t) + '" onclick="event.stopPropagation();clickTag(\'' + escapeAttr(t) + '\')">#' + escapeHtml(t) + '</span>').join(' ')
            : '';

        const pinned = m.pinned || false;
        const pinIcon = pinned ? '<span class="pin-badge" title="Pinned"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M16 2L20.58 6.58C21.37 7.37 21.37 8.63 20.58 9.42L17 13L17 17L15 19L12 16L7.5 20.5L6.08 19.08L10 15.17L7 12L5 14L3 12L9 6L12.58 3.42C13.37 2.63 14.63 2.63 15.42 3.42L16 2Z"/></svg></span>' : '';

        // Lifetime indicator
        let lifetimeHtml = '';
        if (m.expires_at) {
            const ttlLabel = m.ttl_label || '';
            if (ttlLabel === 'expired') {
                lifetimeHtml = '<span class="lifetime-indicator lifetime-expired" title="Expired">EXP</span>';
            } else {
                const ttlRemaining = m.expires_at - now;
                const isUrgent = ttlRemaining < 86400;
                const isSoon = ttlRemaining < 86400 * 3;
                const cls = isUrgent ? 'lifetime-urgent' : isSoon ? 'lifetime-soon' : 'lifetime-limited';
                lifetimeHtml = '<span class="lifetime-indicator ' + cls + '" title="Expires in ' + ttlLabel + '">' + ttlLabel + '</span>';
            }
        } else {
            lifetimeHtml = '<span class="lifetime-indicator lifetime-permanent" title="Permanent — no expiry">&#8734;</span>';
        }

        // Size info
        const tokens = m.tokens || 0;
        const bytes = m.bytes || 0;
        let sizeStr = '';
        if (tokens > 0) {
            const byteLabel = bytes >= 1024 ? (bytes / 1024).toFixed(1) + ' KB' : bytes + ' B';
            sizeStr = '<span class="token-count">' + tokens + ' tok / ' + byteLabel + '</span>';
        }

        const ek = escapeAttr(m.key);
        const chevron = '<svg class="mem-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>';

        return '<div class="memory-item' + stateClass + (m.expires_at && m.ttl_label === 'expired' ? ' expired' : '') + '" data-key="' + escapeHtml(m.key) + '">'
            + '<div class="mem-header" onclick="toggleAccordion(this)">'
            + cbHtml
            + chevron
            + '<div class="main">'
            + '<div class="key">' + pinIcon + badge + escapeHtml(m.key) + '</div>'
            + '<div class="preview">' + escapeHtml((m.value || '').substring(0, 120)) + '</div>'
            + '<div class="meta">'
            + tagsHtml
            + sizeStr
            + (age ? ' <span class="age">' + age + '</span>' : '')
            + ' ' + lifetimeHtml
            + '</div>'
            + '</div>'
            + '<div class="actions" onclick="event.stopPropagation()">'
            + '<button class="btn btn-icon' + (pinned ? ' btn-icon-active' : '') + '" onclick="togglePin(\'' + ek + '\',' + !pinned + ')" title="' + (pinned ? 'Unpin' : 'Pin') + '"><svg width="14" height="14" viewBox="0 0 24 24" fill="' + (pinned ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg></button>'
            + '<button class="btn btn-icon" onclick="editMemory(\'' + ek + '\')" title="Edit"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>'
            + '<button class="btn btn-icon btn-icon-danger" onclick="deleteMemory(\'' + ek + '\')" title="Delete"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>'
            + '</div>'
            + '</div>'
            + '<div class="mem-body" id="mem-body-' + ek + '"></div>'
            + '</div>';
    }).join('');
}

// --- Accordion & Sidebar ---

async function toggleAccordion(headerEl) {
    const item = headerEl.closest('.memory-item');
    const key = item.dataset.key;
    const isExpanded = item.classList.contains('expanded');

    // Collapse all others
    document.querySelectorAll('.memory-item.expanded').forEach(el => {
        if (el !== item) el.classList.remove('expanded');
    });

    if (isExpanded) {
        item.classList.remove('expanded');
        return;
    }

    item.classList.add('expanded');
    const body = item.querySelector('.mem-body');

    // Load content if not already loaded
    if (!body.dataset.loaded) {
        body.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:12px;">Loading...</div>';
        try {
            const url = memoryUrl(key);
            console.log('Accordion fetch:', url);
            const res = await fetch(url);
            if (!res.ok) {
                body.innerHTML = '<div style="padding:12px;color:var(--danger);font-size:12px;">HTTP ' + res.status + '</div>';
                return;
            }
            const m = await res.json();
            const val = m.value || '';

            const rendered = renderMarkdown(val);

            const tagsHtml = (m.tags || []).length
                ? m.tags.map(t => '<span class="tag' + getTagColorClass(t) + '" onclick="event.stopPropagation();clickTag(\'' + escapeAttr(t) + '\')">#' + escapeHtml(t) + '</span>').join(' ')
                : '';

            let ttlHtml = '';
            if (m.expires_at) {
                const ttlLabel = m.ttl_label || 'unknown';
                const color = ttlLabel === 'expired' ? 'var(--danger)' : m.expires_at - Date.now()/1000 < 86400 ? 'var(--warning)' : 'var(--text-muted)';
                ttlHtml = '<div style="margin-top:8px;padding:6px 10px;background:var(--bg);border-radius:4px;font-size:11px;border-left:3px solid ' + color + ';">TTL: <strong>' + ttlLabel + '</strong> remaining</div>';
            }

            const ek = escapeAttr(m.key);
            body.innerHTML = '<div class="mem-body-content">' + rendered + '</div>'
                + (tagsHtml ? '<div style="margin-top:8px;">' + tagsHtml + '</div>' : '')
                + ttlHtml
                + '<div class="mem-body-actions" onclick="event.stopPropagation()">'
                + '<button class="btn btn-small" onclick="event.stopPropagation();showVersions(\'' + ek + '\')">History</button>'
                + '<button class="btn btn-small btn-primary" onclick="event.stopPropagation();editMemory(\'' + ek + '\')">Edit</button>'
                + '<button class="btn btn-small" onclick="event.stopPropagation();viewMemory(\'' + ek + '\')">Full View</button>'
                + '</div>';
            body.dataset.loaded = '1';
        } catch (e) {
            console.error('Accordion load error:', key, e);
            body.innerHTML = '<div style="padding:12px;color:var(--danger);font-size:12px;">Error: ' + escapeHtml(String(e)) + '</div>';
        }
    }
}

function toggleMemSidebar() {
    const sidebar = document.getElementById('mem-sidebar');
    sidebar.classList.toggle('collapsed');
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

        const rendered = renderMarkdown(m.value);

        let ttlHtml = '';
        if (m.expires_at) {
            const ttlLabel = m.ttl_label || 'unknown';
            const color = ttlLabel === 'expired' ? 'var(--danger)' : m.expires_at - Date.now()/1000 < 86400 ? 'var(--warning)' : 'var(--text-muted)';
            ttlHtml = `<div style="margin-bottom:12px;padding:8px 12px;background:var(--surface-alt);border-radius:6px;font-size:12px;border-left:3px solid ${color};">
                TTL: <strong>${ttlLabel}</strong> remaining
                ${m.metadata?.ttl_seconds ? ' (resets on update, period: ' + Math.round(m.metadata.ttl_seconds/86400*10)/10 + 'd)' : ''}
            </div>`;
        }

        const pinned = m.pinned || false;
        const pinBtnClass = pinned ? ' btn-icon-active' : '';
        const pinFill = pinned ? 'currentColor' : 'none';

        openModal(m.key, `
            <div class="view-meta-bar">
                <div class="view-tags">${tagsHtml}</div>
                ${m.expires_at ? '<span class="lifetime-indicator ' + (m.ttl_label === 'expired' ? 'lifetime-expired' : 'lifetime-limited') + '">' + (m.ttl_label || '') + '</span>' : '<span class="lifetime-indicator lifetime-permanent">&#8734;</span>'}
            </div>
            ${ttlHtml}
            <div class="md-preview">${rendered}</div>
        `, `
            <button class="btn btn-icon${pinBtnClass}" onclick="togglePin('${escapeAttr(m.key)}',${!pinned});closeModal();" title="${pinned ? 'Unpin' : 'Pin'}"><svg width="14" height="14" viewBox="0 0 24 24" fill="${pinFill}" stroke="currentColor" stroke-width="2"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg></button>
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

        const currentTtlDays = m.metadata?.ttl_seconds ? (m.metadata.ttl_seconds / 86400) : '';
        const ttlInfo = m.ttl_label ? `<span style="font-size:11px;color:var(--text-muted);">Currently: ${m.ttl_label} remaining</span>` : '';
        openModal('Edit: ' + m.key, `
            <div class="edit-key-display">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                <span>${escapeHtml(m.key)}</span>
            </div>
            <label>Content</label>
            <textarea id="edit-value">${escapeHtml(m.value)}</textarea>
            <div style="display:flex;gap:16px;flex-wrap:wrap;">
                <div style="flex:1;min-width:200px;">
                    <label>Tags (comma-separated)</label>
                    <input type="text" id="edit-tags" value="${escapeHtml(m.tags.join(', '))}">
                </div>
                <div style="min-width:180px;">
                    <label>TTL (auto-delete after)</label>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <input type="number" id="edit-ttl" value="${currentTtlDays}" min="0" step="0.5" placeholder="No expiry" style="width:90px;">
                        <select id="edit-ttl-unit" style="width:auto;padding:6px 10px;">
                            <option value="days">days</option>
                            <option value="hours">hours</option>
                            <option value="minutes">minutes</option>
                        </select>
                        ${m.expires_at ? '<button class="btn btn-small" onclick="document.getElementById(\'edit-ttl\').value=\'\'" style="font-size:11px;">Remove</button>' : ''}
                    </div>
                    ${ttlInfo ? '<div style="margin-top:4px;">' + ttlInfo + '</div>' : ''}
                </div>
            </div>
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
    const ttlEl = document.getElementById('edit-ttl');
    let ttl_seconds = null;
    if (ttlEl) {
        const num = parseFloat(ttlEl.value);
        const unit = document.getElementById('edit-ttl-unit')?.value || 'days';
        if (num > 0) {
            ttl_seconds = unit === 'hours' ? num * 3600 : num * 86400;
        } else if (ttlEl.value === '' || ttlEl.value === '0') {
            ttl_seconds = 0; // explicitly remove TTL
        }
    }
    destroyEditor();
    const tid = showToast('Saving memory', key);
    try {
        const res = await fetch(memoryUrl(key), {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value, tags, ttl_seconds})
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

function openNewMemoryModal() {
    destroyEditor();
    openModal('New Memory', `
        <label>Key</label>
        <input type="text" id="new-memory-key" placeholder="e.g. project/api-endpoint">
        <label>Content</label>
        <textarea id="new-memory-value" placeholder="Write your memory content here..."></textarea>
        <div style="display:flex;gap:16px;flex-wrap:wrap;">
            <div style="flex:1;min-width:200px;">
                <label>Tags (comma-separated)</label>
                <input type="text" id="new-memory-tags" placeholder="e.g. config, api, setup">
            </div>
            <div style="min-width:180px;">
                <label>TTL (auto-delete after)</label>
                <div style="display:flex;gap:6px;align-items:center;">
                    <input type="number" id="new-memory-ttl" placeholder="No expiry" min="0" step="0.5" style="width:90px;">
                    <select id="new-memory-ttl-unit" style="width:auto;padding:6px 10px;">
                        <option value="days">days</option>
                        <option value="hours">hours</option>
                        <option value="minutes">minutes</option>
                    </select>
                </div>
            </div>
        </div>
    `, `
        <button class="btn btn-primary" id="save-new-memory-btn">Create Memory</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);

    setTimeout(() => initEditor('new-memory-value'), 50);

    document.getElementById('save-new-memory-btn').addEventListener('click', saveNewMemory);
}

async function saveNewMemory() {
    const key = document.getElementById('new-memory-key').value.trim();
    const value = activeEditor ? activeEditor.value() : document.getElementById('new-memory-value').value.trim();
    if (!key || !value) return;
    const tagsStr = document.getElementById('new-memory-tags').value.trim();
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
    const ttlEl = document.getElementById('new-memory-ttl');
    const ttlVal = ttlEl ? ttlEl.value : '';
    let ttl_seconds = null;
    if (ttlVal) {
        const num = parseFloat(ttlVal);
        const unit = document.getElementById('new-memory-ttl-unit')?.value || 'days';
        if (num > 0) {
            ttl_seconds = unit === 'hours' ? num * 3600 : unit === 'minutes' ? num * 60 : num * 86400;
        }
    }
    destroyEditor();
    closeModal();
    // Optimistic UI: insert placeholder at top of list
    const list = document.getElementById('memory-list');
    let optimisticEl = null;
    if (list) {
        const tagsHtml = tags.map(t => `<span class="tag">#${escapeHtml(t)}</span>`).join(' ');
        optimisticEl = document.createElement('div');
        optimisticEl.className = 'memory-item inserting';
        optimisticEl.dataset.optimisticKey = key;
        optimisticEl.innerHTML = `<div class="main"><div class="key"><span class="badge badge-new">NEW</span> ${escapeHtml(key)}</div><div class="preview">${escapeHtml(value.substring(0, 150))}</div><div class="meta">${tagsHtml}</div></div>`;
        list.prepend(optimisticEl);
    }
    const tid = showToast('Creating memory', key);
    try {
        const res = await fetch('/api/memories', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value, tags, ttl_seconds})
        });
        if (res.ok) {
            completeToast(tid, 'Created', false);
            loadMemories();
        } else {
            completeToast(tid, 'Create failed: ' + res.status, true);
            if (optimisticEl) optimisticEl.remove();
        }
    } catch (e) {
        completeToast(tid, 'Error: ' + e.message, true);
        if (optimisticEl) optimisticEl.remove();
    }
}

async function deleteMemory(key) {
    if (!confirm(`Delete "${key}"?`)) return;
    // Optimistic UI: remove from list immediately
    const list = document.getElementById('memory-list');
    const items = list?.querySelectorAll('.memory-item');
    let removedEl = null, removedSibling = null;
    if (items) {
        for (const item of items) {
            if (item.querySelector('.key')?.textContent?.includes(key)) {
                removedEl = item;
                removedSibling = item.nextSibling;
                item.classList.add('removing');
                setTimeout(() => item.remove(), 300);
                break;
            }
        }
    }
    try {
        const res = await fetch(memoryUrl(key), {method: 'DELETE'});
        if (res.ok) {
            notify('Memory deleted: ' + key, 'success');
        } else {
            // Rollback
            if (removedEl && list) {
                removedEl.classList.remove('removing');
                list.insertBefore(removedEl, removedSibling);
            }
            notify('Delete failed: ' + res.status, 'error');
        }
    } catch (e) {
        if (removedEl && list) {
            removedEl.classList.remove('removing');
            list.insertBefore(removedEl, removedSibling);
        }
        notify('Delete failed: ' + e.message, 'error');
    }
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
    const tid = silent ? null : showToast('Building search index', 'Started in background...');
    try {
        const res = await fetch('/api/embeddings/index', { method: 'POST' });
        const d = await res.json();
        if (d.status === 'already_running') {
            if (tid) completeToast(tid, 'Already running', false);
            return;
        }
        if (tid) {
            // Poll for completion
            const poll = setInterval(async () => {
                try {
                    const sr = await fetch('/api/embeddings/index/status');
                    const st = await sr.json();
                    if (st.status === 'done') {
                        clearInterval(poll);
                        completeToast(tid, `${st.indexed} indexed, ${st.skipped} skipped (${st.backend})`, false);
                    } else if (st.status === 'error') {
                        clearInterval(poll);
                        completeToast(tid, 'Failed', true);
                    }
                } catch (_) { clearInterval(poll); }
            }, 1000);
        }
    } catch (e) {
        if (tid) completeToast(tid, 'Failed: ' + e.message, true);
        console.error('rebuildIndex failed:', e);
    }
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
    const ttlBtn = document.getElementById('bulk-ttl-btn');
    if (ttlBtn) ttlBtn.style.display = bulkMode ? '' : 'none';
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

function showBulkTTLDialog() {
    const checked = document.querySelectorAll('.bulk-cb:checked');
    if (checked.length === 0) { alert('No memories selected.'); return; }
    const count = checked.length;
    openModal(`Set TTL for ${count} memories`, `
        <p style="margin-bottom:16px;color:var(--text-secondary);">Set a lifetime for <strong>${count}</strong> selected memories. Leave empty to make permanent.</p>
        <div style="display:flex;gap:8px;align-items:center;">
            <input type="number" id="bulk-ttl-value" placeholder="Duration" min="0" step="1" style="width:120px;">
            <select id="bulk-ttl-unit" style="width:auto;padding:8px 12px;">
                <option value="days">days</option>
                <option value="hours">hours</option>
            </select>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;">
            <button class="btn btn-small" onclick="document.getElementById('bulk-ttl-value').value='7'">7d</button>
            <button class="btn btn-small" onclick="document.getElementById('bulk-ttl-value').value='30'">30d</button>
            <button class="btn btn-small" onclick="document.getElementById('bulk-ttl-value').value='90'">90d</button>
            <button class="btn btn-small" onclick="document.getElementById('bulk-ttl-value').value=''">Permanent</button>
        </div>
    `, `
        <button class="btn btn-primary" onclick="bulkSetTTL()">Apply TTL</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);
}

async function bulkSetTTL() {
    const checked = document.querySelectorAll('.bulk-cb:checked');
    if (checked.length === 0) return;
    const keys = Array.from(checked).map(cb => cb.dataset.key);
    const numVal = parseFloat(document.getElementById('bulk-ttl-value').value);
    const unit = document.getElementById('bulk-ttl-unit')?.value || 'days';
    let ttl_seconds = null;
    if (numVal > 0) {
        ttl_seconds = unit === 'hours' ? numVal * 3600 : numVal * 86400;
    } else {
        ttl_seconds = 0; // remove TTL
    }
    closeModal();
    const tid = showToast('Setting TTL', `${keys.length} memories...`);
    let ok = 0;
    for (const key of keys) {
        try {
            const res = await fetch(memoryUrl(key) + '/ttl', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ttl_seconds})
            });
            if (res.ok) ok++;
        } catch (e) {}
    }
    completeToast(tid, `TTL set on ${ok}/${keys.length} memories`, ok < keys.length);
    loadMemories();
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
        const count = Array.isArray(data) ? data.length : (data.memories?.length || '?');
        notify(`Exported ${count} memories`, 'success');
    } catch (e) {
        notify('Export failed: ' + e.message, 'error');
        console.error(e);
    }
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
    const bar = document.getElementById('budget-bar');
    bar.style.width = '0%';
    requestAnimationFrame(() => { bar.style.width = pct + '%'; });
    document.getElementById('budget-label').textContent =
        `${data.used_tokens.toLocaleString()} / ${data.budget.toLocaleString()} tokens (${pct.toFixed(1)}%)`;

    const meta = [];
    if (data.template) meta.push(`Template: <strong>${escapeHtml(data.template)}</strong>`);
    if (data.assembly_id) meta.push(`ID: <code>${data.assembly_id}</code>`);
    meta.push(`${data.block_count} included`);
    if (data.dropped_count) meta.push(`${data.dropped_count} dropped`);
    if (data.total_matching) meta.push(`${data.total_matching} matched`);
    document.getElementById('assembly-meta').innerHTML = meta.join(' &middot; ');

    document.getElementById('assembly-blocks').innerHTML = data.blocks.map(b => {
        const keyLabel = b.key ? `<span style="font-weight:600;">${escapeHtml(b.key)}</span> &middot; ` : '';
        return `<div class="result-block priority-${b.priority}">
            <div class="meta">${keyLabel}${b.priority.toUpperCase()} &middot; ${b.token_count} tok${b.compress_hint ? ' &middot; ' + b.compress_hint : ''}</div>
            <pre>${escapeHtml(b.content.length > 500 ? b.content.substring(0, 500) + '...' : b.content)}</pre>
        </div>`;
    }).join('');

    let droppedHtml = '';
    if (data.dropped && data.dropped.length > 0) {
        droppedHtml = `<details style="margin-top:8px;"><summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--text-muted);">${data.dropped.length} Dropped Blocks</summary>` +
            data.dropped.map(b => {
                const keyLabel = b.key ? `<span style="font-weight:600;">${escapeHtml(b.key)}</span> &middot; ` : '';
                return `<div class="result-block dropped">
                    <div class="meta">${keyLabel}${b.priority.toUpperCase()} &middot; ${b.token_count} tok (dropped)</div>
                    <pre>${escapeHtml(b.content.length > 200 ? b.content.substring(0, 200) + '...' : b.content)}</pre>
                </div>`;
            }).join('') + '</details>';
    }
    document.getElementById('assembly-dropped').innerHTML = droppedHtml;
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
            notify(`${d.count} memories imported from ${d.filename}`, 'success', 5000);
            loadDashboard();
        } else {
            statusEl.textContent = d.message || 'Import failed';
            notify(d.message || 'Import failed', 'error', 5000);
        }
    } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
        notify('Import error: ' + e.message, 'error');
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

        // Header switcher
        const sel = document.getElementById('profile-select');
        sel.innerHTML = '';
        d.profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            if (p.is_active) opt.selected = true;
            sel.appendChild(opt);
        });

        // Settings profile list
        const listEl = document.getElementById('settings-profiles-list');
        if (listEl) {
            listEl.innerHTML = d.profiles.map(p => {
                const active = p.is_active;
                const isDefault = p.is_default;
                const eid = escapeAttr(p.id);
                return '<div class="profile-card' + (active ? ' profile-active' : '') + '">'
                    + '<div class="profile-card-info">'
                    + '<div class="profile-card-name">'
                    + (active ? '<span class="profile-dot"></span>' : '')
                    + escapeHtml(p.name)
                    + (isDefault ? ' <span class="profile-badge">Default</span>' : '')
                    + '</div>'
                    + '<div class="profile-card-meta">'
                    + p.memory_count + ' memories'
                    + (p.description ? ' &mdash; ' + escapeHtml(p.description) : '')
                    + '</div>'
                    + '</div>'
                    + '<div class="profile-card-actions">'
                    + (!active ? '<button class="btn btn-small btn-primary" onclick="switchToProfile(\'' + eid + '\')">Switch</button>' : '')
                    + (!isDefault ? '<button class="btn btn-small" onclick="renameProfile(\'' + eid + '\',\'' + escapeAttr(p.name) + '\',\'' + escapeAttr(p.description || '') + '\')">Rename</button>' : '')
                    + (d.profiles.length > 1 ? '<button class="btn btn-small" onclick="showImportMemoriesDialogFor(\'' + eid + '\')">Import</button>' : '')
                    + (!isDefault ? '<button class="btn btn-small btn-danger" onclick="deleteProfile(\'' + eid + '\',\'' + escapeAttr(p.name) + '\')">Delete</button>' : '')
                    + '</div>'
                    + '</div>';
            }).join('');
        }
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
            notify(`Profile "${name}" created` + (d.imported > 0 ? `, ${d.imported} memories imported` : ''), 'success', 5000);
            loadProfiles();
            if (d.imported > 0) {
                document.getElementById('import-status').textContent = `Profile "${name}" created, ${d.imported} memories imported.`;
            } else {
                showWelcomeForNewProfile(name);
            }
        } else {
            const d = await res.json();
            notify(d.detail || 'Failed to create profile', 'error');
        }
    } catch (e) { alert('Error: ' + e.message); }
}

async function switchToProfile(pid) {
    const tid = showToast('Switching profile', 'Loading...');
    try {
        await fetch(`/api/profiles/${encodeURIComponent(pid)}/switch`, { method: 'POST' });
        completeToast(tid, 'Switched', false);
        loadProfiles();
        const activeTab = document.querySelector('.tab.active');
        if (activeTab) showTab(activeTab.dataset.tab, activeTab);
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function renameProfile(pid, currentName, currentDesc) {
    openModal('Rename Profile', `
        <label>Name</label>
        <input type="text" id="rename-profile-name" value="${escapeHtml(currentName)}">
        <label>Description</label>
        <input type="text" id="rename-profile-desc" value="${escapeHtml(currentDesc)}" placeholder="Optional description">
    `, `
        <button class="btn btn-primary" id="rename-profile-submit">Save</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);
    document.getElementById('rename-profile-submit').addEventListener('click', async () => {
        const newName = document.getElementById('rename-profile-name').value.trim();
        const desc = document.getElementById('rename-profile-desc').value.trim();
        if (!newName) return;
        try {
            const res = await fetch(`/api/profiles/${encodeURIComponent(pid)}?new_name=${encodeURIComponent(newName)}&description=${encodeURIComponent(desc)}`, { method: 'PUT' });
            if (res.ok) { closeModal(); notify('Profile renamed', 'success'); loadProfiles(); }
            else { const d = await res.json(); notify(d.detail || 'Rename failed', 'error'); }
        } catch (e) { console.error(e); }
    });
}

function showImportMemoriesDialogFor(pid) {
    showImportMemoriesDialog();
}

async function deleteProfile(pid, name) {
    if (!confirm(`Delete profile "${name}"? All memories will be lost!`)) return;
    const tid = showToast('Deleting profile', name);
    try {
        await fetch(`/api/profiles/${encodeURIComponent(pid)}`, { method: 'DELETE' });
        completeToast(tid, 'Deleted', false);
        loadProfiles();
        loadDashboard();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

// Keep legacy functions as aliases
async function renameActiveProfile() {
    const pid = document.getElementById('profile-select').value;
    const sel = document.getElementById('profile-select');
    const currentName = sel.options[sel.selectedIndex]?.textContent || '';
    renameProfile(pid, currentName, '');
}

async function deleteActiveProfile() {
    const pid = document.getElementById('profile-select').value;
    const sel = document.getElementById('profile-select');
    const name = sel.options[sel.selectedIndex]?.textContent || pid;
    deleteProfile(pid, name);
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
    showSkeleton('secrets-list', {rows: 5, type: 'list'});
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

let _allConnectors = [];
let _connFilter = {category: 'All', status: 'All'};

const _connIcons = {
    github: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M12 .3a12 12 0 0 0-3.8 23.38c.6.11.82-.26.82-.58v-2.02c-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.33-1.76-1.33-1.76-1.09-.74.08-.73.08-.73 1.2.09 1.84 1.24 1.84 1.24 1.07 1.83 2.8 1.3 3.49 1 .1-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.3-.54-1.52.12-3.18 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6.02 0c2.28-1.55 3.29-1.23 3.29-1.23.66 1.66.25 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.63-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.22.7.82.58A12 12 0 0 0 12 .3"/></svg>',
    gitea: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M4.21 6.1a.68.68 0 1 0 0 1.36.68.68 0 0 0 0-1.36m7.26-4.2C7.49.52 2.5 3.13 1.13 7.1c-.17.5-.3 1-.38 1.52a4.5 4.5 0 0 0 2.57 4.78 13 13 0 0 0 2.44.9 8.6 8.6 0 0 1 1.8.7c.38.22.63.47.77.8.14.3.2.67.23 1.1.01.42.01.87.01 1.4v2.08c0 .16 0 .32.02.48a2.15 2.15 0 0 0 2.38 1.91h.37c.65-.06 1.23-.36 1.64-.82.4-.44.63-1.01.63-1.6v-3.54a5.05 5.05 0 0 1 .95-2.96 2.03 2.03 0 0 0-.73-2.87l-.14-.07c-.3-.14-.63-.2-.95-.19a2 2 0 0 0-1.85 1.26 3.2 3.2 0 0 0-.16 1.73c.02.12.05.24.08.35.05.17.1.33.13.5.05.25.03.5-.06.73a.81.81 0 0 1-.53.43c-.1.03-.2.03-.3.02a1.2 1.2 0 0 1-.5-.16 1.72 1.72 0 0 1-.57-.53 2.1 2.1 0 0 1-.31-.8 5.3 5.3 0 0 1-.08-.94V9.85c.01-1.06.22-1.96.81-2.7a3.9 3.9 0 0 1 2.54-1.45c1.13-.2 2.3-.05 3.33.43a4 4 0 0 1 2.27 3.07c.1.55.12 1.1.06 1.66a5.14 5.14 0 0 1-1.7 3.3 2.9 2.9 0 0 1-.57.4 1.03 1.03 0 0 0-.5.92v3.97c0 .65.26 1.27.72 1.73.47.46 1.1.7 1.74.7h.2c.69-.04 1.32-.35 1.78-.86.47-.5.72-1.16.72-1.85v-1.32c0-.38.02-.74.05-1.05.04-.37.13-.72.3-1.03.19-.37.48-.68.85-.88a8 8 0 0 1 1.52-.6 13 13 0 0 0 2.44-.9 4.5 4.5 0 0 0 2.56-4.78 11.4 11.4 0 0 0-7.85-9z"/></svg>',
    paperless: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2 5 5h-5V4zM8 13h8v1H8v-1zm0 3h8v1H8v-1zm0-6h3v1H8v-1z"/></svg>',
    obsidian: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M12.5 1.3 21 6.8v10.5l-8.5 5.4-8.5-5.4V6.8l8.5-5.5zm0 2.3L5.6 7.8v8.4l6.9 4.4 6.9-4.4V7.8l-6.9-4.2z"/><path d="m12.5 7.1-4.2 2.6v5.2l4.2 2.7 4.2-2.7V9.7l-4.2-2.6z"/></svg>',
    email: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4-8 5-8-5V6l8 5 8-5v2z"/></svg>',
    bookmarks: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z"/></svg>',
    homeassistant: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M12 2L2 12h3v8h6v-6h2v6h6v-8h3L12 2zm0 2.84L18.16 11H17v8h-3v-6H10v6H7v-8H5.84L12 4.84z"/></svg>',
    excel: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM9.3 17 7 13.4h1.5l1.5 2.5 1.5-2.5H13L10.7 17l2.3 3.6h-1.5L10 18l-1.5 2.6H7L9.3 17zM14 9h-1V4l5 5h-4z"/></svg>',
    gdrive: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="m7.71 3.5 1.63 2.83L15.97 3.5H7.71zm8.57 0-6.64 11.5 1.63 2.83L22.55 3.5H16.28zm1.64 2.83-6.64 11.5h6.27l6.63-11.5h-6.26zM8.6 8 1.45 20.5h3.26L11.85 8H8.6zm-.33.58L1.45 20.5h6.53L14.8 9.08 8.27 8.58z"/></svg>',
    notion: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M4.46 4.29c.48.41.66.38 1.56.33l8.5-.5c.19 0 .03-.18-.03-.2l-1.4-1.02c-.28-.22-.66-.46-1.37-.4l-8.23.6c-.33.03-.4.18-.26.3l1.23.89zm.5 1.94v8.94c0 .48.24.66.78.63l9.34-.54c.54-.03.6-.36.6-.75V5.97c0-.39-.15-.57-.48-.54l-9.76.57c-.36.03-.48.18-.48.48v-.25zm9.22.6c.06.27 0 .54-.27.57l-.45.09v6.6c-.39.21-.75.33-.99.33-.45 0-.57-.15-.9-.57L8.56 9.1v4.44l.93.21s0 .54-.75.54l-2.07.12c-.06-.12 0-.42.21-.48l.54-.15V7.85l-.75-.06c-.06-.27.09-.66.51-.69l2.22-.15 3.18 4.86V7.82l-.78-.09c-.06-.33.18-.57.48-.6l2.1-.12v-.18zm-11.7-4.5L11 1.77c.69-.06 .87-.03 1.31.3l3.63 2.53c.42.3.54.39.54.72v10.14c0 .63-.24 1.02-.99 1.08l-9.94.6c-.57.03-.84-.06-1.14-.45L1.82 13.4c-.33-.42-.48-.72-.48-1.08V3.35c0-.45.24-.84.78-.87l-.62-.15z"/></svg>',
    teams: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M19.19 8.77a1.85 1.85 0 1 0 0-3.7 1.85 1.85 0 0 0 0 3.7zM22.31 9.58h-4.38a.91.91 0 0 0-.9.91v4.34a3.1 3.1 0 0 0 2.78 3.08 3.1 3.1 0 0 0 3.41-3.08v-4.34a.91.91 0 0 0-.91-.91zM14.5 7.92a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM17 9H9.88a.88.88 0 0 0-.88.88v5.62a4 4 0 0 0 8 0V9.88A.88.88 0 0 0 17 9zM7.5 9.58H3.69a.91.91 0 0 0-.91.91v3.77a2.63 2.63 0 0 0 5.16.71.96.96 0 0 0 .04-.14V10.5a.91.91 0 0 0-.48-.92zM5 8.77a1.85 1.85 0 1 0 0-3.7 1.85 1.85 0 0 0 0 3.7z"/></svg>',
    telegram: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 0 0-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/></svg>',
    rss: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M6.18 15.64a2.18 2.18 0 0 1 2.18 2.18C8.36 19 7.38 20 6.18 20 5 20 4 19 4 17.82a2.18 2.18 0 0 1 2.18-2.18M4 4.44A15.56 15.56 0 0 1 19.56 20h-2.83A12.73 12.73 0 0 0 4 7.27V4.44m0 5.66a9.9 9.9 0 0 1 9.9 9.9h-2.83A7.07 7.07 0 0 0 4 12.93V10.1z"/></svg>',
    keepass: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M12.65 10a6 6 0 0 0-11.59 0H1v4h.06a6 6 0 0 0 11.59 0H17v2h2v-2h1v2h2v-6H12.65zM7 14a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/></svg>',
    bitwarden: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M3.5 3.5v10.8c0 1.06.47 2.07 1.28 2.75L12 23l7.22-5.95c.81-.68 1.28-1.69 1.28-2.75V3.5h-17zm14 10.8a1.5 1.5 0 0 1-.55 1.16L12 19.74l-4.95-4.28a1.5 1.5 0 0 1-.55-1.16V6h10v8.3z"/></svg>',
    kubernetes: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M12 1.5 2.4 6.75v10.5L12 22.5l9.6-5.25V6.75L12 1.5zm0 2.31 7.2 3.94v7.87L12 19.56l-7.2-3.94V7.75L12 3.81zm0 3.19a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/></svg>',
    dockge: '<svg viewBox="0 0 24 24" fill="#fff" width="22" height="22"><path d="M13.98 11.08c2.28.25 3.97.64 3.97.64s-1.3 3.54-4.28 5.57C10.69 19.31 7.6 20 7.6 20s-.55-3.82.67-7.07c.56-1.49 1.42-2.78 2.53-3.78a7.37 7.37 0 0 1 3.17-1.87l.01-.2zm-2.34.72c-.82.73-1.49 1.68-1.93 2.84-.8 2.15-.71 4.37-.6 5.34.78-.18 2.7-.78 4.48-2.01 1.72-1.18 2.8-2.86 3.3-3.83-.87-.18-2.15-.4-3.62-.5a7.15 7.15 0 0 0-1.63.16zM3 12.5a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm3-5a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm5.5-3a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>',
};

async function loadConnectors() {
    const el = document.getElementById('connectors-list');
    if (el && (!_allConnectors || _allConnectors.length === 0)) {
        showSkeleton('connectors-list', {rows: 6, type: 'cards'});
    }
    try {
        const res = await fetch('/api/connectors');
        _allConnectors = await res.json();
        renderConnectorFilters();
        renderConnectorStore();
    } catch (e) { console.error(e); }
}

function renderConnectorFilters() {
    const cats = ['All', ...new Set(_allConnectors.map(c => c.category || 'Other'))];
    const statuses = ['All', 'Connected', 'Available'];
    const filEl = document.getElementById('conn-filters');
    if (!filEl) return;
    filEl.innerHTML =
        cats.map(c => `<button class="conn-filter${_connFilter.category === c ? ' active' : ''}" onclick="setConnFilter('category','${c}')">${c}</button>`).join('') +
        '<span style="width:1px;background:var(--border);margin:0 4px;"></span>' +
        statuses.map(s => `<button class="conn-filter${_connFilter.status === s ? ' active' : ''}" onclick="setConnFilter('status','${s}')">${s}</button>`).join('');
}

function setConnFilter(key, val) {
    _connFilter[key] = val;
    renderConnectorFilters();
    renderConnectorStore();
}

function renderConnectorStore() {
    let filtered = _allConnectors;
    if (_connFilter.category !== 'All') filtered = filtered.filter(c => c.category === _connFilter.category);
    if (_connFilter.status === 'Connected') filtered = filtered.filter(c => c.configured && c.enabled);
    if (_connFilter.status === 'Available') filtered = filtered.filter(c => !c.configured);

    const countEl = document.getElementById('conn-count');
    if (countEl) countEl.textContent = `${filtered.length} of ${_allConnectors.length} connectors`;

    const el = document.getElementById('connectors-list');
    if (filtered.length === 0) {
        el.innerHTML = '<p class="muted" style="padding:20px;text-align:center;">No connectors match this filter.</p>';
        return;
    }
    el.innerHTML = filtered.map(c => renderConnectorCard(c)).join('');
}

function renderConnectorCard(c) {
    const bg = c.color || 'var(--accent)';
    const lastSync = c.last_sync ? new Date(c.last_sync * 1000).toLocaleString() : '';
    let statusDot, statusText, cardClass, actions;

    if (!c.configured) {
        statusDot = 'gray'; statusText = 'Not connected'; cardClass = '';
        actions = `<button class="btn btn-small btn-primary" onclick="showConnectorSetup('${escapeAttr(c.name)}')">Connect</button>`;
    } else if (c.enabled) {
        statusDot = 'green'; statusText = `${c.synced_count} items`; cardClass = 'connected';
        actions = `<button class="btn btn-small btn-primary" onclick="syncConnector('${escapeAttr(c.name)}')">Sync</button>
            <button class="btn btn-small" onclick="showConnectorSetup('${escapeAttr(c.name)}')">Settings</button>
            <button class="btn btn-small btn-danger" onclick="removeConnector('${escapeAttr(c.name)}')">Disconnect</button>`;
    } else {
        statusDot = 'orange'; statusText = 'Disabled'; cardClass = 'disabled';
        actions = `<button class="btn btn-small btn-primary" onclick="enableConnector('${escapeAttr(c.name)}',true)">Enable</button>
            <button class="btn btn-small" onclick="showConnectorSetup('${escapeAttr(c.name)}')">Settings</button>`;
    }

    return `<div class="connector-card ${cardClass}">
        <div class="conn-card-header">
            <div class="conn-icon" style="background:${bg};">${_connIcons[c.name] || escapeHtml(c.icon)}</div>
            <div>
                <div class="conn-name">${escapeHtml(c.display_name)}</div>
                ${lastSync ? `<div style="font-size:10px;color:var(--text-muted);">Last: ${lastSync}</div>` : ''}
            </div>
            <span class="conn-cat">${escapeHtml(c.category || 'Other')}</span>
        </div>
        <div class="conn-desc">${escapeHtml(c.description)}</div>
        <div class="conn-status"><span class="dot ${statusDot}"></span>${statusText}</div>
        <div class="conn-actions">${actions}</div>
    </div>`;
}

async function enableConnector(name, enabled) {
    try {
        await fetch(`/api/connectors/${encodeURIComponent(name)}/enable?enabled=${enabled}`, {method: 'POST'});
        notify(`Connector "${name}" ${enabled ? 'enabled' : 'disabled'}`, 'info');
        loadConnectors();
    } catch (e) {
        notify('Failed: ' + e.message, 'error');
    }
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

        const ttlField = `<label>Memory TTL (auto-delete synced memories after N days, 0 = never)</label>
            <input type="number" id="conn-ttl_days" placeholder="0 (permanent)" value="${c.ttl_days || ''}" min="0" step="1">`;

        const guide = c.setup_guide ? `<div class="conn-setup-guide">${escapeHtml(c.setup_guide)}</div>` : '';
        openModal(`${c.display_name} Setup`, guide + fields + ttlField, `
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

    // Include TTL days
    const ttlEl = document.getElementById('conn-ttl_days');
    if (ttlEl) {
        const ttlVal = parseInt(ttlEl.value) || 0;
        values['ttl_days'] = ttlVal > 0 ? ttlVal : 0;
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
        notify(`Connector "${name}" disconnected`, 'success');
        loadConnectors();
    } catch (e) {
        notify('Disconnect failed: ' + e.message, 'error');
        console.error(e);
    }
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
    showSkeleton('folder-list', {rows: 2, type: 'list'});
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

let _allTemplates = [];

async function loadTemplates() {
    const el = document.getElementById('template-list');
    if (!el) return;
    try {
        const res = await fetch('/api/templates');
        _allTemplates = await res.json();
        renderTemplates(_allTemplates);
    } catch (e) { console.error(e); }
}

function renderTemplates(templates) {
    const el = document.getElementById('template-list');
    const countEl = document.getElementById('asm-tpl-count');
    if (countEl) countEl.textContent = templates.length + ' template' + (templates.length !== 1 ? 's' : '');

    if (templates.length === 0) {
        el.innerHTML = '<p class="muted" style="padding:16px;">No templates match. Create one to get started.</p>';
        return;
    }
    el.innerHTML = templates.map(t => {
        const tags = t.tag_filter.length ? t.tag_filter.map(tag => `<span class="tpl-badge">${escapeHtml(tag)}</span>`).join('') : '<span class="tpl-badge">all</span>';
        return `<div class="tpl-item" data-name="${escapeAttr(t.name)}">
            <div class="tpl-header" onclick="toggleTplAccordion(this)">
                <span class="tpl-chevron">&#9654;</span>
                <span class="tpl-name">${escapeHtml(t.name)}</span>
                <span class="tpl-desc">${escapeHtml(t.description || '')}</span>
                <span class="tpl-badges">${tags}</span>
                <span class="tpl-badge">${t.budget} tok</span>
            </div>
            <div class="tpl-body">
                <dl class="tpl-details">
                    <dt>Description</dt><dd>${escapeHtml(t.description || '(none)')}</dd>
                    <dt>Tag Filter</dt><dd>${t.tag_filter.length ? t.tag_filter.join(', ') : 'all memories'}</dd>
                    <dt>Key Filter</dt><dd>${t.key_filter ? escapeHtml(t.key_filter) : 'none'}</dd>
                    <dt>Token Budget</dt><dd>${t.budget.toLocaleString()} tokens</dd>
                </dl>
                <div class="tpl-actions">
                    <button class="btn btn-small btn-primary" onclick="assembleTemplate('${escapeAttr(t.name)}')">Assemble</button>
                    <button class="btn btn-small" onclick="editTemplate('${escapeAttr(t.name)}')">Edit</button>
                    <button class="btn btn-small btn-danger" onclick="deleteTemplate('${escapeAttr(t.name)}')">Delete</button>
                </div>
            </div>
        </div>`;
    }).join('');
}

function toggleTplAccordion(header) {
    const item = header.closest('.tpl-item');
    item.classList.toggle('expanded');
}

function filterTemplates(query) {
    const q = query.toLowerCase().trim();
    if (!q) { renderTemplates(_allTemplates); return; }
    renderTemplates(_allTemplates.filter(t =>
        t.name.toLowerCase().includes(q) ||
        (t.description || '').toLowerCase().includes(q) ||
        t.tag_filter.some(tag => tag.toLowerCase().includes(q))
    ));
}

function toggleAsmSidebar() {
    const sb = document.querySelector('.asm-sidebar');
    if (sb) sb.style.display = sb.style.display === 'none' ? '' : 'none';
}

async function suggestTemplates() {
    const tid = showToast('Analyzing memories', 'Finding clusters...');
    botBusy();
    try {
        const res = await fetch('/api/templates/suggest');
        const d = await res.json();
        const suggestions = d.suggestions || [];
        if (suggestions.length === 0) {
            completeToast(tid, 'No new templates to suggest', false);
            return;
        }
        completeToast(tid, `${suggestions.length} suggestions found`, false);

        const reasonLabel = {key_prefix: 'Key Prefix', tag_cluster: 'Tag Cluster', all: 'All Memories'};
        const rows = suggestions.map(s => `
            <div class="tpl-item" style="margin-bottom:4px;">
                <div class="tpl-header" onclick="toggleTplAccordion(this)">
                    <span class="tpl-chevron">&#9654;</span>
                    <span class="tpl-name">${escapeHtml(s.name)}</span>
                    <span class="tpl-desc">${escapeHtml(s.description)}</span>
                    <span class="tpl-badge">${s.memory_count} mem</span>
                    <span class="tpl-badge">${s.budget} tok</span>
                </div>
                <div class="tpl-body">
                    <dl class="tpl-details">
                        <dt>Reason</dt><dd>${reasonLabel[s.reason] || s.reason}</dd>
                        <dt>Tag Filter</dt><dd>${s.tag_filter.length ? s.tag_filter.join(', ') : 'none'}</dd>
                        <dt>Key Filter</dt><dd>${s.key_filter || 'none'}</dd>
                        <dt>Memories</dt><dd>${s.memory_count} (${s.total_tokens.toLocaleString()} tokens total)</dd>
                        <dt>Budget</dt><dd>${s.budget.toLocaleString()} tokens</dd>
                    </dl>
                    <div class="tpl-actions">
                        <button class="btn btn-small btn-primary" onclick="acceptSuggestion(${escapeAttr(JSON.stringify(s))})">Accept</button>
                        <button class="btn btn-small" onclick="this.closest('.tpl-item').remove()">Dismiss</button>
                    </div>
                </div>
            </div>`).join('');

        openModal('Template Suggestions', `
            <p class="muted" style="margin:0 0 12px;">Based on your memory clusters. Click <strong>Accept</strong> to create.</p>
            <div style="max-height:60vh;overflow-y:auto;">${rows}</div>
        `, `
            <button class="btn btn-primary" onclick="acceptAllSuggestions()">Accept All</button>
            <button class="btn" onclick="closeModal()">Close</button>
        `);
        window._pendingSuggestions = suggestions;
    } catch (e) { completeToast(tid, 'Failed: ' + e.message, true); }
    finally { botIdle(); }
}

async function acceptSuggestion(s) {
    try {
        const res = await fetch('/api/templates', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: s.name, description: s.description, tag_filter: s.tag_filter, key_filter: s.key_filter, budget: s.budget})
        });
        if (res.ok) {
            const tid3 = showToast('Created', s.name);
            completeToast(tid3, s.name, false);
            const item = event.target.closest('.tpl-item');
            if (item) { item.style.opacity = '0.4'; item.querySelector('.tpl-actions').innerHTML = '<span class="muted">Created</span>'; }
            loadTemplates();
        }
    } catch (e) { alert('Error: ' + e.message); }
}

async function acceptAllSuggestions() {
    const suggestions = window._pendingSuggestions || [];
    let created = 0;
    for (const s of suggestions) {
        try {
            const res = await fetch('/api/templates', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: s.name, description: s.description, tag_filter: s.tag_filter, key_filter: s.key_filter, budget: s.budget})
            });
            if (res.ok) created++;
        } catch (e) { /* skip */ }
    }
    closeModal();
    const tid2 = showToast('Creating templates', `${created}/${suggestions.length}`);
    completeToast(tid2, `${created}/${suggestions.length} templates created`, false);
    loadTemplates();
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
    const tid = showToast(`Assembling "${name}"`, 'Filtering, weighting, compressing...');
    botBusy();
    try {
        const res = await fetch(`/api/templates/${encodeURIComponent(name)}/assemble`, { method: 'POST' });
        const d = await res.json();
        completeToast(tid, `${d.used_tokens}/${d.budget} tokens, ${d.block_count}/${d.total_matching} blocks`, false);
        showAssemblyResult(d);
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
            fetch(memoryUrl(key) + '/versions')
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
        await fetch(memoryUrl(key) + `/pin?pinned=${pinned}`, { method: 'POST' });
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

let gsSelectedIndex = -1;
let gsItems = [];

function openGlobalSearch() {
    const overlay = document.getElementById('global-search-overlay');
    overlay.classList.add('active');
    const input = document.getElementById('global-search-input');
    input.value = '';
    input.focus();
    gsSelectedIndex = -1;
    gsItems = [];
    document.getElementById('global-search-results').innerHTML =
        '<div class="global-search-hint">Type to search memories, templates, connectors...</div>';

    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeGlobalSearch();
    });

    input.addEventListener('keydown', globalSearchKeyNav);
}

function closeGlobalSearch() {
    const input = document.getElementById('global-search-input');
    if (input) input.removeEventListener('keydown', globalSearchKeyNav);
    document.getElementById('global-search-overlay').classList.remove('active');
    gsSelectedIndex = -1;
    gsItems = [];
}

function globalSearchKeyNav(e) {
    const el = document.getElementById('global-search-results');
    const items = el.querySelectorAll('.global-search-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        gsSelectedIndex = Math.min(gsSelectedIndex + 1, items.length - 1);
        updateGsSelection(items);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        gsSelectedIndex = Math.max(gsSelectedIndex - 1, 0);
        updateGsSelection(items);
    } else if (e.key === 'Enter' && gsSelectedIndex >= 0 && gsSelectedIndex < gsItems.length) {
        e.preventDefault();
        const item = gsItems[gsSelectedIndex];
        globalSearchSelect(item.type, item.label);
    }
}

function updateGsSelection(items) {
    items.forEach((it, i) => {
        it.classList.toggle('gs-selected', i === gsSelectedIndex);
    });
    if (items[gsSelectedIndex]) {
        items[gsSelectedIndex].scrollIntoView({ block: 'nearest' });
    }
}

async function globalSearch() {
    const q = document.getElementById('global-search-input').value.trim();
    const el = document.getElementById('global-search-results');
    if (!q) {
        el.innerHTML = '<div class="global-search-hint">Type to search memories, templates, connectors...</div>';
        gsItems = [];
        gsSelectedIndex = -1;
        return;
    }

    clearTimeout(debounceTimers['globalSearch']);
    debounceTimers['globalSearch'] = setTimeout(async () => {
        try {
            const res = await fetch(`/api/global-search?q=${encodeURIComponent(q)}`);
            const d = await res.json();

            // Build grouped results
            const groups = [
                { key: 'Memories', items: (d.memories || []).map(m => ({ type: 'memory', label: m.key, detail: m.preview })) },
                { key: 'Templates', items: (d.templates || []).map(t => ({ type: 'template', label: t.name, detail: t.description })) },
                { key: 'Connectors', items: (d.connectors || []).map(c => ({ type: 'connector', label: c.display_name || c.name, detail: '' })) },
                { key: 'Folders', items: (d.folders || []).map(f => ({ type: 'folder', label: f.name, detail: f.path })) },
            ];

            gsItems = [];
            let html = '';
            groups.forEach(g => {
                if (!g.items.length) return;
                html += `<div class="global-search-group-label">${g.key} (${g.items.length})</div>`;
                g.items.forEach(item => {
                    const idx = gsItems.length;
                    gsItems.push(item);
                    html += `<div class="global-search-item" data-gs-idx="${idx}" onclick="globalSearchSelect('${escapeAttr(item.type)}', '${escapeAttr(item.label)}')">
                        <span class="global-search-type">${item.type}</span>
                        <div style="flex:1;min-width:0;">
                            <div style="font-weight:500;">${escapeHtml(item.label)}</div>
                            ${item.detail ? '<div style="font-size:11px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(item.detail) + '</div>' : ''}
                        </div>
                    </div>`;
                });
            });

            if (gsItems.length === 0) {
                el.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);">No results</div>';
            } else {
                el.innerHTML = html;
            }
            gsSelectedIndex = -1;
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
// SETTINGS
// ═══════════════════════════════════════════════════════════════

async function loadSettings() {
    loadMcpSettings();
    loadDbStats();
    loadSchedulerSettings();
    loadSystemInfo();
}

async function loadMcpSettings() {
    showSkeleton('settings-mcp-status', {rows: 1, type: 'list'});
    try {
        const res = await fetch('/api/mcp-status');
        const mcp = await res.json();
        const el = document.getElementById('settings-mcp-status');
        const actions = document.getElementById('settings-mcp-actions');

        if (mcp.registered) {
            const url = mcp.config?.url || 'unknown';
            const type = mcp.config?.type || 'sse';
            el.innerHTML = `
                <div class="memory-item" style="cursor:default;border-left:3px solid var(--success);">
                    <div class="main">
                        <div class="key"><span class="badge" style="background:var(--success-light);color:var(--success);">registered</span> Context Pilot MCP</div>
                        <div class="meta">
                            <span class="age">Type: ${escapeHtml(type)}</span>
                            <span class="age">URL: ${escapeHtml(url)}</span>
                        </div>
                    </div>
                </div>`;
            actions.innerHTML = `
                <button class="btn btn-small btn-danger" onclick="mcpDeregister()">Deregister</button>`;
        } else {
            el.innerHTML = `
                <div class="memory-item" style="cursor:default;border-left:3px solid var(--text-muted);">
                    <div class="main">
                        <div class="key"><span class="badge" style="background:var(--surface-alt);color:var(--text-muted);">not registered</span> MCP Server</div>
                        <div class="meta"><span class="age">Not registered in ~/.claude.json. Register to connect Claude Code.</span></div>
                    </div>
                </div>`;
            actions.innerHTML = `
                <button class="btn btn-small btn-primary" onclick="showMcpRegisterDialog()">Register</button>`;
        }
    } catch (e) { console.error(e); }
}

function showMcpRegisterDialog() {
    openModal('Register MCP Server', `
        <p style="margin-bottom:16px;color:var(--text-secondary);">Register the Context Pilot MCP server in <code>~/.claude.json</code> so Claude Code can access your memories.</p>
        <label>Port</label>
        <input type="number" id="mcp-reg-port" value="8400" min="1" max="65535">
        <label style="margin-top:12px;">Transport</label>
        <select id="mcp-reg-transport" style="width:100%;">
            <option value="sse">SSE (Server-Sent Events)</option>
            <option value="streamable-http">Streamable HTTP</option>
        </select>
    `, `
        <button class="btn btn-primary" onclick="mcpRegister()">Register</button>
        <button class="btn" onclick="closeModal()">Cancel</button>
    `);
}

async function mcpRegister() {
    const port = parseInt(document.getElementById('mcp-reg-port').value) || 8400;
    const transport = document.getElementById('mcp-reg-transport').value;
    const tid = showToast('Registering MCP', `Port ${port}...`);
    try {
        const res = await fetch('/api/mcp/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({port, transport})
        });
        if (res.ok) {
            completeToast(tid, 'MCP registered', false);
            closeModal();
            loadMcpSettings();
            loadDashboard();
        } else {
            completeToast(tid, 'Failed', true);
        }
    } catch (e) { completeToast(tid, 'Error: ' + e.message, true); }
}

async function mcpDeregister() {
    if (!confirm('Deregister MCP server from ~/.claude.json?')) return;
    const tid = showToast('Deregistering MCP', '...');
    try {
        await fetch('/api/mcp/deregister', {method: 'POST'});
        completeToast(tid, 'MCP deregistered', false);
        loadMcpSettings();
        loadDashboard();
    } catch (e) { completeToast(tid, 'Error: ' + e.message, true); }
}

async function loadDbStats() {
    showSkeleton('settings-db-stats', {rows: 6, type: 'cards'});
    try {
        const res = await fetch('/api/maintenance/db-stats');
        const d = await res.json();
        const el = document.getElementById('settings-db-stats');
        el.innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;">
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Data Dir</div><div style="font-size:11px;word-break:break-all;color:var(--text-secondary);">${escapeHtml(d.data_dir)}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">DB Size</div><div class="card-value" style="font-size:18px;">${d.db_size_mb} MB</div>${d.embeddings_size_mb ? '<div style="font-size:10px;color:var(--text-muted);margin-top:2px;">Embeddings: ' + d.embeddings_size_mb + ' MB</div>' : ''}</div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Memories</div><div class="card-value" style="font-size:18px;">${d.memory_count}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Schema</div><div class="card-value" style="font-size:18px;">v${d.schema_version}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Fragmentation</div><div class="card-value" style="font-size:18px;">${d.fragmentation_pct}%</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Disk Free</div><div class="card-value" style="font-size:18px;">${d.disk_free_gb != null ? d.disk_free_gb + ' GB' : 'n/a'}</div></div>
            </div>`;
    } catch (e) { console.error(e); }
}

async function vacuumDb() {
    const tid = showToast('Compacting database', '...');
    try {
        await fetch('/api/maintenance/vacuum', {method: 'POST'});
        completeToast(tid, 'Database compacted', false);
        loadDbStats();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function rebuildFts() {
    const tid = showToast('Rebuilding search index', '...');
    try {
        await fetch('/api/maintenance/rebuild-fts', {method: 'POST'});
        completeToast(tid, 'Search index rebuilt', false);
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function cleanupTrash() {
    const tid = showToast('Cleaning up trash', '...');
    try {
        const res = await fetch('/api/maintenance/trash-cleanup?days=30', {method: 'POST'});
        const d = await res.json();
        completeToast(tid, `${d.removed} old trash entries removed`, false);
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function cleanupExpired() {
    const tid = showToast('Cleaning expired memories', '...');
    try {
        const res = await fetch('/api/memories/cleanup-expired', {method: 'POST'});
        const d = await res.json();
        completeToast(tid, `${d.removed} expired memories removed`, false);
        loadDbStats();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function purgeAllTrash() {
    if (!confirm('Permanently delete ALL items in trash? This cannot be undone.')) return;
    const tid = showToast('Purging trash', '...');
    try {
        const res = await fetch('/api/trash/purge', {method: 'DELETE'});
        const d = await res.json();
        completeToast(tid, `${d.purged || 0} items purged`, false);
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function deleteAllMemories() {
    const phrase = prompt('Type "DELETE ALL" to confirm deletion of ALL memories:');
    if (phrase !== 'DELETE ALL') return;
    const tid = showToast('Deleting all memories', '...');
    try {
        const store = await fetch('/api/memories?page_size=1');
        const d = await store.json();
        const total = d.total;
        // Fetch all keys
        const allRes = await fetch(`/api/memories?page_size=${total}`);
        const all = await allRes.json();
        const keys = all.memories.map(m => m.key);
        await fetch('/api/memories/bulk-delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(keys)
        });
        completeToast(tid, `${keys.length} memories deleted`, false);
        loadDbStats();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function loadSchedulerSettings() {
    showSkeleton('settings-scheduler-status', {rows: 1, type: 'list'});
    try {
        const res = await fetch('/api/scheduler');
        const s = await res.json();
        const el = document.getElementById('settings-scheduler-status');
        const actions = document.getElementById('settings-scheduler-actions');
        const lastRun = s.last_run ? new Date(s.last_run * 1000).toLocaleString() : 'never';

        el.innerHTML = `
            <div class="memory-item" style="cursor:default;border-left:3px solid ${s.running ? 'var(--success)' : 'var(--text-muted)'};">
                <div class="main">
                    <div class="key">
                        <span class="badge" style="background:${s.running ? 'var(--success-light)' : 'var(--surface-alt)'};color:${s.running ? 'var(--success)' : 'var(--text-muted)'};">${s.running ? 'running' : 'stopped'}</span>
                        Auto-Sync
                    </div>
                    <div class="meta">
                        <span class="age">Interval: ${s.interval_minutes}m</span>
                        <span class="age">Last run: ${lastRun}</span>
                    </div>
                </div>
            </div>`;

        if (s.running) {
            actions.innerHTML = `
                <button class="btn btn-small" onclick="schedulerRunNow()">Run Now</button>
                <button class="btn btn-small btn-danger" onclick="schedulerStop()">Stop</button>`;
        } else {
            actions.innerHTML = `
                <input type="number" id="sched-interval" value="30" min="1" max="1440" style="width:60px;padding:4px 8px;font-size:12px;" title="Interval in minutes">
                <button class="btn btn-small btn-primary" onclick="schedulerStart()">Start</button>`;
        }
    } catch (e) { console.error(e); }
}

async function schedulerStart() {
    const interval = parseInt(document.getElementById('sched-interval')?.value || '30');
    await fetch(`/api/scheduler/start?interval=${interval}`, {method: 'POST'});
    loadSchedulerSettings();
}

async function schedulerStop() {
    await fetch('/api/scheduler/stop', {method: 'POST'});
    loadSchedulerSettings();
}

async function schedulerRunNow() {
    const tid = showToast('Running sync', '...');
    try {
        const res = await fetch('/api/scheduler/run-now', {method: 'POST'});
        const d = await res.json();
        completeToast(tid, 'Sync complete', false);
        loadSchedulerSettings();
    } catch (e) { completeToast(tid, 'Failed', true); }
}

async function loadSystemInfo() {
    showSkeleton('settings-system-info', {rows: 6, type: 'cards'});
    try {
        const res = await fetch('/health');
        const h = await res.json();
        const el = document.getElementById('settings-system-info');
        el.innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;">
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Version</div><div class="card-value" style="font-size:16px;">${escapeHtml(h.version)}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Uptime</div><div class="card-value" style="font-size:16px;">${escapeHtml(h.uptime)}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Python</div><div class="card-value" style="font-size:16px;">${escapeHtml(h.python)}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Platform</div><div class="card-value" style="font-size:14px;">${escapeHtml(h.platform)}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">PID</div><div class="card-value" style="font-size:16px;">${h.pid}</div></div>
                <div class="status-card" style="padding:10px;"><div class="card-title" style="font-size:10px;">Requests</div><div class="card-value" style="font-size:16px;">${h.requests?.total || 0}</div></div>
            </div>`;
    } catch (e) { console.error(e); }
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

// ═══════════════════════════════════════════════════════════════
// NOTIFICATION TOASTS (simple type-based)
// ═══════════════════════════════════════════════════════════════

const _toastIcons = { success: '\u2713', error: '!', warning: '\u26A0', info: '\u2139' };

function notify(message, type = 'info', duration = 3000) {
    const container = document.getElementById('progress-toast');
    if (!container) return;
    const id = 'notify-' + (++toastCounter);
    const icon = _toastIcons[type] || _toastIcons.info;
    const html = `<div class="toast toast-${type}" id="${id}">
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" onclick="this.closest('.toast').style.animation='toastOut 0.3s ease forwards';setTimeout(()=>document.getElementById('${id}')?.remove(),300)">&times;</button>
    </div>`;
    container.insertAdjacentHTML('beforeend', html);
    if (duration > 0) {
        setTimeout(() => {
            const el = document.getElementById(id);
            if (el) {
                el.style.animation = 'toastOut 0.3s ease forwards';
                setTimeout(() => el.remove(), 300);
            }
        }, duration);
    }
}

// ═══════════════════════════════════════════════════════════════
// BUTTON LOADING STATE
// ═══════════════════════════════════════════════════════════════

async function withLoading(btn, asyncFn) {
    if (!btn || btn.classList.contains('btn-loading')) return;
    btn.classList.add('btn-loading');
    btn.disabled = true;
    const spinner = document.getElementById('header-ops-spinner');
    if (spinner) spinner.classList.add('active');
    try {
        return await asyncFn();
    } finally {
        btn.classList.remove('btn-loading');
        btn.disabled = false;
        if (spinner) spinner.classList.remove('active');
    }
}

// ═══════════════════════════════════════════════════════════════
// EVENT BADGE (counts SSE events since last dashboard view)
// ═══════════════════════════════════════════════════════════════

let _eventBadgeCount = 0;

function incrementEventBadge() {
    const activeTab = document.querySelector('.tab.active')?.dataset?.tab;
    if (activeTab === 'dashboard') return;
    _eventBadgeCount++;
    const badge = document.getElementById('event-badge');
    if (badge) {
        badge.textContent = _eventBadgeCount > 99 ? '99+' : _eventBadgeCount;
        badge.classList.remove('pulse');
        void badge.offsetWidth;
        badge.classList.add('pulse');
    }
}

function resetEventBadge() {
    _eventBadgeCount = 0;
    const badge = document.getElementById('event-badge');
    if (badge) badge.textContent = '';
}

// Bot animation
let botTimer = null;
function botBusy() {
    const bot = document.getElementById('header-bot');
    if (bot) { bot.classList.add('speaking', 'busy'); }
    const spinner = document.getElementById('header-ops-spinner');
    if (spinner) spinner.classList.add('active');
    clearTimeout(botTimer);
}
function botIdle() {
    clearTimeout(botTimer);
    botTimer = setTimeout(() => {
        const bot = document.getElementById('header-bot');
        if (bot) { bot.classList.remove('speaking', 'busy'); }
        const spinner = document.getElementById('header-ops-spinner');
        if (spinner) spinner.classList.remove('active');
    }, 400);
}

function setBotState(state) {
    const bot = document.getElementById('header-bot');
    if (!bot) return;
    bot.classList.remove('speaking', 'busy', 'error', 'connected');
    if (state) bot.classList.add(state);
}

// Skeleton loading
function showSkeleton(elementId, opts = {}) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const rows = opts.rows || 3;
    const type = opts.type || 'list';
    let html = '<div class="skeleton-container">';
    if (type === 'cards') {
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;">';
        for (let i = 0; i < rows; i++) {
            html += '<div class="skeleton skeleton-card"></div>';
        }
        html += '</div>';
    } else if (type === 'list') {
        for (let i = 0; i < rows; i++) {
            const w = 40 + Math.random() * 50;
            html += `<div class="skeleton-row">
                <div class="skeleton skeleton-block" style="flex:1;"></div>
            </div>`;
        }
    } else if (type === 'text') {
        for (let i = 0; i < rows; i++) {
            const w = 50 + Math.random() * 40;
            html += `<div class="skeleton skeleton-line" style="width:${w}%;"></div>`;
        }
    }
    html += '</div>';
    el.innerHTML = html;
}

function contentLoaded(elementId) {
    const el = document.getElementById(elementId);
    if (el) el.classList.add('content-loaded');
}

// ═══════════════════════════════════════════════════════════════
// FLOATING ACTION BUTTON (FAB)
// ═══════════════════════════════════════════════════════════════

function updateFabVisibility(tabName) {
    const fab = document.getElementById('fab-container');
    if (!fab) return;
    const show = (tabName === 'dashboard' || tabName === 'memories');
    fab.style.display = show ? 'flex' : 'none';
    if (!show) fab.classList.remove('open');
}

function toggleFab() {
    const fab = document.getElementById('fab-container');
    if (fab) fab.classList.toggle('open');
}

function fabAction(action) {
    const fab = document.getElementById('fab-container');
    if (fab) fab.classList.remove('open');

    if (action === 'memory') {
        showTab('memories', null);
        setTimeout(() => openNewMemoryModal(), 100);
    } else if (action === 'import') {
        showTab('dashboard', null);
        setTimeout(() => {
            const importPanel = document.querySelector('[data-import="claude-md"]');
            if (importPanel) importPanel.closest('.panel')?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
    } else if (action === 'search') {
        openGlobalSearch();
    }
}

// Close FAB when clicking outside
document.addEventListener('click', e => {
    const fab = document.getElementById('fab-container');
    if (fab && fab.classList.contains('open') && !fab.contains(e.target)) {
        fab.classList.remove('open');
    }
});

// ═══════════════════════════════════════════════════════════════
// OPERATION STATUS BAR
// ═══════════════════════════════════════════════════════════════

function showOperation(id, message) {
    const bar = document.getElementById('ops-bar');
    if (!bar) return;
    let item = document.getElementById('ops-' + id);
    if (item) {
        item.querySelector('.ops-text').textContent = message;
        return;
    }
    const html = `<div class="ops-item" id="ops-${escapeAttr(id)}">
        <div class="ops-spinner"></div>
        <span class="ops-text">${escapeHtml(message)}</span>
    </div>`;
    bar.insertAdjacentHTML('beforeend', html);
}

function hideOperation(id) {
    const item = document.getElementById('ops-' + id);
    if (!item) return;
    item.style.animation = 'opsSlideOut 0.25s ease forwards';
    setTimeout(() => item.remove(), 250);
}

// ═══════════════════════════════════════════════════════════════
// TAG COLOR CODING
// ═══════════════════════════════════════════════════════════════

let _topTagColors = {};

function updateTagColors(tags) {
    if (!tags || !tags.length) return;
    _topTagColors = {};
    const sorted = [...tags].sort((a, b) => (b.count || 0) - (a.count || 0));
    sorted.slice(0, 5).forEach((t, i) => {
        _topTagColors[t.tag || t] = i;
    });
}

function getTagColorClass(tag) {
    if (tag in _topTagColors) return ' tag-color-' + _topTagColors[tag];
    return '';
}

// ═══════════════════════════════════════════════════════════════
// RELATIVE TIME FORMATTING
// ═══════════════════════════════════════════════════════════════

function relativeTime(ts) {
    if (!ts) return '';
    const now = Date.now() / 1000;
    const delta = now - ts;
    if (delta < 60) return 'gerade eben';
    if (delta < 3600) return Math.floor(delta / 60) + ' Min.';
    if (delta < 86400) return Math.floor(delta / 3600) + ' Std.';
    if (delta < 604800) return Math.floor(delta / 86400) + ' Tage';
    if (delta < 2592000) return Math.floor(delta / 604800) + ' Wochen';
    return Math.floor(delta / 2592000) + ' Monate';
}
