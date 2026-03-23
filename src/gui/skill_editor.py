"""Skill Editor — GUI panel for managing skill connections and configurations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from src.core.block import Block
from src.core.skill_connector import BaseSkill, SkillConfig, SkillConnector
from src.core.token_budget import TokenBudget


class _ParamDialog(QDialog):
    """Dialog to edit skill parameters as key=value pairs."""

    def __init__(self, skill: BaseSkill, config: SkillConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Configure: {skill.name}")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"<b>{skill.name}</b>"))
        layout.addWidget(QLabel(skill.description))

        layout.addWidget(QLabel(""))
        layout.addWidget(QLabel("Parameters (one per line, key=value):"))

        self._params_edit = QTextEdit()
        self._params_edit.setMinimumHeight(100)
        lines = [f"{k}={v}" for k, v in config.params.items()]
        self._params_edit.setPlainText("\n".join(lines))
        self._params_edit.setPlaceholderText("cwd=/home/user/project\npriority=low")
        layout.addWidget(self._params_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for line in self._params_edit.toPlainText().strip().splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _, value = line.partition("=")
            params[key.strip()] = value.strip()
        return params


class _SkillCard(QFrame):
    """Card displaying one skill with toggle, info, and config button."""

    toggled = Signal(str, bool)
    configure_clicked = Signal(str)
    test_clicked = Signal(str)

    def __init__(self, skill: BaseSkill, config: SkillConfig, parent=None) -> None:
        super().__init__(parent)
        self._skill = skill
        self._config = config
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self._build_ui()

    @property
    def skill(self) -> BaseSkill:
        return self._skill

    @property
    def config(self) -> SkillConfig:
        return self._config

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        self._toggle = QCheckBox()
        self._toggle.setChecked(self._config.enabled)
        self._toggle.toggled.connect(
            lambda checked: self.toggled.emit(self._skill.name, checked)
        )
        root.addWidget(self._toggle)

        info = QVBoxLayout()
        info.setSpacing(3)

        name_label = QLabel(self._skill.name)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info.addWidget(name_label)

        desc_label = QLabel(self._skill.description)
        desc_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        desc_label.setWordWrap(True)
        desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info.addWidget(desc_label)

        if self._skill.context_hints:
            hints = ", ".join(self._skill.context_hints[:5])
            hints_label = QLabel(f"hints: {hints}")
            hints_label.setStyleSheet("color: #6c7086; font-size: 11px;")
            info.addWidget(hints_label)

        if self._config.params:
            params_text = ", ".join(f"{k}={v}" for k, v in self._config.params.items())
            params_label = QLabel(f"params: {params_text}")
            params_label.setStyleSheet("color: #6c7086; font-size: 11px;")
            info.addWidget(params_label)

        root.addLayout(info)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        test_btn = QPushButton("Test")
        test_btn.setMinimumWidth(80)
        test_btn.setMinimumHeight(30)
        test_btn.setToolTip("Run skill and show generated blocks")
        test_btn.clicked.connect(lambda: self.test_clicked.emit(self._skill.name))
        btn_col.addWidget(test_btn)

        cfg_btn = QPushButton("Config")
        cfg_btn.setMinimumWidth(80)
        cfg_btn.setMinimumHeight(30)
        cfg_btn.clicked.connect(lambda: self.configure_clicked.emit(self._skill.name))
        btn_col.addWidget(cfg_btn)

        root.addLayout(btn_col)


class SkillEditor(QWidget):
    """Skill management panel with enable/disable, configuration, and testing.

    Signals:
        configs_changed: emitted whenever skill configs are modified;
                         carries the new list[SkillConfig].
    """

    configs_changed = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._connector: Optional[SkillConnector] = None
        self._configs: Dict[str, SkillConfig] = {}
        self._build_ui()

    def set_connector(self, connector: SkillConnector, configs: List[SkillConfig]) -> None:
        self._connector = connector
        self._configs = {c.skill_name: c for c in configs}
        for skill in connector.available_skills:
            if skill.name not in self._configs:
                self._configs[skill.name] = SkillConfig(skill_name=skill.name, enabled=False)
        self._refresh()

    def get_configs(self) -> List[SkillConfig]:
        return list(self._configs.values())

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()

        enable_all = QPushButton("Enable All")
        enable_all.setMinimumHeight(28)
        enable_all.clicked.connect(self._enable_all)
        toolbar.addWidget(enable_all)

        disable_all = QPushButton("Disable All")
        disable_all.setMinimumHeight(28)
        disable_all.clicked.connect(self._disable_all)
        toolbar.addWidget(disable_all)

        test_all_btn = QPushButton("Test All Enabled")
        test_all_btn.setMinimumHeight(28)
        test_all_btn.clicked.connect(self._test_all)
        toolbar.addWidget(test_all_btn)

        refresh_btn = QPushButton("\u21BB Refresh")
        refresh_btn.setMinimumHeight(28)
        refresh_btn.setToolTip("Reload skill list and status")
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch()

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #a6adc8; font-size: 12px;")
        toolbar.addWidget(self._summary)

        layout.addLayout(toolbar)

        self._list = QListWidget()
        layout.addWidget(self._list)

        layout.addWidget(QLabel("Test output:"))
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(150)
        self._output.setPlaceholderText("Click 'Test' on a skill to see its generated blocks...")
        layout.addWidget(self._output)

    def _refresh(self) -> None:
        self._list.clear()
        if self._connector is None:
            return

        for skill in self._connector.available_skills:
            config = self._configs.get(skill.name, SkillConfig(skill_name=skill.name, enabled=False))
            item = QListWidgetItem()
            card = _SkillCard(skill, config)
            card.toggled.connect(self._on_toggle)
            card.configure_clicked.connect(self._on_configure)
            card.test_clicked.connect(self._on_test)
            item.setSizeHint(card.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

        self._update_summary()

    def _update_summary(self) -> None:
        if not self._connector:
            return
        total = len(self._connector.available_skills)
        enabled = sum(1 for c in self._configs.values() if c.enabled)
        self._summary.setText(f"{enabled}/{total} skills enabled")

    def _on_toggle(self, skill_name: str, enabled: bool) -> None:
        if skill_name in self._configs:
            self._configs[skill_name].enabled = enabled
        else:
            self._configs[skill_name] = SkillConfig(skill_name=skill_name, enabled=enabled)
        self._update_summary()
        self.configs_changed.emit(self.get_configs())

    def _on_configure(self, skill_name: str) -> None:
        if self._connector is None:
            return
        skill = self._connector.get_skill(skill_name)
        if skill is None:
            return
        config = self._configs.get(skill_name, SkillConfig(skill_name=skill_name))
        dlg = _ParamDialog(skill, config, parent=self)
        if dlg.exec() == QDialog.Accepted:
            config.params = dlg.result_params()
            self._configs[skill_name] = config
            self._refresh()
            self.configs_changed.emit(self.get_configs())

    def _on_test(self, skill_name: str) -> None:
        if self._connector is None:
            return
        skill = self._connector.get_skill(skill_name)
        if skill is None:
            return
        config = self._configs.get(skill_name, SkillConfig(skill_name=skill_name))
        try:
            blocks = skill.generate_blocks(config)
        except Exception as exc:
            self._output.setPlainText(f"ERROR: {exc}")
            return

        if not blocks:
            self._output.setPlainText(f"Skill '{skill_name}' returned no blocks.")
            return

        lines = [f"Skill '{skill_name}' generated {len(blocks)} block(s):", ""]
        for i, b in enumerate(blocks):
            lines.append(f"--- Block {i + 1} [{b.priority.value}] ({b.token_count} tokens) ---")
            lines.append(b.content[:500])
            if len(b.content) > 500:
                lines.append("...")
            lines.append("")
        self._output.setPlainText("\n".join(lines))

    def _test_all(self) -> None:
        if self._connector is None:
            return
        enabled = [c for c in self._configs.values() if c.enabled]
        if not enabled:
            self._output.setPlainText("No skills enabled.")
            return

        all_blocks = self._connector.collect_blocks(enabled)
        total_tokens = sum(b.token_count for b in all_blocks)

        lines = [f"All enabled skills: {len(all_blocks)} block(s), {total_tokens:,} tokens", ""]
        for i, b in enumerate(all_blocks):
            preview = b.content[:120].replace("\n", " ")
            if len(b.content) > 120:
                preview += "..."
            lines.append(f"  [{b.priority.value}] {b.token_count:>5} t  {preview}")
        self._output.setPlainText("\n".join(lines))

    def _enable_all(self) -> None:
        for config in self._configs.values():
            config.enabled = True
        self._refresh()
        self.configs_changed.emit(self.get_configs())

    def _disable_all(self) -> None:
        for config in self._configs.values():
            config.enabled = False
        self._refresh()
        self.configs_changed.emit(self.get_configs())
