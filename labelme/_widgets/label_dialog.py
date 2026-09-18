from __future__ import annotations

import dataclasses
from collections.abc import Collection
from typing import Final
from typing import Literal

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets

from .._annotation_rules import AnnotationRules
from .._label_flags import compile_label_flags

LabelDialogField = Literal["label", "flags", "group_id", "description"]


@dataclasses.dataclass(frozen=True)
class LabelDialogEntry:
    label: str
    attributes: dict[str, object]
    flags: dict[str, bool]
    group_id: int | None
    description: str


_PLACEHOLDER_TEXT: Final[str] = "Enter object label"


class LabelDialog(QtWidgets.QDialog):
    """Dialog for entering label, group id, description, and flags."""

    def __init__(
        self,
        *,
        text: str = _PLACEHOLDER_TEXT,
        parent: QtWidgets.QWidget | None = None,
        labels: list[str] | None = None,
        shape_attributes: list[dict] | None = None,
        sort_labels: bool = True,
        show_text_field: bool = True,
        completion: str = "startswith",
        fit_to_content: dict[str, bool] | None = None,
        flags: dict[str, list[str]] | None = None,
        label_history: list[str] | None = None,
        annotation_rules: AnnotationRules | None = None,
        ) -> None:

        super().__init__(parent)
        dialog_name = self.tr("Shape Label")
        self.setWindowTitle(dialog_name)
        self.setAccessibleName(dialog_name)

        self._sort_labels = sort_labels
        self._show_text_field = show_text_field
        self._flags_spec = compile_label_flags(label_flags=flags)
        self._label_history = label_history[:] if label_history is not None else []
        self._annotation_rules = annotation_rules

        if self._annotation_rules is not None:
            self._attribute_specs = (
                self._annotation_rules.ui_attribute_specs()
            )
        else:
            self._attribute_specs = shape_attributes or []

        self._attribute_lists: dict[str, QtWidgets.QListWidget] = {}
        self._attribute_labels: dict[str, QtWidgets.QLabel] = {}
        self._layout_attribute_keys: set[str] = set()
        self._required_attribute_keys: set[str] = set()
        self._attribute_columns: dict[str, int] = {}
        self._updating_attributes = False
        # Fields the current popup shows read-only because the caller has no
        # single value for them (a mixed multi-selection).
        self._locked: frozenset[LabelDialogField] = frozenset()
        self._locked_attributes: frozenset[str] = frozenset()
        # A popup opened without a label starts from the last one accepted.
        self._last_label = ""
        # The flags currently on show, keyed by flag name, so a flag named by
        # two matching label_flags patterns gets exactly one checkbox.
        self._flag_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        # Checked state per flag key, remembered for the lifetime of one popup.
        # The checkboxes themselves cannot hold it: editing the label rebuilds
        # them, and an intermediate keystroke that matches no pattern destroys
        # them entirely.
        self._flag_states: dict[str, bool] = {}

        if fit_to_content is None:
            fit_to_content = {"row": False, "column": True}
        self._fit_to_content = fit_to_content

        # Build widgets
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(text)
        self.edit.setAccessibleName(self.tr("Label"))

        group_id_name = self.tr("Group ID")
        self.edit_group_id = QtWidgets.QLineEdit()
        self.edit_group_id.setPlaceholderText(group_id_name)
        self.edit_group_id.setAccessibleName(group_id_name)
        self.edit_group_id.setValidator(
            QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"[0-9]*"))
        )

        description_name = self.tr("Description")
        self.edit_description = QtWidgets.QTextEdit()
        self.edit_description.setPlaceholderText(description_name)
        self.edit_description.setAccessibleName(description_name)
        self.edit_description.setFixedHeight(50)

        self.label_list = QtWidgets.QListWidget()
        self._active_label = ""
        self._last_weapon_type_selection: tuple[object, ...] = ()
        self._weapon_direction_lists: dict[object, QtWidgets.QListWidget] = {}

        # Vehicle weapon direction area.
        # One selected weapon -> one direction list.
        # Two selected weapons -> two lists stacked vertically.
        self._weapon_direction_container = QtWidgets.QWidget()
        self._weapon_direction_layout = QtWidgets.QVBoxLayout()
        self._weapon_direction_layout.setContentsMargins(0, 0, 0, 0)
        self._weapon_direction_layout.setSpacing(4)
        self._weapon_direction_container.setLayout(
            self._weapon_direction_layout
        )
        
        # Build custom attribute lists
        for spec in self._attribute_specs:
            key = spec["key"]

            attribute_list = QtWidgets.QListWidget()
            attribute_list.setSelectionMode(
                QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
            )

            self._populate_attribute_list(
                attribute_list,
                spec.get("options", []),
            )

            self._attribute_lists[key] = attribute_list
            
        # Make selected items clearly visible
        for list_widget in [
            self.label_list,
            *self._attribute_lists.values(),
        ]:
            palette = list_widget.palette()

            for color_group in (
                QtGui.QPalette.ColorGroup.Active,
                QtGui.QPalette.ColorGroup.Inactive,
            ):
                palette.setColor(
                    color_group,
                    QtGui.QPalette.ColorRole.Highlight,
                    QtGui.QColor("#0D47A1"),
                )
                palette.setColor(
                    color_group,
                    QtGui.QPalette.ColorRole.HighlightedText,
                    QtGui.QColor("white"),
                )

            list_widget.setPalette(palette)
            
        # Configure label list
        if sort_labels:
            self.label_list.setDragDropMode(
                QtWidgets.QAbstractItemView.DragDropMode.NoDragDrop
            )
        else:
            self.label_list.setDragDropMode(
                QtWidgets.QAbstractItemView.DragDropMode.InternalMove
            )

        if fit_to_content["row"]:
            self.label_list.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        if fit_to_content["column"]:
            self.label_list.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )

        # Set up completer bound to label_list's model
        completer = self._make_completer(completion=completion)
        self.edit.setCompleter(completer)
        # Up/Down are taken before the line edit sees them so the arrow keys walk
        # the label list while every other key keeps editing the text.
        self.edit.installEventFilter(self)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self._ok_button = button_box.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )

        # Build layout
        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        if show_text_field:
            top_row = QtWidgets.QHBoxLayout()
            top_row.addWidget(self.edit, stretch=4)
            top_row.addWidget(self.edit_group_id, stretch=1)
            main_layout.addLayout(top_row)
        else:
            self.edit.hide()

        selection_layout = QtWidgets.QGridLayout()
        self._selection_layout = selection_layout
        selection_layout.setHorizontalSpacing(6)
        selection_layout.setVerticalSpacing(4)

        # Class
        selection_layout.addWidget(
            QtWidgets.QLabel(self.tr("Class")),
            0,
            0,
        )
        selection_layout.addWidget(
            self.label_list,
            1,
            0,
        )

        # Custom attributes
        for column, spec in enumerate(self._attribute_specs, start=1):
            key = spec["key"]
            self._attribute_columns[key] = column
            title = spec.get("label", key)

            title_label = QtWidgets.QLabel(title)
            self._attribute_labels[key] = title_label

            selection_layout.addWidget(
                title_label,
                0,
                column,
            )

            if key == "무기방향":
                selection_layout.addWidget(
                    self._weapon_direction_container,
                    1,
                    column,
                )
            else:
                selection_layout.addWidget(
                    self._attribute_lists[key],
                    1,
                    column,
                )
        
        for column in range(1 + len(self._attribute_specs)):
            selection_layout.setColumnStretch(column, 1)

        main_layout.addLayout(selection_layout)

        self._flags_container = QtWidgets.QWidget()
        self._flags_layout = QtWidgets.QVBoxLayout()
        self._flags_layout.setContentsMargins(0, 0, 0, 0)
        self._flags_layout.setSpacing(0)
        self._flags_container.setLayout(self._flags_layout)

        self._flags_scroll = QtWidgets.QScrollArea()
        self._flags_scroll.setWidgetResizable(True)
        self._flags_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._flags_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._flags_scroll.setWidget(self._flags_container)
        main_layout.addWidget(self._flags_scroll)

        main_layout.addWidget(button_box)

        # Connect signals
        self.edit.textChanged.connect(self._on_text_changed)
        self.label_list.currentItemChanged.connect(self._on_label_selected)
        
        for key, attribute_list in self._attribute_lists.items():
            if key == "무기타입":
                attribute_list.itemSelectionChanged.connect(
                    self._on_weapon_type_selection_changed
                )
            else:
                attribute_list.currentItemChanged.connect(
                    self._on_attribute_changed
                )

        
        # Populate initial labels
        for label in dict.fromkeys([*(labels or []), *self._label_history]):
            self.label_list.addItem(label)
        if sort_labels:
            self.label_list.sortItems()

        self._refresh_ok_button()

    @property
    def label_history(self) -> list[str]:
        return self._label_history[:]
    
    @staticmethod
    def _option_text(value: object) -> str:
        if value == "None":
            return "없음"

        if isinstance(value, bool):
            return "true" if value else "false"

        if value is None:
            return "null"

        return str(value)


    def _populate_attribute_list(
        self,
        attribute_list: QtWidgets.QListWidget,
        options: list[object],
        selected_value: object | None = None,
    ) -> None:
        attribute_list.clear()

        selected_item = None

        for option in options:
            item = QtWidgets.QListWidgetItem(
                self._option_text(option)
            )
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole,
                option,
            )

            attribute_list.addItem(item)

            if selected_value is not None and option == selected_value:
                selected_item = item
        if selected_item is not None:
            attribute_list.setCurrentItem(selected_item)

        elif attribute_list.count() == 1:
            attribute_list.setCurrentRow(0)

        else:
            attribute_list.setCurrentRow(-1)
            attribute_list.clearSelection()

        
    def _apply_attribute_rules(
        self,
        label: str,
    ) -> None:
        if self._annotation_rules is None:
            return

        if self._updating_attributes:
            return

        self._updating_attributes = True

        try:
            self._active_label = label

            layout_keys = (
                self._annotation_rules
                .layout_attribute_keys(label)
            )

            self._layout_attribute_keys = set(
                layout_keys
            )

            self._required_attribute_keys.clear()

            for key, attribute_list in (
                self._attribute_lists.items()
            ):
                title_label = self._attribute_labels[key]
                column = self._attribute_columns[key]

                # 무기방향은 기존 QListWidget 대신
                # 선택된 무기 수에 맞춘 동적 리스트 영역을 사용합니다.
                if key == "무기방향":
                    continue

                if key not in self._layout_attribute_keys:
                    with QtCore.QSignalBlocker(
                        attribute_list
                    ):
                        attribute_list.clear()
                        attribute_list.clearSelection()
                        attribute_list.setCurrentRow(-1)

                    title_label.hide()
                    attribute_list.hide()

                    self._selection_layout.setColumnStretch(
                        column,
                        0,
                    )
                    continue

                title_label.show()
                attribute_list.show()

                self._selection_layout.setColumnStretch(
                    column,
                    1,
                )

                options = (
                    self._annotation_rules
                    .options_for(
                        label,
                        key,
                    )
                )

                if key == "무기타입":
                    if (
                        self._annotation_rules
                        .allows_multiple_weapon_types(label)
                    ):
                        selection_mode = (
                            QtWidgets.QAbstractItemView
                            .SelectionMode.MultiSelection
                        )
                    else:
                        selection_mode = (
                            QtWidgets.QAbstractItemView
                            .SelectionMode.SingleSelection
                        )

                    attribute_list.setSelectionMode(
                        selection_mode
                    )

                with QtCore.QSignalBlocker(
                    attribute_list
                ):
                    self._populate_attribute_list(
                        attribute_list,
                        options,
                    )

                if not options:
                    attribute_list.setEnabled(False)
                    continue

                attribute_list.setEnabled(True)
                self._required_attribute_keys.add(key)

            direction_label = self._attribute_labels.get(
                "무기방향"
            )
            direction_column = self._attribute_columns.get(
                "무기방향"
            )

            if "무기방향" in self._layout_attribute_keys:
                if direction_label is not None:
                    direction_label.show()

                self._weapon_direction_container.show()

                if direction_column is not None:
                    self._selection_layout.setColumnStretch(
                        direction_column,
                        1,
                    )

                self._rebuild_weapon_direction_lists(label)
            else:
                if direction_label is not None:
                    direction_label.hide()

                self._weapon_direction_container.hide()
                self._clear_weapon_direction_lists()

                if direction_column is not None:
                    self._selection_layout.setColumnStretch(
                        direction_column,
                        0,
                    )

            self._last_weapon_type_selection = tuple(
                self._selected_weapon_types()
            )

            self._refresh_ok_button()
            self._fit_label_list_to_content()

        finally:
            self._updating_attributes = False


    def _select_attribute_value(
        self,
        key: str,
        value: object,
    ) -> None:
        attribute_list = self._attribute_lists[key]

        for row in range(attribute_list.count()):
            item = attribute_list.item(row)

            if item.data(QtCore.Qt.ItemDataRole.UserRole) == value:
                attribute_list.setCurrentItem(item)
                return

            if item.text() == str(value):
                attribute_list.setCurrentItem(item)
                return

    def _make_completer(self, *, completion: str) -> QtWidgets.QCompleter:
        if completion == "startswith":
            completer = QtWidgets.QCompleter(self.label_list.model())
            completer.setCompletionMode(
                QtWidgets.QCompleter.CompletionMode.InlineCompletion
            )
            return completer
        elif completion == "contains":
            completer = QtWidgets.QCompleter(self.label_list.model())
            completer.setCompletionMode(
                QtWidgets.QCompleter.CompletionMode.PopupCompletion
            )
            completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            return completer
        else:
            raise ValueError(f"Unknown completion mode: {completion!r}")

    def _on_text_changed(self, text: str, /) -> None:
        # Leading whitespace never belongs to a label, so undo it as it is typed;
        # the re-entrant signal then handles the corrected text.
        if text != text.lstrip():
            self.edit.setText(text.lstrip())
            return
        self._refresh_ok_button()
        if "flags" not in self._locked:
            self._update_flags(text)

    def _refresh_ok_button(self) -> None:
        label_selected = (
            "label" in self._locked
            or self.label_list.currentItem() is not None
        )

        attributes_selected = True

        for key in self._required_attribute_keys:
            if key in self._locked_attributes:
                continue

            if key == "무기타입":
                if not self._selected_weapon_types():
                    attributes_selected = False
                    break
            else:
                attribute_list = self._attribute_lists[key]

                if attribute_list.currentItem() is None:
                    attributes_selected = False
                    break

        directions_valid = (
            self._weapon_directions_are_valid()
        )

        self._ok_button.setEnabled(
            label_selected
            and attributes_selected
            and directions_valid
        )
        
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent, /) -> bool:
        if watched is self.edit and event.type() == QtCore.QEvent.Type.KeyPress:
            assert isinstance(event, QtGui.QKeyEvent)
            step = {QtCore.Qt.Key.Key_Up: -1, QtCore.Qt.Key.Key_Down: 1}.get(
                QtCore.Qt.Key(event.key())
            )
            if step is not None:
                row = self.label_list.currentRow() + step
                self.label_list.setCurrentRow(
                    min(max(row, 0), self.label_list.count() - 1)
                )
                return True
        return super().eventFilter(watched, event)

    def _on_label_selected(
        self,
        current: QtWidgets.QListWidgetItem | None,
        _previous: QtWidgets.QListWidgetItem | None,
        /,
    ) -> None:
        if current is None:
            return

        label = current.text()

        self._apply_attribute_rules(label)
        self.edit.setText(label)

    def _clear_flag_checkboxes(self) -> None:
        self._flag_checkboxes.clear()
        while self._flags_layout.count():
            item = self._flags_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _update_flags(self, text: str, /) -> None:
        self._flag_states.update(self._collect_flags())
        flags: dict[str, bool] = {}
        for pattern, flag_keys in self._flags_spec.items():
            if not pattern.match(text):
                continue
            for key in flag_keys:
                flags[key] = self._flag_states.get(key, False)
        self._set_flag_checkboxes(flags=flags)

    def add_label_history(self, *, label: str) -> None:
        if label not in self._label_history:
            self._label_history.append(label)

        if self.label_list.findItems(label, QtCore.Qt.MatchFlag.MatchExactly):
            return
        self.label_list.addItem(label)
        if self._sort_labels:
            self.label_list.sortItems()

    def set_predefined_labels(self, *, labels: list[str]) -> None:
        history_extras = [h for h in self._label_history if h not in labels]
        all_labels = list(dict.fromkeys(labels)) + history_extras

        self.label_list.clear()
        for label in all_labels:
            self.label_list.addItem(label)

        if self._sort_labels:
            self.label_list.sortItems()

    def remember_label(self, *, label: str) -> None:
        self._last_label = label

    def _find_label_row(self, text: str, /) -> int:
        # Match through the model so the highlight folds case the way Qt's own
        # text matching does; Python's folding differs on the sharp s, say.
        model = self.label_list.model()
        hits = model.match(
            model.index(0, 0),
            QtCore.Qt.ItemDataRole.DisplayRole,
            text,
            flags=QtCore.Qt.MatchFlag.MatchFixedString,
        )
        return hits[0].row() if hits else -1

    def popup(
        self,
        *,
        text: str | None = None,
        attributes: dict[str, object] | None = None,
        flags: dict[str, bool] | None = None,
        group_id: int | None = None,
        description: str | None = None,
        locked: Collection[LabelDialogField] = (),
        move: bool = True,
        position: QtCore.QPoint | None = None,
    ) -> LabelDialogEntry | None:
        self._locked = frozenset(locked)
        # Drop the previous popup's checkboxes and their remembered states so a
        # fresh popup starts unchecked. This has to precede setText() below,
        # whose textChanged signal would otherwise re-seed the states from the
        # previous popup's checkboxes; the flags block below rebuilds them.
        self._flag_states.clear()
        self._clear_flag_checkboxes()

        # A locked field shows nothing: the caller's value is not shared by the
        # whole selection, and the field is skipped when the entry is applied.
        for name, widgets in self._get_field_widgets().items():
            for widget in widgets:
                widget.setEnabled(name not in self._locked)
        if "label" in self._locked or text is None:
            text = ""
        if "group_id" in self._locked:
            group_id = None
        if "description" in self._locked:
            description = None
        if "flags" in self._locked:
            flags = {}

        self.edit.setText(text)
        # Read the text back: a stored label with leading whitespace is shown
        # normalized, and the flags and list match must follow what is shown.
        text = self.edit.text()
        self.edit.selectAll()
        self.edit_group_id.setText("" if group_id is None else str(group_id))
        self.edit_description.setPlainText(description or "")

        # Reset / restore custom attributes
        attributes = attributes or {}

        for attribute_list in self._attribute_lists.values():
            with QtCore.QSignalBlocker(attribute_list):
                attribute_list.clearSelection()
                attribute_list.setCurrentRow(-1)

        self._clear_weapon_direction_lists()
        self._active_label = ""
        self._last_weapon_type_selection = ()

        # Select the stored class without firing _on_label_selected while
        # attributes are being restored.
        with QtCore.QSignalBlocker(self.label_list):
            self.label_list.setCurrentRow(
                self._find_label_row(text)
            )

        self._apply_attribute_rules(text)

        # 시선방향 복원
        if "시선방향" in self._layout_attribute_keys:
            value = attributes.get("시선방향")

            if value is not None:
                self._select_attribute_value(
                    "시선방향",
                    value,
                )

        # 무기타입 복원
        weapon_types = attributes.get("무기타입")

        if (
            "무기타입" in self._layout_attribute_keys
            and weapon_types is not None
        ):
            self._set_weapon_type_values(weapon_types)

        # 차량 무기방향 복원.
        # 무기타입[i]와 무기방향[i]의 대응을 유지합니다.
        if "무기방향" in self._layout_attribute_keys:
            if isinstance(weapon_types, list):
                type_values = list(weapon_types)
            elif weapon_types is None:
                type_values = []
            else:
                type_values = [weapon_types]

            raw_directions = attributes.get(
                "무기방향"
            )

            if isinstance(raw_directions, list):
                direction_values = list(
                    raw_directions
                )
            elif raw_directions is None:
                direction_values = []
            else:
                direction_values = [
                    raw_directions
                ]

            direction_by_type: dict[object, object] = {}

            for index, weapon_type in enumerate(
                type_values
            ):
                direction = (
                    direction_values[index]
                    if index < len(direction_values)
                    else None
                )

                direction_by_type[weapon_type] = direction

            self._rebuild_weapon_direction_lists(
                text,
                direction_by_type,
            )

        if flags is None:
            self._update_flags(text)
        else:
            self._set_flag_checkboxes(flags=flags)

        self._fit_label_list_to_content()
        self.adjustSize()
        self._refresh_ok_button()

        if self._show_text_field:
            self.edit.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)
        else:
            self.label_list.setFocus(QtCore.Qt.FocusReason.PopupFocusReason)

        if move:
            target = position if position is not None else QtGui.QCursor.pos()
            self._move_within_screen(target)
            # frameGeometry() lacks the window-manager decoration size until the
            # dialog is mapped, so re-clamp once exec() has shown it. Clamp only
            # (no re-anchor to target): a full re-move visibly jerks the already
            # visible dialog, while the clamp is a no-op unless it overflows.
            QtCore.QTimer.singleShot(0, lambda: self._clamp_within_screen(target))

        if self.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None

        # The flag checkboxes follow the text, so normalize it before they are
        # collected: "cat " must yield the flags of "cat", not none.
        self.edit.setText(self.edit.text().strip())
        group_id_text = self.edit_group_id.text()
        entry = LabelDialogEntry(
            label=self.edit.text(),
            attributes=self._collect_attributes(),
            flags=self._collect_flags(),
            group_id=int(group_id_text) if group_id_text else None,
            description=self.edit_description.toPlainText(),
        )
        # A locked label is accepted as blank, and the next new-shape popup
        # starts blank too, exactly as a cancelled locked edit leaves it.
        self.remember_label(label=entry.label)
        return entry

    def _get_field_widgets(
        self,
    ) -> dict[LabelDialogField, tuple[QtWidgets.QWidget, ...]]:
        return {
            "label": (self.edit, self.label_list),
            "flags": (self._flags_container,),
            "group_id": (self.edit_group_id,),
            "description": (self.edit_description,),
        }

    def _set_flag_checkboxes(self, *, flags: dict[str, bool]) -> None:
        FLAGS_SCROLL_MAX_HEIGHT: Final[int] = 150

        self._clear_flag_checkboxes()
        for key, checked in flags.items():
            checkbox = QtWidgets.QCheckBox(key)
            checkbox.setChecked(checked)
            self._flag_checkboxes[key] = checkbox
            self._flags_layout.addWidget(checkbox)
            # A widget added to a visible layout stays hidden until the event
            # loop activates the layout, and the layout counts hidden widgets as
            # empty, so the container hint below would be momentarily 0 and
            # would pin the scroll area shut for the rest of the popup.
            checkbox.show()

        content_height = self._flags_container.sizeHint().height()
        self._flags_scroll.setFixedHeight(min(content_height, FLAGS_SCROLL_MAX_HEIGHT))

    def _collect_flags(self) -> dict[str, bool]:
        return {key: cb.isChecked() for key, cb in self._flag_checkboxes.items()}
    
    def _collect_attributes(
        self,
    ) -> dict[str, object]:
        attributes: dict[str, object] = {}

        # 시선방향
        direction_list = self._attribute_lists.get(
            "시선방향"
        )

        if direction_list is not None:
            item = direction_list.currentItem()

            if item is not None:
                attributes["시선방향"] = item.data(
                    QtCore.Qt.ItemDataRole.UserRole
                )

        weapon_types = self._selected_weapon_types()

        # --------------------------------------------------
        # 차량
        # --------------------------------------------------
        if (
            "무기방향"
            in self._layout_attribute_keys
        ):
            if not weapon_types:
                return attributes

            weapon_directions: list[object] = []

            for weapon_type in weapon_types:
                if weapon_type == "None":
                    weapon_directions.append(None)
                    continue

                direction_list = (
                    self._weapon_direction_lists.get(
                        weapon_type
                    )
                )

                direction = None

                if direction_list is not None:
                    item = direction_list.currentItem()

                    if item is not None:
                        direction = item.data(
                            QtCore.Qt.ItemDataRole.UserRole
                        )

                weapon_directions.append(
                    direction
                )

            # 실제 복수 선택된 경우에만 list
            if len(weapon_types) >= 2:
                attributes["무기타입"] = weapon_types
                attributes["무기방향"] = weapon_directions

            # 하나만 선택했으면 기존과 동일한 단일 값
            else:
                attributes["무기타입"] = weapon_types[0]
                attributes["무기방향"] = weapon_directions[0]

            return attributes

        # --------------------------------------------------
        # 사람
        # --------------------------------------------------
        if weapon_types:
            attributes["무기타입"] = weapon_types[0]

        return attributes
    
    def _fit_label_list_to_content(self) -> None:
        lists = [
            self.label_list,
        ]

        for key, attribute_list in (
            self._attribute_lists.items()
        ):
            if key not in self._layout_attribute_keys:
                continue

            if key == "무기방향":
                continue

            lists.append(attribute_list)

        max_count = max(
            (
                list_widget.count()
                for list_widget in lists
            ),
            default=1,
        )

        row_height = (
            self.label_list.sizeHintForRow(0)
        )

        if row_height <= 0:
            row_height = (
                self.label_list
                .fontMetrics()
                .height()
                + 8
            )

        height = (
            row_height * max_count
            + self.label_list.frameWidth() * 2
            + 8
        )

        height = max(
            180,
            min(height, 360),
        )

        for list_widget in lists:
            list_widget.setMinimumWidth(220)
            list_widget.setFixedHeight(height)

        if "무기방향" in self._layout_attribute_keys:
            self._weapon_direction_container.setMinimumWidth(220)
            self._weapon_direction_container.setFixedHeight(
                height
            )

    def _move_within_screen(self, target: QtCore.QPoint, /) -> None:
        self.adjustSize()
        # setGeometry() anchors the client area, unlike move() which anchors the
        # window frame: the content corner lands at target, not the title bar's.
        self.setGeometry(QtCore.QRect(target, self.size()))
        self._clamp_within_screen(target)

    def _clamp_within_screen(self, target: QtCore.QPoint, /) -> None:
        screen = (
            QtGui.QGuiApplication.screenAt(target)
            or QtGui.QGuiApplication.primaryScreen()
        )
        if screen is None:
            return
        available = screen.availableGeometry()

        # Nudge by the actual frame overflow (frameGeometry() includes the
        # window-manager decoration) so the title bar and borders stay on screen,
        # not just the content rect.
        frame = self.frameGeometry()
        dx = min(0, available.right() - frame.right())
        dx = max(dx, available.left() - frame.left())
        dy = min(0, available.bottom() - frame.bottom())
        dy = max(dy, available.top() - frame.top())
        if dx or dy:
            self.move(self.x() + dx, self.y() + dy)
    
    def _current_attributes(
        self,
    ) -> dict[str, object]:
        attributes: dict[str, object] = {}

        for key, attribute_list in (
            self._attribute_lists.items()
        ):
            item = attribute_list.currentItem()

            if item is None:
                continue

            attributes[key] = item.data(
                QtCore.Qt.ItemDataRole.UserRole
            )

        return attributes
    
    def _on_attribute_changed(
        self,
        _current: QtWidgets.QListWidgetItem | None,
        _previous: QtWidgets.QListWidgetItem | None,
    ) -> None:
        if self._updating_attributes:
            return

        self._refresh_ok_button()
    
    def _selected_weapon_types(
        self,
    ) -> list[object]:
        weapon_list = self._attribute_lists.get(
            "무기타입"
        )

        if weapon_list is None:
            return []

        values: list[object] = []

        # 화면의 위→아래 순서를 그대로 저장 순서로 사용합니다.
        for row in range(weapon_list.count()):
            item = weapon_list.item(row)

            if item.isSelected():
                values.append(
                    item.data(
                        QtCore.Qt.ItemDataRole.UserRole
                    )
                )

        return values

    def _weapon_directions_are_valid(
        self,
    ) -> bool:
        if (
            "무기방향"
            not in self._layout_attribute_keys
        ):
            return True

        for weapon_type in self._selected_weapon_types():
            if weapon_type == "None":
                continue

            direction_list = (
                self._weapon_direction_lists.get(
                    weapon_type
                )
            )

            # 방향 선택지가 없는 무기라면 방향 입력을 요구하지 않습니다.
            if direction_list is None:
                continue

            if direction_list.currentItem() is None:
                return False

        return True

    def _set_weapon_type_values(
        self,
        values: object,
    ) -> None:
        weapon_list = self._attribute_lists.get(
            "무기타입"
        )

        if weapon_list is None:
            return

        if isinstance(values, list):
            target_values = list(values)
        else:
            target_values = [values]

        # None은 다른 무기와 공존 불가
        if "None" in target_values:
            target_values = ["None"]

        with QtCore.QSignalBlocker(weapon_list):
            weapon_list.clearSelection()
            weapon_list.setCurrentRow(-1)

            multi = (
                weapon_list.selectionMode()
                == QtWidgets.QAbstractItemView.SelectionMode.MultiSelection
            )

            for row in range(weapon_list.count()):
                item = weapon_list.item(row)

                value = item.data(
                    QtCore.Qt.ItemDataRole.UserRole
                )

                if value not in target_values:
                    continue

                if multi:
                    item.setSelected(True)
                else:
                    weapon_list.setCurrentItem(item)
                    break

        self._last_weapon_type_selection = tuple(
            self._selected_weapon_types()
        )
    
    def _clear_weapon_direction_lists(
        self,
    ) -> None:
        self._weapon_direction_lists.clear()

        while self._weapon_direction_layout.count():
            item = self._weapon_direction_layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
    
    def _rebuild_weapon_direction_lists(
        self,
        label: str,
        direction_by_type: dict[object, object] | None = None,
    ) -> None:
        if self._annotation_rules is None:
            return

        self._clear_weapon_direction_lists()

        direction_by_type = direction_by_type or {}

        for weapon_type in self._selected_weapon_types():
            # 없음은 방향 없음
            if weapon_type == "None":
                continue

            options = (
                self._annotation_rules
                .weapon_direction_options(
                    label,
                    weapon_type,
                )
            )

            if not options:
                continue

            section = QtWidgets.QWidget()
            section_layout = QtWidgets.QVBoxLayout()
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(2)
            section.setLayout(section_layout)

            weapon_label = QtWidgets.QLabel(
                self._option_text(weapon_type)
            )

            direction_list = QtWidgets.QListWidget()
            direction_list.setSelectionMode(
                QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
            )
            direction_list.setPalette(
                self.label_list.palette()
            )

            selected_direction = direction_by_type.get(
                weapon_type
            )

            self._populate_attribute_list(
                direction_list,
                options,
                selected_value=selected_direction,
            )

            direction_list.currentItemChanged.connect(
                self._on_attribute_changed
            )

            self._weapon_direction_lists[
                weapon_type
            ] = direction_list

            section_layout.addWidget(weapon_label)
            section_layout.addWidget(direction_list)

            # 1개면 전체 사용
            # 2개면 QVBoxLayout에서 위/아래로 자동 분할
            self._weapon_direction_layout.addWidget(
                section,
                1,
            )
    
    def _on_weapon_type_selection_changed(
        self,
    ) -> None:
        if self._updating_attributes:
            return

        if self._annotation_rules is None:
            return

        label = self._active_label

        if not label:
            return

        weapon_list = self._attribute_lists.get(
            "무기타입"
        )

        if weapon_list is None:
            return

        previous = list(
            self._last_weapon_type_selection
        )

        current = self._selected_weapon_types()

        # 복수선택 클래스에서 None 배타 처리
        if (
            self._annotation_rules
            .allows_multiple_weapon_types(label)
            and "None" in current
            and len(current) > 1
        ):
            # 기존에는 None이 없었는데 이번에 None을 눌렀다면
            # None만 남김
            if "None" not in previous:
                target = ["None"]

            # 기존 None 상태에서 실제 무기를 눌렀다면
            # None 제거
            else:
                target = [
                    value
                    for value in current
                    if value != "None"
                ]

            with QtCore.QSignalBlocker(weapon_list):
                for row in range(
                    weapon_list.count()
                ):
                    item = weapon_list.item(row)

                    value = item.data(
                        QtCore.Qt.ItemDataRole.UserRole
                    )

                    item.setSelected(
                        value in target
                    )

            current = self._selected_weapon_types()

        # 무기 조합이 바뀌었으면 방향 전부 초기화
        if tuple(current) != tuple(previous):
            self._last_weapon_type_selection = tuple(
                current
            )

            if "무기방향" in self._layout_attribute_keys:
                self._rebuild_weapon_direction_lists(
                    label
                )

        self._refresh_ok_button()