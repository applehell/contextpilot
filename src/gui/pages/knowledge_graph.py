"""Knowledge Graph page — vis.js network embedded in QWebEngineView."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QObject, QUrl, Signal, Slot

from src.core.token_budget import TokenBudget
from src.storage.memory import MemoryStore

CATEGORY_COLORS = [
    "#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7",
    "#fab387", "#94e2d5", "#74c7ec", "#f5c2e7", "#b4befe",
]


def build_graph_data(store: MemoryStore) -> Dict[str, Any]:
    memories = store.list()

    nodes = []
    groups_seen: Dict[str, int] = {}
    tag_index: Dict[str, List[str]] = defaultdict(list)

    for m in memories:
        parts = m.key.split("/")
        if len(parts) >= 2:
            group = "/".join(parts[:2])
            label = "/".join(parts[2:]) or parts[-1]
        else:
            group = parts[0]
            label = parts[0]

        if group not in groups_seen:
            groups_seen[group] = len(groups_seen)

        tokens = TokenBudget.estimate(m.value)
        size = max(8, min(40, 8 + tokens // 50))

        if label == "_preamble":
            label = "(preamble)"

        tag_str = ", ".join(m.tags) if m.tags else "keine"
        nodes.append({
            "id": m.key,
            "label": label,
            "group": group,
            "title": f"<b>{m.key}</b><br>Tags: {tag_str}<br>{tokens} tokens",
            "value": size,
            "tags": m.tags,
        })

        for tag in m.tags:
            tag_index[tag].append(m.key)

    edges = []
    edge_set: set = set()
    for tag, keys in tag_index.items():
        if len(keys) > 20:
            continue
        for i, k1 in enumerate(keys):
            g1 = "/".join(k1.split("/")[:2])
            for k2 in keys[i + 1:]:
                g2 = "/".join(k2.split("/")[:2])
                if g1 == g2:
                    continue
                pair = tuple(sorted([k1, k2]))
                if pair not in edge_set:
                    edge_set.add(pair)
                    edges.append({
                        "from": k1,
                        "to": k2,
                        "title": f"Tag: {tag}",
                        "color": {"color": "#585b70", "opacity": 0.4},
                        "width": 1,
                    })

    group_config = {}
    for group_name, idx in groups_seen.items():
        color = CATEGORY_COLORS[idx % len(CATEGORY_COLORS)]
        group_config[group_name] = {
            "color": {"background": color, "border": color,
                      "highlight": {"background": color, "border": "#fff"}},
            "font": {"color": "#cdd6f4"},
        }

    return {
        "nodes": nodes,
        "edges": edges,
        "groups": group_config,
        "stats": {
            "total_memories": len(memories),
            "total_groups": len(groups_seen),
            "total_edges": len(edges),
        },
    }


class _Bridge(QObject):
    """Bridge between JS and Python for fetching memory content."""

    memory_content = Signal(str)

    def __init__(self, store: Optional[MemoryStore] = None, parent=None):
        super().__init__(parent)
        self._store = store

    def set_store(self, store: MemoryStore):
        self._store = store

    @Slot(str, result=str)
    def getMemoryContent(self, key: str) -> str:
        if not self._store:
            return "Kein Store verfuegbar"
        try:
            m = self._store.get(key)
            preview = m.value[:800]
            if len(m.value) > 800:
                preview += "..."
            return preview
        except KeyError:
            return f"Memory '{key}' nicht gefunden"


_GRAPH_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #181825; font-family: 'SF Mono', monospace; overflow: hidden; }
  #toolbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 16px; background: #1e1e2e;
    border-bottom: 1px solid #45475a; color: #cdd6f4; font-size: 12px;
  }
  #toolbar h2 { font-size: 15px; margin: 0; }
  #stats { color: #6c7086; }
  .spacer { flex: 1; }
  #toolbar label { color: #a6adc8; cursor: pointer; }
  #toolbar button {
    background: #313244; border: 1px solid #45475a; color: #cdd6f4;
    padding: 4px 12px; border-radius: 6px; cursor: pointer; font-size: 12px;
    font-family: inherit;
  }
  #toolbar button:hover { background: #45475a; }
  #graph { width: 100%; height: calc(100vh - 42px); }
  #legend {
    position: absolute; bottom: 12px; left: 12px;
    background: rgba(30,30,46,0.92); border: 1px solid #45475a;
    border-radius: 8px; padding: 10px 14px; font-size: 11px;
    color: #a6adc8; max-height: 220px; overflow-y: auto;
  }
  .legend-item { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
  .legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  #detail {
    position: absolute; top: 52px; right: 12px;
    background: rgba(30,30,46,0.95); border: 1px solid #45475a;
    border-radius: 8px; padding: 14px; font-size: 12px;
    color: #cdd6f4; max-width: 380px; max-height: 420px;
    overflow-y: auto; display: none;
  }
  #detail .key { font-weight: bold; font-size: 14px; margin-bottom: 4px; }
  #detail .group { color: #a6adc8; margin-bottom: 6px; }
  #detail .tags { margin-bottom: 8px; }
  #detail .tag {
    background: #45475a; padding: 2px 6px; border-radius: 4px;
    font-size: 11px; margin-right: 4px;
  }
  #detail pre {
    white-space: pre-wrap; font-size: 11px; color: #a6adc8;
    max-height: 220px; overflow-y: auto; background: #181825;
    padding: 8px; border-radius: 4px; margin-top: 8px;
  }
</style>
</head>
<body>
<div id="toolbar">
  <h2>Knowledge Graph</h2>
  <span id="stats"></span>
  <div class="spacer"></div>
  <input type="text" id="search" placeholder="Suche in Memories..." oninput="searchNodes()" style="width:220px;padding:4px 10px;font-size:12px;background:#181825;border:1px solid #45475a;color:#cdd6f4;border-radius:6px;">
  <span id="search-count" style="color:#6c7086;font-size:11px;min-width:60px;"></span>
  <label><input type="checkbox" id="physics" checked onchange="togglePhysics()"> Physik</label>
  <button onclick="fitAll()">Alles zeigen</button>
  <button onclick="reload()">Neu laden</button>
</div>
<div id="graph"></div>
<div id="legend"></div>
<div id="detail"></div>

<script>
let network = null;
let graphData = null;

function escape(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function initGraph(dataJson) {
  graphData = JSON.parse(dataJson);
  const container = document.getElementById('graph');

  const nodes = new vis.DataSet(graphData.nodes.map(n => ({
    id: n.id, label: n.label, group: n.group,
    title: n.title, value: n.value,
    font: { color: '#cdd6f4', size: 11 }, shape: 'dot',
  })));

  const edges = new vis.DataSet(graphData.edges);

  const options = {
    groups: graphData.groups,
    physics: {
      enabled: true,
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -40, centralGravity: 0.008,
        springLength: 120, springConstant: 0.02,
        damping: 0.5, avoidOverlap: 0.3,
      },
      stabilization: { iterations: 200, fit: true },
    },
    interaction: {
      hover: true, tooltipDelay: 100,
      keyboard: { enabled: true }, zoomView: true,
    },
    nodes: {
      scaling: { min: 8, max: 40 },
      borderWidth: 2,
      shadow: { enabled: true, size: 6, color: 'rgba(0,0,0,0.3)' },
    },
    edges: { smooth: { type: 'continuous' } },
  };

  nodesDataSet = nodes;
  network = new vis.Network(container, { nodes, edges }, options);

  network.on('click', function(params) {
    const detail = document.getElementById('detail');
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      const node = graphData.nodes.find(n => n.id === nodeId);
      if (node) {
        detail.style.display = 'block';
        const tagHtml = node.tags.length
          ? node.tags.map(t => '<span class="tag">' + escape(t) + '</span>').join(' ')
          : '<span style="color:#6c7086;">keine</span>';
        detail.innerHTML =
          '<div class="key">' + escape(node.id) + '</div>' +
          '<div class="group">Gruppe: ' + escape(node.group) + '</div>' +
          '<div class="tags">Tags: ' + tagHtml + '</div>' +
          '<button onclick="loadContent(\\'' + node.id.replace(/'/g, "\\\\'") + '\\')">Inhalt laden</button>' +
          '<pre id="content-area"></pre>';
      }
    } else {
      detail.style.display = 'none';
    }
  });

  // Stats
  const s = graphData.stats;
  document.getElementById('stats').textContent =
    s.total_memories + ' Memories | ' + s.total_groups + ' Gruppen | ' + s.total_edges + ' Verbindungen';

  // Legend
  const legend = document.getElementById('legend');
  let html = '<div style="font-weight:bold;margin-bottom:4px;">Gruppen</div>';
  for (const [name, cfg] of Object.entries(graphData.groups)) {
    const count = graphData.nodes.filter(n => n.group === name).length;
    html += '<div class="legend-item"><span class="legend-dot" style="background:' +
      cfg.color.background + ';"></span>' + escape(name) + ' (' + count + ')</div>';
  }
  legend.innerHTML = html;
}

function loadContent(key) {
  const area = document.getElementById('content-area');
  if (!area) return;
  area.textContent = 'Lade...';
  if (window.bridge) {
    bridge.getMemoryContent(key, function(result) {
      area.textContent = result;
    });
  } else {
    area.textContent = 'Bridge nicht verfuegbar';
  }
}

function togglePhysics() {
  if (network) network.setOptions({ physics: { enabled: document.getElementById('physics').checked } });
}

function fitAll() {
  if (network) network.fit({ animation: true });
}

function reload() {
  if (window.bridge) {
    window.location.reload();
  }
}

let nodesDataSet = null;

function searchNodes() {
  if (!network || !nodesDataSet || !graphData) return;
  const q = document.getElementById('search').value.trim().toLowerCase();
  const countEl = document.getElementById('search-count');

  if (!q) {
    const updates = graphData.nodes.map(n => ({
      id: n.id, opacity: 1.0,
      font: { color: '#cdd6f4', size: 11 },
    }));
    nodesDataSet.update(updates);
    countEl.textContent = '';
    return;
  }

  let matchCount = 0;
  const updates = graphData.nodes.map(n => {
    const haystack = (n.id + ' ' + n.label + ' ' + (n.tags || []).join(' ')).toLowerCase();
    const isMatch = haystack.includes(q);
    if (isMatch) matchCount++;
    return {
      id: n.id, opacity: isMatch ? 1.0 : 0.15,
      font: { color: isMatch ? '#cdd6f4' : '#313244', size: isMatch ? 13 : 9 },
    };
  });
  nodesDataSet.update(updates);
  countEl.textContent = matchCount + ' Treffer';

  const firstMatch = graphData.nodes.find(n =>
    (n.id + ' ' + n.label + ' ' + (n.tags || []).join(' ')).toLowerCase().includes(q)
  );
  if (firstMatch) network.focus(firstMatch.id, { scale: 1.2, animation: true });
}
</script>
</body>
</html>"""


class KnowledgeGraphPage(QWidget):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._store: Optional[MemoryStore] = None
        self._bridge = _Bridge()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._web = QWebEngineView()
        self._web.setStyleSheet("background: #181825;")

        # Set up web channel for Python <-> JS bridge
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self._bridge)
        self._web.page().setWebChannel(self._channel)

        layout.addWidget(self._web)

    def set_store(self, store: MemoryStore) -> None:
        self._store = store
        self._bridge.set_store(store)
        self.refresh()

    def refresh(self) -> None:
        if not self._store:
            self._web.setHtml(
                "<html><body style='background:#181825;color:#6c7086;"
                "font-family:monospace;padding:40px;'>"
                "Kein Projekt geoeffnet — oeffne ein Projekt um den Knowledge Graph zu sehen."
                "</body></html>"
            )
            return

        data = build_graph_data(self._store)
        data_json = json.dumps(data)

        # Inject qwebchannel.js and data into the HTML
        html = _GRAPH_HTML.replace(
            '<script>',
            '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n<script>',
            1,
        )
        # Add init call with data
        init_script = f"""
        <script>
        new QWebChannel(qt.webChannelTransport, function(channel) {{
            window.bridge = channel.objects.bridge;
            initGraph({json.dumps(data_json)});
        }});
        </script>
        </body>"""
        html = html.replace("</body>", init_script)
        # baseUrl required so QWebEngine can load vis.js from CDN
        self._web.setHtml(html, QUrl("https://unpkg.com/"))
