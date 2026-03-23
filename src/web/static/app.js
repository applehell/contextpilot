// Context Pilot — Frontend Logic

let debounceTimers = {};
let bulkMode = false;
let blockIndex = 1;
let graphNetwork = null;
let graphDataCache = null;
let graphNodesDataSet = null;
let secretsData = null;

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════

function init() {
    // Tab delegation
    document.querySelectorAll('.tab[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => showTab(btn.dataset.tab, btn));
    });

    // Modal close
    document.getElementById('modal-close-btn').addEventListener('click', closeModal);
    document.getElementById('modal-overlay').addEventListener('click', e => {
        if (e.target === e.currentTarget) closeModal();
    });

    // Import handlers
    document.querySelectorAll('[data-import]').forEach(input => {
        input.addEventListener('change', () => importFile(input, input.dataset.import));
    });

    // Welcome screen
    checkWelcome();

    // Initial load
    loadProfiles();
    loadDashboard();
}

function checkWelcome() {
    const dismissed = localStorage.getItem('cp-welcome-dismissed');
    if (!dismissed) {
        document.getElementById('welcome-overlay').classList.add('active');
    }
}

function dismissWelcome() {
    localStorage.setItem('cp-welcome-dismissed', '1');
    document.getElementById('welcome-overlay').classList.remove('active');
}

function showWelcomeForNewProfile(profileName) {
    const overlay = document.getElementById('welcome-overlay');
    const card = overlay.querySelector('.welcome-card');
    card.querySelector('h2').textContent = 'Profil "' + profileName + '" erstellt';
    card.querySelector('p').textContent = 'Dein neues Profil ist bereit. Starte mit dem Import von Wissen oder lege direkt Memories an.';
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

        // Activity
        const actEl = document.getElementById('dash-activity');
        if (!d.activity.length) {
            actEl.innerHTML = '<p class="muted">Keine Aktivitaet</p>';
        } else {
            actEl.innerHTML = d.activity.map(e => {
                const color = OP_COLORS[e.operation] || 'var(--text-muted)';
                const detail = e.detail ? ' — ' + escapeHtml(e.detail) : '';
                return `<div class="activity-item">
                    <span class="activity-op" style="color:${color};">${e.operation.toUpperCase()}</span>
                    <span class="activity-key">${escapeHtml(e.memory_key)}</span>
                    <span class="activity-detail">${detail}</span>
                    <span class="activity-age">${escapeHtml(e.age)}</span>
                </div>`;
            }).join('');
        }
    } catch (e) { console.error('Dashboard load failed:', e); } finally { botIdle(); }

    // MCP status
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
            mcpDetail.textContent = 'Nicht in Claude registriert';
        }
    } catch (e) {}
}

// ═══════════════════════════════════════════════════════════════
// CONTEXT PREVIEW
// ═══════════════════════════════════════════════════════════════

async function previewContext() {
    const budget = parseInt(document.getElementById('preview-budget').value) || 8000;
    const el = document.getElementById('preview-result');
    el.innerHTML = '<p class="muted">Assembliere...</p>';

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
                ${d.block_count} Blocks eingeschlossen | ${d.dropped_count} gedroppt | ${d.input_count} total
            </div>`;

        if (d.blocks.length > 0) {
            html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:8px 0 4px;">Eingeschlossen:</div>';
            d.blocks.forEach(b => {
                const hint = b.compress_hint ? ` | ${b.compress_hint}` : '';
                html += `<div class="result-block priority-${b.priority}">
                    <div class="meta">${b.priority.toUpperCase()} | ${b.token_count} tokens${hint}</div>
                    <pre>${escapeHtml(b.content.substring(0, 200))}${b.content.length > 200 ? '...' : ''}</pre>
                </div>`;
            });
        }

        if (d.dropped.length > 0) {
            html += '<div style="font-size:11px;font-weight:600;color:var(--text-muted);margin:8px 0 4px;">Gedroppt:</div>';
            d.dropped.forEach(b => {
                html += `<div class="result-block dropped">
                    <div class="meta">${b.token_count} tokens (dropped)</div>
                    <pre>${escapeHtml(b.content_preview)}</pre>
                </div>`;
            });
        }

        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = '<p style="color:var(--danger);">Fehler: ' + escapeHtml(e.message) + '</p>';
    }
}

// ═══════════════════════════════════════════════════════════════
// SKILLS
// ═══════════════════════════════════════════════════════════════

function renderSkillCard(s) {
    const alive = s.is_alive !== false && s.status !== 'stale';
    const hints = (s.context_hints || []).slice(0, 6);
    const hintsHtml = hints.length
        ? hints.map(h => `<span class="skill-hint">${escapeHtml(h)}</span>`).join('')
        : '<span class="muted">keine hints</span>';
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
            list.innerHTML = '<p class="muted">Keine Skills verbunden</p>';
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
    try {
        const [memRes, tagRes] = await Promise.all([
            fetch('/api/memories'),
            fetch('/api/memory-tags'),
        ]);
        const data = await memRes.json();
        const tags = await tagRes.json();
        renderMemories(data);
        renderTagFilter(tags);
    } catch (e) { console.error(e); } finally { botIdle(); }
}

function renderTagFilter(tags) {
    const sel = document.getElementById('memory-tag-filter');
    const current = sel.value;
    sel.innerHTML = '<option value="">Alle Tags</option>';
    tags.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        if (t === current) opt.selected = true;
        sel.appendChild(opt);
    });
}

async function filterByTag() {
    const tag = document.getElementById('memory-tag-filter').value;
    const q = document.getElementById('memory-search').value.trim();
    try {
        let url = '/api/memories/search?q=' + encodeURIComponent(q);
        if (tag) url += '&tags=' + encodeURIComponent(tag);
        const res = await fetch(url);
        const data = await res.json();
        renderMemories(data);
    } catch (e) { console.error(e); }
}

function renderMemories(data) {
    const list = document.getElementById('memory-list');
    const countEl = document.getElementById('memory-count');
    if (countEl) countEl.textContent = `${data.length} memories`;

    if (data.length === 0) {
        list.innerHTML = '<div class="empty-state">Keine Memories gefunden.</div>';
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
        if (isNew) badge = '<span class="badge badge-new">NEU</span> ';
        else if (isModified) badge = '<span class="badge badge-upd">UPD</span> ';

        let age = '';
        const ts = m.updated_at || m.created_at;
        if (ts) {
            const delta = now - ts;
            if (delta < 3600) age = `vor ${Math.floor(delta / 60)} Min`;
            else if (delta < 86400) age = `vor ${Math.floor(delta / 3600)} Std`;
            else age = `vor ${Math.floor(delta / 86400)} Tagen`;
        }

        const stateClass = isNew ? ' new' : isModified ? ' updated' : '';
        const cbHtml = bulkMode ? `<input type="checkbox" class="bulk-cb" data-key="${escapeAttr(m.key)}">` : '';
        const tagsHtml = m.tags.length
            ? m.tags.map(t => `<span class="tag" onclick="event.stopPropagation();clickTag('${escapeAttr(t)}')">#${escapeHtml(t)}</span>`).join(' ')
            : '';

        return `<div class="memory-item${stateClass}" onclick="viewMemory('${escapeAttr(m.key)}')">
            ${cbHtml}
            <div class="main">
                <div class="key">${badge}${escapeHtml(m.key)}</div>
                <div class="preview">${escapeHtml((m.value || '').substring(0, 150))}</div>
                <div class="meta">
                    ${tagsHtml}
                    ${age ? '<span class="age">' + age + '</span>' : ''}
                </div>
            </div>
            <div class="actions" onclick="event.stopPropagation()">
                <button class="btn btn-small" onclick="editMemory('${escapeAttr(m.key)}')">Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteMemory('${escapeAttr(m.key)}')">Del</button>
            </div>
        </div>`;
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
    document.getElementById('modal-overlay').classList.remove('active');
    document.body.style.overflow = '';
}

async function viewMemory(key) {
    try {
        const res = await fetch(memoryUrl(key));
        if (!res.ok) return;
        const m = await res.json();
        const tagsHtml = m.tags.length
            ? m.tags.map(t => `<span class="tag" onclick="event.stopPropagation();clickTag('${escapeAttr(t)}');closeModal();">#${escapeHtml(t)}</span>`).join(' ')
            : '<span class="muted">keine</span>';

        openModal(m.key, `
            <label>Tags</label>
            <div style="margin-bottom:16px;">${tagsHtml}</div>
            <label>Inhalt</label>
            <pre>${escapeHtml(m.value)}</pre>
        `, `
            <button class="btn btn-primary" onclick="editMemory('${escapeAttr(m.key)}')">Bearbeiten</button>
            <button class="btn" onclick="closeModal()">Schliessen</button>
        `);
    } catch (e) { console.error(e); }
}

async function editMemory(key) {
    try {
        const res = await fetch(memoryUrl(key));
        if (!res.ok) return;
        const m = await res.json();

        openModal('Bearbeiten: ' + m.key, `
            <label>Key</label>
            <input type="text" id="edit-key" value="${escapeHtml(m.key)}" readonly style="background:var(--surface-alt);cursor:not-allowed;">
            <label>Value</label>
            <textarea id="edit-value" rows="14">${escapeHtml(m.value)}</textarea>
            <label>Tags (kommagetrennt)</label>
            <input type="text" id="edit-tags" value="${escapeHtml(m.tags.join(', '))}">
        `, `
            <button class="btn btn-primary" id="save-memory-btn">Speichern</button>
            <button class="btn" id="cancel-memory-btn">Abbrechen</button>
        `);

        document.getElementById('save-memory-btn').addEventListener('click', () => saveEditedMemory(m.key));
        document.getElementById('cancel-memory-btn').addEventListener('click', closeModal);
    } catch (e) { console.error(e); }
}

async function saveEditedMemory(key) {
    const value = document.getElementById('edit-value').value;
    const tagsStr = document.getElementById('edit-tags').value;
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
    try {
        const res = await fetch(memoryUrl(key), {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value, tags})
        });
        if (res.ok) {
            closeModal();
            loadMemories();
        } else {
            alert('Fehler beim Speichern: ' + res.status);
        }
    } catch (e) { alert('Fehler: ' + e.message); }
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
    if (!confirm(`"${key}" loeschen?`)) return;
    try {
        await fetch(memoryUrl(key), {method: 'DELETE'});
        loadMemories();
    } catch (e) { console.error(e); }
}

async function searchMemories() {
    clearTimeout(debounceTimers['memSearch']);
    debounceTimers['memSearch'] = setTimeout(() => filterByTag(), 300);
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
    document.getElementById('bulk-toggle-btn').textContent = bulkMode ? 'Abbrechen' : 'Auswahl';
    loadMemories();
}

async function bulkDeleteSelected() {
    const checked = document.querySelectorAll('.bulk-cb:checked');
    if (checked.length === 0) { alert('Keine Memories ausgewaehlt.'); return; }
    const keys = Array.from(checked).map(cb => cb.dataset.key);
    if (!confirm(`${keys.length} Memories loeschen?`)) return;
    try {
        await fetch('/api/memories/bulk-delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(keys)
        });
        loadMemories();
    } catch (e) { console.error(e); }
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
    <textarea class="block-content" rows="4" placeholder="Block-Inhalt eingeben..."
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
    if (!hint) { alert('Waehle zuerst einen Compress Hint aus.'); return; }

    try {
        const res = await fetch('/api/test-compress', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content, compress_hint: hint})
        });
        const d = await res.json();
        if (d.error) { alert(d.error); return; }

        const panel = document.getElementById('compress-result');
        panel.style.display = 'block';
        document.getElementById('compress-meta').innerHTML =
            `<strong>${hint}</strong>: ${d.original_tokens} → ${d.compressed_tokens} tokens ` +
            `(<span style="color:var(--success);">-${d.savings_pct}%</span>)`;
        document.getElementById('compress-preview').textContent = d.compressed_content;
        panel.scrollIntoView({ behavior: 'smooth' });
    } catch (e) { console.error(e); }
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

    try {
        const res = await fetch('/api/assemble', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({blocks, budget})
        });
        const data = await res.json();
        showAssemblyResult(data);
    } catch (e) { console.error('Assembly failed:', e); }
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
                    : '<span class="muted">keine</span>';
                detail.innerHTML = `
                    <div style="font-weight:600;font-size:14px;margin-bottom:6px;">${escapeHtml(node.id)}</div>
                    <div style="color:var(--text-secondary);margin-bottom:8px;">Gruppe: ${escapeHtml(node.group)}</div>
                    <div style="margin-bottom:8px;">Tags: ${tagHtml}</div>
                    <button class="btn btn-small" onclick="fetchMemoryDetail('${escapeAttr(node.id)}')">Inhalt laden</button>
                    <div id="graph-memory-content" style="margin-top:8px;"></div>`;
            }
        } else {
            detail.style.display = 'none';
        }
    });

    document.getElementById('graph-stats').textContent =
        `${data.stats.total_memories} Memories | ${data.stats.total_groups} Gruppen | ${data.stats.total_edges} Verbindungen`;

    const legend = document.getElementById('graph-legend');
    legend.innerHTML = '<div style="font-weight:600;margin-bottom:4px;">Gruppen</div>' +
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
        el.innerHTML = '<span style="color:var(--danger);">Fehler</span>';
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
    countEl.textContent = matchCount + ' Treffer';

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

// ═══════════════════════════════════════════════════════════════
// IMPORT
// ═══════════════════════════════════════════════════════════════

async function importFile(input, type) {
    const file = input.files[0];
    if (!file) return;
    const statusEl = document.getElementById('import-status');
    statusEl.textContent = 'Importiere...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`/api/import/${type}`, { method: 'POST', body: formData });
        const d = await res.json();
        if (d.status === 'imported') {
            statusEl.textContent = `${d.count} memories importiert aus ${d.filename}`;
            loadDashboard();
        } else {
            statusEl.textContent = d.message || 'Import fehlgeschlagen';
        }
    } catch (e) {
        statusEl.textContent = 'Fehler: ' + e.message;
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
            opt.value = p.name;
            opt.textContent = `${p.name} (${p.memory_count})`;
            if (p.is_active) opt.selected = true;
            sel.appendChild(opt);
        });
        const active = d.profiles.find(p => p.is_active);
        const notDefault = active && !active.is_default;
        document.getElementById('profile-delete-btn').style.display = notDefault ? '' : 'none';
        document.getElementById('profile-rename-btn').style.display = notDefault ? '' : 'none';
    } catch (e) { console.error(e); }
}

async function switchProfile() {
    const name = document.getElementById('profile-select').value;
    try {
        await fetch(`/api/profiles/${encodeURIComponent(name)}/switch`, { method: 'POST' });
        loadProfiles();
        const activeTab = document.querySelector('.tab.active');
        if (activeTab) showTab(activeTab.dataset.tab, activeTab);
    } catch (e) { console.error(e); }
}

async function showNewProfileDialog() {
    // Lade Profile-Liste fuer "Wissen uebernehmen"-Dropdown
    let profiles = [];
    try {
        const res = await fetch('/api/profiles');
        const d = await res.json();
        profiles = d.profiles;
    } catch (e) { console.error(e); }

    // Lade Tags des aktuell aktiven Profils
    let allTags = [];
    try {
        const res = await fetch('/api/memory-tags');
        allTags = await res.json();
    } catch (e) {}

    const profileOpts = profiles.map(p =>
        `<option value="${escapeAttr(p.name)}">${escapeHtml(p.name)} (${p.memory_count})</option>`
    ).join('');

    openModal('Neues Profil erstellen', `
        <label>Name</label>
        <input type="text" id="new-profile-name" placeholder="Alphanumerisch, -, _">
        <label>Beschreibung</label>
        <input type="text" id="new-profile-desc" placeholder="Optional">
        <label style="margin-top:12px;">Wissen uebernehmen von</label>
        <select id="new-profile-source" onchange="toggleCopyTags()" style="width:100%;">
            <option value="">— Leeres Profil —</option>
            ${profileOpts}
        </select>
        <div id="copy-tags-section" style="display:none;margin-top:12px;">
            <label>Nur bestimmte Tags (leer = alle)</label>
            <input type="text" id="new-profile-tags" placeholder="z.B. smarthome, netzwerk">
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Kommagetrennt. Vorhandene Tags im Quellprofil werden nach Auswahl geladen.</div>
            <div id="available-tags" style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;"></div>
        </div>
    `, `
        <button class="btn btn-primary" id="create-profile-btn">Erstellen</button>
        <button class="btn" onclick="closeModal()">Abbrechen</button>
    `);

    document.getElementById('create-profile-btn').addEventListener('click', submitNewProfile);
}

function toggleCopyTags() {
    const source = document.getElementById('new-profile-source').value;
    const section = document.getElementById('copy-tags-section');
    section.style.display = source ? '' : 'none';

    if (source) {
        loadSourceTags(source);
    }
}

async function loadSourceTags(profileName) {
    const container = document.getElementById('available-tags');
    container.innerHTML = '';

    // Tags aus dem Quellprofil laden — dazu kurz auf das Profil wechseln und zurueck
    // Einfacher: Tags direkt aus der DB holen via neuen Endpoint oder den vorhandenen nutzen
    // Wir nutzen den bestehenden /api/memory-tags, der aber nur das aktive Profil kennt.
    // Deshalb: Profil-spezifische Tags ueber die Profile-Liste approximieren
    // oder einfach die bekannten Tags des aktiven Profils anzeigen falls Quelle = aktiv

    try {
        const res = await fetch('/api/profiles');
        const d = await res.json();
        const active = d.active;

        if (profileName === active) {
            const tagRes = await fetch('/api/memory-tags');
            const tags = await tagRes.json();
            if (tags.length > 0) {
                container.innerHTML = tags.map(t =>
                    `<span class="tag" onclick="addTagToInput('${escapeAttr(t)}')" style="cursor:pointer;">#${escapeHtml(t)}</span>`
                ).join(' ');
            }
        } else {
            container.innerHTML = '<span class="muted">Tags werden nach Profilwechsel sichtbar</span>';
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
    if (!name) { alert('Name ist erforderlich.'); return; }

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
                document.getElementById('import-status').textContent = `Profil "${name}" erstellt, ${d.imported} Memories uebernommen.`;
            } else {
                showWelcomeForNewProfile(name);
            }
        } else {
            const d = await res.json();
            alert(d.detail || 'Fehler beim Erstellen');
        }
    } catch (e) { alert('Fehler: ' + e.message); }
}

async function renameActiveProfile() {
    const oldName = document.getElementById('profile-select').value;
    const newName = prompt('Neuer Name:', oldName);
    if (!newName || newName === oldName) return;
    const desc = prompt('Beschreibung (optional):', '') || '';
    try {
        const res = await fetch(`/api/profiles/${encodeURIComponent(oldName)}?new_name=${encodeURIComponent(newName)}&description=${encodeURIComponent(desc)}`, { method: 'PUT' });
        if (res.ok) {
            loadProfiles();
        } else {
            const d = await res.json();
            alert(d.detail || 'Fehler');
        }
    } catch (e) { console.error(e); }
}

async function deleteActiveProfile() {
    const name = document.getElementById('profile-select').value;
    if (!confirm(`Profil "${name}" wirklich loeschen? Alle Memories gehen verloren!`)) return;
    try {
        await fetch(`/api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadProfiles();
        loadDashboard();
    } catch (e) { console.error(e); }
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
    try {
        const res = await fetch('/api/sensitivity');
        secretsData = await res.json();
        renderSecretsStats(secretsData);
        renderSecretsList(secretsData.memories);
    } catch (e) { console.error(e); }
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
        el.innerHTML = '<p class="muted">Keine Ergebnisse</p>';
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
                <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">${findingsHtml || '<span class="muted">keine Findings</span>'}</div>
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
        `, `<button class="btn" onclick="closeModal()">Schliessen</button>`);
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

// Bot animation helper
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
