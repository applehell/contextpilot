"""Tests for PySide6 GUI widgets.

Requires PySide6 + a working display (or QT_QPA_PLATFORM=offscreen).
All tests are auto-skipped when Qt is unavailable.
"""
from __future__ import annotations

import pytest
from tests.conftest import requires_qt

# ---------------------------------------------------------------------------
# BudgetBar
# ---------------------------------------------------------------------------

@requires_qt
class TestBudgetBar:

    def test_initial_state(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        assert bar._bar.value() == 0
        assert "0" in bar._pct_label.text()

    def test_update_budget_normal(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        bar.update_budget(2_000, 10_000)
        assert bar._bar.value() == 20
        assert "20" in bar._pct_label.text()
        assert "2,000" in bar._usage_label.text()
        assert "10,000" in bar._usage_label.text()

    def test_update_budget_overflow(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        bar.update_budget(12_000, 10_000)
        assert bar._bar.value() == 100  # capped at 100

    def test_colour_green_below_70(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        bar.update_budget(500, 1_000)
        assert "#43a047" in bar._bar.styleSheet()

    def test_colour_orange_at_70(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        bar.update_budget(750, 1_000)
        assert "#fb8c00" in bar._bar.styleSheet()

    def test_colour_red_at_90(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        bar.update_budget(950, 1_000)
        assert "#e53935" in bar._bar.styleSheet()

    def test_zero_total_no_crash(self, qapp):
        from src.gui.widgets.budget_bar import BudgetBar
        bar = BudgetBar()
        bar.update_budget(0, 0)  # total clamped to 1


# ---------------------------------------------------------------------------
# BlockCard
# ---------------------------------------------------------------------------

@requires_qt
class TestBlockCard:

    def test_card_displays_block_content(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.block_card import BlockCard
        block = Block(content="Hello world", priority=Priority.MEDIUM)
        card = BlockCard(block)
        assert card.block is block

    def test_card_priority_high(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.block_card import BlockCard
        block = Block(content="urgent", priority=Priority.HIGH)
        card = BlockCard(block)
        assert card.block.priority == Priority.HIGH

    def test_card_with_compress_hint(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.block_card import BlockCard
        block = Block(content="code", priority=Priority.LOW, compress_hint="code_compact")
        card = BlockCard(block)
        assert card.block.compress_hint == "code_compact"

    def test_card_truncates_long_content(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.block_card import BlockCard
        block = Block(content="x" * 200, priority=Priority.MEDIUM)
        card = BlockCard(block)
        assert card.block is block

    def test_signals_exist(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.block_card import BlockCard
        block = Block(content="sig", priority=Priority.MEDIUM)
        card = BlockCard(block)
        assert hasattr(card, "edit_clicked")
        assert hasattr(card, "delete_clicked")
        assert hasattr(card, "duplicate_clicked")


# ---------------------------------------------------------------------------
# BlockEditor
# ---------------------------------------------------------------------------

@requires_qt
class TestBlockEditor:

    def test_initial_empty(self, qapp):
        from src.gui.block_editor import BlockEditor
        editor = BlockEditor()
        assert editor.get_blocks() == []

    def test_set_and_get_blocks(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.block_editor import BlockEditor
        editor = BlockEditor()
        blocks = [
            Block(content="A", priority=Priority.HIGH),
            Block(content="B", priority=Priority.LOW),
        ]
        editor.set_blocks(blocks)
        got = editor.get_blocks()
        assert len(got) == 2
        assert got[0].content == "A"
        assert got[1].content == "B"

    def test_set_blocks_replaces(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.block_editor import BlockEditor
        editor = BlockEditor()
        editor.set_blocks([Block(content="old", priority=Priority.MEDIUM)])
        editor.set_blocks([Block(content="new", priority=Priority.HIGH)])
        got = editor.get_blocks()
        assert len(got) == 1
        assert got[0].content == "new"

    def test_delete_block(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.block_editor import BlockEditor
        editor = BlockEditor()
        blocks = [Block(content="keep", priority=Priority.HIGH),
                  Block(content="remove", priority=Priority.LOW)]
        editor.set_blocks(blocks)
        editor._delete_block(blocks[1])
        assert len(editor.get_blocks()) == 1
        assert editor.get_blocks()[0].content == "keep"

    def test_duplicate_block(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.block_editor import BlockEditor
        editor = BlockEditor()
        block = Block(content="dup me", priority=Priority.MEDIUM)
        editor.set_blocks([block])
        editor._duplicate_block(block)
        got = editor.get_blocks()
        assert len(got) == 2
        assert got[0].content == got[1].content == "dup me"


# ---------------------------------------------------------------------------
# MemoryEditor
# ---------------------------------------------------------------------------

@requires_qt
class TestMemoryEditorWidget:

    def test_initial_no_store(self, qapp):
        from src.gui.memory_editor import MemoryEditor
        editor = MemoryEditor()
        assert editor._store is None

    def test_set_store(self, qapp):
        from src.storage.db import Database
        from src.storage.memory import Memory, MemoryStore
        from src.gui.memory_editor import MemoryEditor
        db = Database(None)
        store = MemoryStore(db)
        store.set(Memory(key="k1", value="v1", tags=["t1"]))
        editor = MemoryEditor()
        editor.set_store(store)
        assert editor._store is store
        assert editor._list.count() == 1

    def test_preview_context_no_store(self, qapp):
        from src.gui.memory_editor import MemoryEditor
        editor = MemoryEditor()
        editor._preview_context()
        assert "no database" in editor._preview.toPlainText()

    def test_preview_context_empty_store(self, qapp):
        from src.storage.db import Database
        from src.storage.memory import MemoryStore
        from src.gui.memory_editor import MemoryEditor
        db = Database(None)
        store = MemoryStore(db)
        editor = MemoryEditor()
        editor.set_store(store)
        editor._preview_context()
        assert "no memories" in editor._preview.toPlainText()

    def test_preview_context_with_data(self, qapp):
        from src.storage.db import Database
        from src.storage.memory import Memory, MemoryStore
        from src.gui.memory_editor import MemoryEditor
        db = Database(None)
        store = MemoryStore(db)
        store.set(Memory(key="sys", value="Be helpful", tags=["system"]))
        store.set(Memory(key="usr", value="Be concise"))
        editor = MemoryEditor()
        editor.set_store(store)
        editor._preview_context()
        text = editor._preview.toPlainText()
        assert "2 entries" in text
        assert "sys" in text

    def test_refresh_filters_by_search(self, qapp):
        from src.storage.db import Database
        from src.storage.memory import Memory, MemoryStore
        from src.gui.memory_editor import MemoryEditor
        db = Database(None)
        store = MemoryStore(db)
        store.set(Memory(key="alpha", value="first"))
        store.set(Memory(key="beta", value="second"))
        editor = MemoryEditor()
        editor.set_store(store)
        assert editor._list.count() == 2
        editor._search.setText("alpha")
        # _refresh_list is auto-triggered by textChanged
        assert editor._list.count() == 1


# ---------------------------------------------------------------------------
# SimulationPanel
# ---------------------------------------------------------------------------

@requires_qt
class TestSimulationPanel:

    def test_initial_empty(self, qapp):
        from src.gui.widgets.simulation_panel import SimulationPanel
        panel = SimulationPanel()
        assert panel._blocks == []
        assert panel.report is None
        assert panel.clustering_result is None

    def test_set_blocks(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.simulation_panel import SimulationPanel
        panel = SimulationPanel()
        blocks = [Block(content="test block", priority=Priority.HIGH)]
        panel.set_blocks(blocks)
        assert panel._blocks == blocks

    def test_run_simulation_empty_blocks_noop(self, qapp):
        from src.gui.widgets.simulation_panel import SimulationPanel
        panel = SimulationPanel()
        panel._run_simulation()  # should not crash
        assert panel.report is None

    def test_run_simulation_with_blocks(self, qapp):
        from src.core.block import Block, Priority
        from src.gui.widgets.simulation_panel import SimulationPanel
        panel = SimulationPanel()
        blocks = [
            Block(content="Block A with some content", priority=Priority.HIGH),
            Block(content="Block B shorter", priority=Priority.MEDIUM),
            Block(content="Block C low priority stuff", priority=Priority.LOW),
        ]
        panel.set_blocks(blocks)
        panel._run_simulation()
        assert panel.report is not None
        assert panel.clustering_result is not None
        assert len(panel.report.scenarios) > 0


# ---------------------------------------------------------------------------
# ClusterMap & BudgetImpactChart (paintEvent smoke tests)
# ---------------------------------------------------------------------------

@requires_qt
class TestClusterMap:

    def test_empty_clusters(self, qapp):
        from src.gui.widgets.simulation_panel import ClusterMap
        cm = ClusterMap()
        assert cm._clusters == []

    def test_set_clusters(self, qapp):
        from src.gui.widgets.simulation_panel import ClusterMap
        from src.core.clustering import BlockCluster
        from src.core.block import Block, Priority
        cm = ClusterMap()
        blocks = [Block(content="x", priority=Priority.HIGH)]
        cluster = BlockCluster(label="test", blocks=blocks, total_tokens=10, priority_distribution={"high": 1})
        cm.set_clusters([cluster])
        assert len(cm._clusters) == 1


@requires_qt
class TestBudgetImpactChart:

    def test_empty_scenarios(self, qapp):
        from src.gui.widgets.simulation_panel import BudgetImpactChart
        chart = BudgetImpactChart()
        assert chart._scenarios == []

    def test_set_scenarios(self, qapp):
        from src.gui.widgets.simulation_panel import BudgetImpactChart
        from src.core.simulator import ScenarioResult
        chart = BudgetImpactChart()
        sr = ScenarioResult(
            scenario_name="test",
            budget=1000,
            used_tokens=500,
            blocks_included=3,
            blocks_total=5,
            blocks_compressed=1,
            utilization=0.5,
        )
        chart.set_scenarios([sr])
        assert len(chart._scenarios) == 1


# ---------------------------------------------------------------------------
# MainWindow (smoke test)
# ---------------------------------------------------------------------------

@requires_qt
class TestMainWindow:

    def test_creates_without_crash(self, qapp):
        from src.gui.main_window import MainWindow
        win = MainWindow()
        assert win.windowTitle() == "Context Pilot"

    def test_assemble_empty(self, qapp):
        from src.gui.main_window import MainWindow
        win = MainWindow()
        win._assemble()
        assert "no blocks" in win._assemble_page._preview.toPlainText()

    def test_budget_bar_updates(self, qapp):
        from src.gui.main_window import MainWindow
        win = MainWindow()
        win._assemble_page._budget_spin.setValue(4_000)
        # Budget bar is now in the assemble page
        assert win._assemble_page.budget == 4_000

    def test_save_project_no_project(self, qapp):
        from src.gui.main_window import MainWindow
        from unittest.mock import patch
        win = MainWindow()
        with patch("src.gui.main_window.QMessageBox.information") as mock_msg:
            win._save_project()
            mock_msg.assert_called_once()

    def test_close_event(self, qapp):
        from src.gui.main_window import MainWindow
        from unittest.mock import MagicMock
        win = MainWindow()
        event = MagicMock()
        win.closeEvent(event)
        event.accept.assert_called_once()


# ---------------------------------------------------------------------------
# __main__ smoke test
# ---------------------------------------------------------------------------

@requires_qt
class TestGuiMain:

    def test_main_module_importable(self):
        from src.gui import __main__
        assert hasattr(__main__, "main")
