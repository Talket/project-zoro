"""UI tests for Personal Memory Management Panel."""

from __future__ import annotations

import sys
import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication

from zoro.ui.memory_panel import EditMemoryDialog, ZoroMemoryDialog


@pytest.fixture(scope="module")
def qapp():
    """Ensure QApplication instance is initialized."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_edit_memory_dialog(qapp) -> None:
    """Verify EditMemoryDialog initialization and data retrieval."""
    dlg = EditMemoryDialog(
        category="PROJECT",
        content="Developing Zoro Autonomous Agent",
        importance=0.9,
        project_name="Zoro",
        is_new=False,
    )
    try:
        assert dlg.combo_cat.currentText() == "PROJECT"
        assert dlg.txt_content.toPlainText() == "Developing Zoro Autonomous Agent"
        assert dlg.spin_importance.value() == 0.9
        assert dlg.edit_project.text() == "Zoro"

        data = dlg.get_data()
        assert data["category"] == "PROJECT"
        assert data["content"] == "Developing Zoro Autonomous Agent"
        assert data["importance"] == 0.9
        assert data["project_name"] == "Zoro"
    finally:
        dlg.close()


def test_zoro_memory_dialog_table_population(qapp) -> None:
    """Verify ZoroMemoryDialog populates table from IPC handler response."""
    mock_ipc = MagicMock()
    mock_ipc.return_value = {
        "success": True,
        "memories": [
            {
                "id": "mem-1234-5678-90ab",
                "category": "IDENTITY",
                "content": "Owner's name is Alice.",
                "importance": 0.95,
                "source": "explicit_user",
                "created_at": "2026-11-19T01:00:00Z",
            },
            {
                "id": "mem-9876-5432-10fe",
                "category": "PREFERENCE",
                "content": "Owner prefers dark mode.",
                "importance": 0.80,
                "source": "extracted_conversation",
                "created_at": "2026-11-19T01:05:00Z",
            },
        ],
    }

    dlg = ZoroMemoryDialog(ipc_call_handler=mock_ipc)
    try:
        assert dlg.table.rowCount() == 2
        # Verify row 0
        assert "IDENTITY" in dlg.table.item(0, 1).text()
        assert "Alice" in dlg.table.item(0, 2).text()
        # Verify row 1
        assert "PREFERENCE" in dlg.table.item(1, 1).text()
        assert "dark mode" in dlg.table.item(1, 2).text()
    finally:
        dlg.close()


def test_zoro_memory_dialog_search_dispatch(qapp) -> None:
    """Verify searching queries memory.search endpoint."""
    mock_ipc = MagicMock()
    mock_ipc.return_value = {
        "success": True,
        "results": [
            {
                "memory": {
                    "id": "mem-1111",
                    "category": "PROJECT",
                    "content": "Restaurant POS project",
                    "importance": 0.85,
                    "source": "explicit_user",
                    "created_at": "2026-11-19T01:00:00Z",
                },
                "score": 0.75,
                "match_type": "semantic",
            }
        ],
    }

    dlg = ZoroMemoryDialog(ipc_call_handler=mock_ipc)
    try:
        dlg.search_input.setText("restaurant")
        dlg._on_search()

        mock_ipc.assert_called_with(
            "memory.search",
            {"query": "restaurant", "limit": 25, "min_score": 0.15},
        )
        assert dlg.table.rowCount() == 1
        assert "Restaurant POS" in dlg.table.item(0, 2).text()
    finally:
        dlg.close()
