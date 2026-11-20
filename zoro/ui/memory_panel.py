"""PySide6 Memory Management Panel for PROJECT ZORO Milestone 05.

Provides an interactive GUI for viewing, searching, editing, and managing
multi-tiered personal memories with category filtering and security confirmation guards.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class EditMemoryDialog(QDialog):
    """Dialog to create or edit a persistent memory item."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        category: str = "PREFERENCE",
        content: str = "",
        importance: float = 0.5,
        project_name: Optional[str] = None,
        is_new: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ZORO // CREATE MEMORY" if is_new else "ZORO // EDIT MEMORY")
        self.resize(500, 320)
        self.setStyleSheet("""
            QDialog { background-color: #0B0E14; color: #E2E8F0; }
            QLabel { color: #00D2FF; font-weight: bold; }
            QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox {
                background-color: #121824;
                border: 1px solid #1E293B;
                border-radius: 4px;
                color: #FFFFFF;
                padding: 6px;
            }
            QPushButton {
                background-color: #008899;
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 4px;
                padding: 6px 14px;
            }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.combo_cat = QComboBox(self)
        self.combo_cat.addItems(["IDENTITY", "PREFERENCE", "PROJECT", "SCHEDULE", "EPISODIC"])
        self.combo_cat.setCurrentText(category)
        form.addRow("Category:", self.combo_cat)

        self.txt_content = QTextEdit(self)
        self.txt_content.setPlainText(content)
        self.txt_content.setPlaceholderText("Enter personal memory fact or preference...")
        form.addRow("Content:", self.txt_content)

        self.spin_importance = QDoubleSpinBox(self)
        self.spin_importance.setRange(0.0, 1.0)
        self.spin_importance.setSingleStep(0.05)
        self.spin_importance.setValue(importance)
        form.addRow("Importance (0-1):", self.spin_importance)

        self.edit_project = QLineEdit(self)
        if project_name:
            self.edit_project.setText(project_name)
        self.edit_project.setPlaceholderText("Optional: Project name (for PROJECT category)")
        form.addRow("Project Scope:", self.edit_project)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_data(self) -> Dict[str, Any]:
        return {
            "category": self.combo_cat.currentText(),
            "content": self.txt_content.toPlainText().strip(),
            "importance": self.spin_importance.value(),
            "project_name": self.edit_project.text().strip() or None,
        }


class ZoroMemoryDialog(QDialog):
    """
    Standalone modal or independent window for managing ZORO's personal memories.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        ipc_call_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.ipc_call_handler = ipc_call_handler
        self._loaded_memories: List[Dict[str, Any]] = []

        self.setWindowTitle("PROJECT ZORO // PERSONAL MEMORY ARCHITECTURE")
        self.resize(950, 620)
        self.setStyleSheet("""
            QDialog { background-color: #0B0E14; color: #E2E8F0; }
            QLabel { color: #00D2FF; font-weight: bold; }
            QTableWidget {
                background-color: #101520;
                border: 1px solid #1E293B;
                gridline-color: #1A2333;
                color: #E2E8F0;
                selection-background-color: #004466;
            }
            QHeaderView::section {
                background-color: #121824;
                color: #00D2FF;
                padding: 6px;
                border: 1px solid #1E293B;
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                background-color: #121824;
                border: 1px solid #1E293B;
                border-radius: 4px;
                color: #FFFFFF;
                padding: 6px;
            }
            QPushButton {
                background-color: #1A2634;
                border: 1px solid #00D2FF;
                color: #00D2FF;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00D2FF;
                color: #0B0E14;
            }
            QPushButton#dangerButton {
                border: 1px solid #FF3344;
                color: #FF3344;
                background-color: #220B10;
            }
            QPushButton#dangerButton:hover {
                background-color: #FF3344;
                color: #FFFFFF;
            }
        """)

        self._build_ui()
        self.refresh_memories()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Title
        lbl_title = QLabel("PERSONAL MEMORY REPOSITORY // PERSISTENT RETRIEVAL", self)
        lbl_title.setStyleSheet("font-size: 15px; letter-spacing: 1px;")
        layout.addWidget(lbl_title)

        # Filter & Search Controls Bar
        filter_box = QHBoxLayout()

        filter_box.addWidget(QLabel("FILTER CATEGORY:", self))
        self.combo_filter_cat = QComboBox(self)
        self.combo_filter_cat.addItems(["ALL", "IDENTITY", "PREFERENCE", "PROJECT", "SCHEDULE", "EPISODIC"])
        self.combo_filter_cat.currentTextChanged.connect(lambda _: self.refresh_memories())
        filter_box.addWidget(self.combo_filter_cat)

        filter_box.addWidget(QLabel("SEARCH:", self))
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Semantic or keyword search memories...")
        self.search_input.returnPressed.connect(self._on_search)
        filter_box.addWidget(self.search_input)

        btn_search = QPushButton("Search", self)
        btn_search.clicked.connect(self._on_search)
        filter_box.addWidget(btn_search)

        btn_refresh = QPushButton("Refresh All", self)
        btn_refresh.clicked.connect(self.refresh_memories)
        filter_box.addWidget(btn_refresh)

        layout.addLayout(filter_box)

        # Main Memory Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Category", "Content", "Importance", "Source", "Created At"
        ])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.doubleClicked.connect(self._on_edit_clicked)
        layout.addWidget(self.table)

        # Action Buttons Row
        action_row = QHBoxLayout()

        btn_add = QPushButton("+ Add Memory", self)
        btn_add.clicked.connect(self._on_add_clicked)
        action_row.addWidget(btn_add)

        btn_edit = QPushButton("Edit Selected", self)
        btn_edit.clicked.connect(self._on_edit_clicked)
        action_row.addWidget(btn_edit)

        btn_delete = QPushButton("Delete Selected", self)
        btn_delete.setObjectName("dangerButton")
        btn_delete.clicked.connect(self._on_delete_clicked)
        action_row.addWidget(btn_delete)

        btn_delete_cat = QPushButton("Delete Category", self)
        btn_delete_cat.setObjectName("dangerButton")
        btn_delete_cat.clicked.connect(self._on_delete_category_clicked)
        action_row.addWidget(btn_delete_cat)

        action_row.addStretch()

        btn_clear_all = QPushButton("CLEAR ALL MEMORIES", self)
        btn_clear_all.setObjectName("dangerButton")
        btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        action_row.addWidget(btn_clear_all)

        layout.addLayout(action_row)

    def refresh_memories(self) -> None:
        """Fetch memories from core engine via Named Pipe IPC."""
        if not self.ipc_call_handler:
            return

        cat = self.combo_filter_cat.currentText()
        params: Dict[str, Any] = {"limit": 100}
        if cat != "ALL":
            params["category"] = cat

        res = self.ipc_call_handler("memory.get_all", params)
        if res and res.get("success"):
            self._loaded_memories = res.get("memories", [])
            self._populate_table(self._loaded_memories)

    def _on_search(self) -> None:
        """Perform semantic & keyword search."""
        query = self.search_input.text().strip()
        if not query:
            self.refresh_memories()
            return

        if not self.ipc_call_handler:
            return

        cat = self.combo_filter_cat.currentText()
        params: Dict[str, Any] = {"query": query, "limit": 25, "min_score": 0.15}
        if cat != "ALL":
            params["category"] = cat

        res = self.ipc_call_handler("memory.search", params)
        if res and res.get("success"):
            results = res.get("results", [])
            memories = [r["memory"] for r in results]
            self._loaded_memories = memories
            self._populate_table(memories)

    def _populate_table(self, memories: List[Dict[str, Any]]) -> None:
        """Render memory records into the Qt table."""
        self.table.setRowCount(len(memories))
        for row_idx, mem in enumerate(memories):
            self.table.setItem(row_idx, 0, QTableWidgetItem(mem.get("id", "")[:8] + "..."))
            self.table.setItem(row_idx, 1, QTableWidgetItem(mem.get("category", "")))
            self.table.setItem(row_idx, 2, QTableWidgetItem(mem.get("content", "")))
            self.table.setItem(row_idx, 3, QTableWidgetItem(f"{float(mem.get('importance', 0.5)):.2f}"))
            self.table.setItem(row_idx, 4, QTableWidgetItem(mem.get("source", "")))
            created = mem.get("created_at", "")[:19].replace("T", " ")
            self.table.setItem(row_idx, 5, QTableWidgetItem(created))

    def _get_selected_memory(self) -> Optional[Dict[str, Any]]:
        row = self.table.currentRow()
        if 0 <= row < len(self._loaded_memories):
            return self._loaded_memories[row]
        return None

    def _on_add_clicked(self) -> None:
        dlg = EditMemoryDialog(self, is_new=True)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            if not data["content"]:
                return
            if self.ipc_call_handler:
                self.ipc_call_handler("memory.create", data)
                self.refresh_memories()

    def _on_edit_clicked(self) -> None:
        mem = self._get_selected_memory()
        if not mem:
            QMessageBox.information(self, "No Selection", "Please select a memory to edit.")
            return

        dlg = EditMemoryDialog(
            self,
            category=mem.get("category", "PREFERENCE"),
            content=mem.get("content", ""),
            importance=float(mem.get("importance", 0.5)),
            project_name=mem.get("project_name"),
            is_new=False,
        )
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            if self.ipc_call_handler:
                self.ipc_call_handler("memory.update", {
                    "id": mem["id"],
                    "content": data["content"],
                    "importance": data["importance"],
                    "project_name": data["project_name"],
                })
                self.refresh_memories()

    def _on_delete_clicked(self) -> None:
        mem = self._get_selected_memory()
        if not mem:
            QMessageBox.information(self, "No Selection", "Please select a memory to delete.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete this memory?\n\n'{mem.get('content')}'",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes and self.ipc_call_handler:
            self.ipc_call_handler("memory.delete", {"id": mem["id"]})
            self.refresh_memories()

    def _on_delete_category_clicked(self) -> None:
        cat = self.combo_filter_cat.currentText()
        if cat == "ALL":
            QMessageBox.warning(self, "Select Category", "Please choose a specific category in the filter first.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Category Deletion",
            f"Are you sure you want to delete ALL memories in category '{cat}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes and self.ipc_call_handler:
            self.ipc_call_handler("memory.delete_category", {"category": cat})
            self.refresh_memories()

    def _on_clear_all_clicked(self) -> None:
        """Clear all personal memories with explicit confirmation security guard."""
        dialog = QDialog(self)
        dialog.setWindowTitle("SECURITY GUARD: CLEAR ALL MEMORIES")
        dialog.setStyleSheet("QDialog { background-color: #1e0b10; color: #ffcccc; }")
        d_layout = QVBoxLayout(dialog)

        lbl = QLabel(
            "CRITICAL: This will delete ALL stored personal memories.\n"
            "To confirm, type exactly:\nCONFIRM_CLEAR_ALL_MEMORIES",
            dialog,
        )
        lbl.setStyleSheet("color: #ff4455; font-weight: bold;")
        d_layout.addWidget(lbl)

        inp = QLineEdit(dialog)
        inp.setStyleSheet("background-color: #2b0e14; color: white; padding: 6px; border: 1px solid #ff4455;")
        d_layout.addWidget(inp)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        d_layout.addWidget(btn_box)

        if dialog.exec() == QDialog.Accepted:
            phrase = inp.text().strip()
            if phrase != "CONFIRM_CLEAR_ALL_MEMORIES":
                QMessageBox.critical(self, "Verification Failed", "Phrase did not match. Operation aborted.")
                return

            if self.ipc_call_handler:
                res = self.ipc_call_handler("memory.clear_all", {"confirmation_phrase": phrase})
                if res and res.get("success"):
                    QMessageBox.information(self, "Cleared", f"Successfully cleared {res.get('deleted_count')} memories.")
                    self.refresh_memories()
                else:
                    QMessageBox.critical(self, "Error", f"Failed to clear memories: {res.get('error') if res else 'Unknown'}")
