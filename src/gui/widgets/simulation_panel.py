"""Simulation Panel — PySide6 widget for Context Pilot Classes visualization."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.block import Block
from src.core.clustering import BlockCluster, BlockClusterer, ClusteringResult
from src.core.compressors.base import BaseCompressor
from src.core.simulator import Simulator, SimulationScenario, ScenarioResult, SimulationReport


_CLUSTER_COLORS = [
    QColor("#4285f4"), QColor("#ea4335"), QColor("#fbbc04"),
    QColor("#34a853"), QColor("#ff6d01"), QColor("#46bdc6"),
    QColor("#7b1fa2"), QColor("#c2185b"), QColor("#00897b"),
    QColor("#6d4c41"),
]


class ClusterMap(QWidget):
    """Treemap-style visualization of block clusters with token budget impact."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._clusters: List[BlockCluster] = []
        self._total_tokens = 0
        self.setMinimumHeight(180)

    def set_clusters(self, clusters: List[BlockCluster]) -> None:
        self._clusters = clusters
        self._total_tokens = sum(c.total_tokens for c in clusters) or 1
        self.update()

    def paintEvent(self, event) -> None:
        if not self._clusters:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width() - 4
        h = self.height() - 4
        x = 2

        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)

        for i, cluster in enumerate(self._clusters):
            ratio = cluster.total_tokens / self._total_tokens
            box_w = max(int(w * ratio), 20)
            color = _CLUSTER_COLORS[i % len(_CLUSTER_COLORS)]

            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(130), 1))
            painter.drawRoundedRect(x, 2, box_w, h, 4, 4)

            painter.setPen(QPen(Qt.white))
            label = f"{cluster.label[:20]}\n{cluster.total_tokens:,}t"
            painter.drawText(x + 4, 2, box_w - 8, h, Qt.AlignLeft | Qt.AlignVCenter, label)

            x += box_w + 2
            if x >= self.width() - 4:
                break

        painter.end()


class BudgetImpactChart(QWidget):
    """Horizontal bar chart showing token usage per scenario."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._scenarios: List[ScenarioResult] = []
        self.setMinimumHeight(120)

    def set_scenarios(self, scenarios: List[ScenarioResult]) -> None:
        self._scenarios = scenarios
        self.update()

    def paintEvent(self, event) -> None:
        if not self._scenarios:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        max_budget = max(s.budget for s in self._scenarios) or 1
        bar_h = max(16, (self.height() - 10) // len(self._scenarios) - 4)
        y = 5

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        for i, sc in enumerate(self._scenarios):
            full_w = self.width() - 140
            budget_w = int(full_w * sc.budget / max_budget)
            used_w = int(full_w * sc.used_tokens / max_budget)

            painter.setBrush(QBrush(QColor("#e0e0e0")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(130, y, budget_w, bar_h, 3, 3)

            color = QColor("#4caf50") if sc.utilization < 0.9 else QColor("#f44336")
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(130, y, used_w, bar_h, 3, 3)

            painter.setPen(QPen(Qt.black))
            painter.drawText(2, y, 124, bar_h, Qt.AlignRight | Qt.AlignVCenter,
                             f"{sc.scenario_name}: ")
            painter.drawText(132, y, used_w - 4, bar_h, Qt.AlignLeft | Qt.AlignVCenter,
                             f"{sc.used_tokens:,}/{sc.budget:,}")

            y += bar_h + 4

        painter.end()


class SimulationPanel(QWidget):
    """Main simulation panel combining cluster view, budget sweep, and compression analysis."""

    simulation_run = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._blocks: List[Block] = []
        self._compressors: List[BaseCompressor] = []
        self._report: Optional[SimulationReport] = None
        self._clustering_result: Optional[ClusteringResult] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Min Budget:"))
        self._min_budget = QSpinBox()
        self._min_budget.setRange(100, 200_000)
        self._min_budget.setValue(1_000)
        self._min_budget.setSuffix(" t")
        self._min_budget.setSingleStep(500)
        ctrl.addWidget(self._min_budget)

        ctrl.addWidget(QLabel("Max Budget:"))
        self._max_budget = QSpinBox()
        self._max_budget.setRange(100, 200_000)
        self._max_budget.setValue(16_000)
        self._max_budget.setSuffix(" t")
        self._max_budget.setSingleStep(1_000)
        ctrl.addWidget(self._max_budget)

        ctrl.addWidget(QLabel("Steps:"))
        self._steps = QSpinBox()
        self._steps.setRange(2, 20)
        self._steps.setValue(5)
        ctrl.addWidget(self._steps)

        run_btn = QPushButton("Run Simulation")
        run_btn.clicked.connect(self._run_simulation)
        ctrl.addWidget(run_btn)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Splitter: top (clusters) | bottom (budget + details)
        splitter = QSplitter(Qt.Vertical)

        # Cluster view
        cluster_frame = QFrame()
        cluster_layout = QVBoxLayout(cluster_frame)
        cluster_layout.setContentsMargins(2, 2, 2, 2)
        cluster_layout.addWidget(QLabel("Context Pilot Classes (Clusters)"))
        self._cluster_map = ClusterMap()
        cluster_layout.addWidget(self._cluster_map)
        self._cluster_table = QTableWidget(0, 4)
        self._cluster_table.setHorizontalHeaderLabels(["Cluster", "Blocks", "Tokens", "Priority Mix"])
        self._cluster_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._cluster_table.setMaximumHeight(200)
        cluster_layout.addWidget(self._cluster_table)
        splitter.addWidget(cluster_frame)

        # Budget impact
        budget_frame = QFrame()
        budget_layout = QVBoxLayout(budget_frame)
        budget_layout.setContentsMargins(2, 2, 2, 2)
        budget_layout.addWidget(QLabel("Budget Impact"))
        self._budget_chart = BudgetImpactChart()
        budget_layout.addWidget(self._budget_chart)

        # Compression comparison
        budget_layout.addWidget(QLabel("Compression Analysis"))
        self._compression_table = QTableWidget(0, 4)
        self._compression_table.setHorizontalHeaderLabels(
            ["Block #", "Original", "Compressed", "Savings"]
        )
        self._compression_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._compression_table.setMaximumHeight(180)
        budget_layout.addWidget(self._compression_table)
        splitter.addWidget(budget_frame)

        splitter.setSizes([300, 300])
        layout.addWidget(splitter, stretch=1)

    def set_blocks(self, blocks: List[Block]) -> None:
        self._blocks = blocks

    def set_compressors(self, compressors: List[BaseCompressor]) -> None:
        self._compressors = compressors

    def _run_simulation(self) -> None:
        if not self._blocks:
            return

        # Clustering
        clusterer = BlockClusterer(similarity_threshold=0.15)
        self._clustering_result = clusterer.cluster(self._blocks)
        self._update_cluster_view()

        # Budget sweep
        min_b = self._min_budget.value()
        max_b = self._max_budget.value()
        steps = self._steps.value()
        step_size = max(1, (max_b - min_b) // (steps - 1))
        budgets = [min_b + i * step_size for i in range(steps)]

        simulator = Simulator(base_compressors=self._compressors)
        self._report = simulator.run_budget_sweep(self._blocks, budgets)
        self._budget_chart.set_scenarios(self._report.scenarios)

        # Compression analysis
        deltas = simulator.analyze_compression(self._blocks)
        self._update_compression_table(deltas)

        self.simulation_run.emit()

    def _update_cluster_view(self) -> None:
        if not self._clustering_result:
            return
        clusters = self._clustering_result.clusters
        self._cluster_map.set_clusters(clusters)

        self._cluster_table.setRowCount(len(clusters))
        for i, c in enumerate(clusters):
            self._cluster_table.setItem(i, 0, QTableWidgetItem(c.label[:40]))
            self._cluster_table.setItem(i, 1, QTableWidgetItem(str(c.size)))
            self._cluster_table.setItem(i, 2, QTableWidgetItem(f"{c.total_tokens:,}"))
            priorities = {}
            for b in c.blocks:
                p = b.priority.value if hasattr(b.priority, 'value') else str(b.priority)
                priorities[p] = priorities.get(p, 0) + 1
            mix = ", ".join(f"{k}:{v}" for k, v in sorted(priorities.items()))
            self._cluster_table.setItem(i, 3, QTableWidgetItem(mix))

    def _update_compression_table(self, deltas) -> None:
        self._compression_table.setRowCount(len(deltas))
        for i, d in enumerate(deltas):
            self._compression_table.setItem(i, 0, QTableWidgetItem(f"#{d.block_index} ({d.compressor_name})"))
            self._compression_table.setItem(i, 1, QTableWidgetItem(f"{d.original_tokens:,}"))
            self._compression_table.setItem(i, 2, QTableWidgetItem(f"{d.compressed_tokens:,}"))
            pct = (1 - d.ratio) * 100
            self._compression_table.setItem(i, 3, QTableWidgetItem(f"-{d.savings:,} ({pct:.0f}%)"))

    @property
    def report(self) -> Optional[SimulationReport]:
        return self._report

    @property
    def clustering_result(self) -> Optional[ClusteringResult]:
        return self._clustering_result
