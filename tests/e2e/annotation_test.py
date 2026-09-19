from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from ..conftest import assert_labelfile_sanity
from ..conftest import close_or_pause
from .conftest import MainWinFactory
from .conftest import show_window_and_wait_for_imagedata


@pytest.mark.gui
@pytest.mark.parametrize(
    (
        "create_mode",
        "setup_clicks",
        "finalize_click",
        "finalize_modifier",
        "expected_num_points",
    ),
    [
        pytest.param(
            "polygon",
            [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)],
            (0.25, 0.25),
            Qt.KeyboardModifier.NoModifier,
            4,
            id="polygon",
        ),
        pytest.param(
            "rectangle",
            [(0.25, 0.25)],
            (0.75, 0.75),
            Qt.KeyboardModifier.NoModifier,
            2,
            id="rectangle",
        ),
        pytest.param(
            "oriented_rectangle",
            [(0.25, 0.5), (0.5, 0.5)],
            (0.5, 0.75),
            Qt.KeyboardModifier.NoModifier,
            4,
            id="oriented_rectangle",
        ),
        pytest.param(
            "circle",
            [(0.5, 0.5)],
            (0.75, 0.5),
            Qt.KeyboardModifier.NoModifier,
            2,
            id="circle",
        ),
        pytest.param(
            "line",
            [(0.25, 0.25)],
            (0.75, 0.75),
            Qt.KeyboardModifier.NoModifier,
            2,
            id="line",
        ),
        pytest.param(
            "point",
            [],
            (0.5, 0.5),
            Qt.KeyboardModifier.NoModifier,
            1,
            id="point",
        ),
        pytest.param(
            "linestrip",
            [(0.25, 0.25), (0.5, 0.5)],
            (0.75, 0.75),
            Qt.KeyboardModifier.ControlModifier,
            3,
            id="linestrip",
        ),
    ],
)
def test_annotate_shape_types(
    *,
    main_win: MainWinFactory,
    qtbot: QtBot,
    data_path: Path,
    tmp_path: Path,
    pause: bool,
    create_mode: str,
    setup_clicks: list[tuple[float, float]],
    finalize_click: tuple[float, float],
    finalize_modifier: Qt.KeyboardModifier,
    expected_num_points: int,
) -> None:
    input_file = str(data_path / "raw/2011_000003.jpg")
    out_file = str(tmp_path / "2011_000003.json")

    win = main_win(
        file_or_dir=input_file,
        config_overrides=dict(auto_save=True),
        output_dir=str(tmp_path),
    )
    show_window_and_wait_for_imagedata(qtbot=qtbot, win=win)

    label = "test_shape"
    canvas = win._canvas_widgets.canvas

    canvas_size = canvas.size()

    def to_pos(xy: tuple[float, float]) -> QPoint:
        return QPoint(
            int(canvas_size.width() * xy[0]),
            int(canvas_size.height() * xy[1]),
        )

    win._switch_canvas_mode(
        edit=False,
        create_mode=create_mode,
    )
    qtbot.wait(50)

    def click(
        xy: tuple[float, float],
        modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ) -> None:
        pos = to_pos(xy)
        qtbot.mouseMove(canvas, pos=pos)
        qtbot.wait(50)
        qtbot.mouseClick(
            canvas,
            Qt.MouseButton.LeftButton,
            modifier,
            pos=pos,
        )
        qtbot.wait(50)

    for xy in setup_clicks:
        click(xy=xy)

    def enter_label_when_visible() -> None:
        if not win._label_dialog.isVisible():
            QTimer.singleShot(
                50,
                enter_label_when_visible,
            )
            return

        qtbot.keyClicks(
            win._label_dialog.edit,
            label,
        )
        qtbot.wait(50)
        qtbot.keyClick(
            win._label_dialog.edit,
            Qt.Key.Key_Enter,
        )

    QTimer.singleShot(
        0,
        enter_label_when_visible,
    )

    click(
        xy=finalize_click,
        modifier=finalize_modifier,
    )

    shapes = canvas.shapes

    assert len(shapes) >= 1
    assert all(shape.label == label for shape in shapes)
    assert all(shape.shape_type == create_mode for shape in shapes)
    assert all(shape.flags == {} for shape in shapes)
    assert all(shape.mask is None for shape in shapes)
    assert all(shape.group_id is None for shape in shapes)
    assert len(shapes[0].points) == expected_num_points

    win._save_label_file(save_as=False)

    assert_labelfile_sanity(out_file)

    close_or_pause(
        qtbot=qtbot,
        widget=win,
        pause=pause,
    )