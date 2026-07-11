"""Shared selection styling for emulator dialog item views."""

from gui_components.profile_list_manager import ProfileSelectionDelegate


def apply_profile_selection_style(item_view, parent=None):
    """Apply the main profile table's single/multi-selection appearance."""
    settings = getattr(parent, "current_settings", {}) if parent else {}
    is_dark_mode = settings.get("theme", "dark") == "dark"
    delegate = ProfileSelectionDelegate(
        item_view,
        is_dark_mode=is_dark_mode,
        table_widget=item_view,
    )
    item_view.setItemDelegate(delegate)
    item_view.itemSelectionChanged.connect(item_view.viewport().update)
    return delegate
