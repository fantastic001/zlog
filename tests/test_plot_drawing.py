import math
from pathlib import Path

import pytest
from matplotlib.colors import to_hex
from matplotlib.figure import Figure

from zlog.errors import SpecError
from zlog.plot_drawing import (
    BarPlotDrawer,
    MatplotlibPlotWriter,
    PlotFileLocator,
    build_plot_file_stem,
)
from zlog.plotting import PlotData, PlotKind, PlotSeries

PNG_SIGNATURE = b"\x89PNG"
PLOTS = {
    PlotKind.BAR: PlotData(
        PlotKind.BAR,
        "",
        "acc",
        (
            PlotSeries("adam", (0.0,), (1.0,), (0.1,), (2,)),
            PlotSeries("sgd", (1.0,), (2.0,), (math.nan,), (1,)),
        ),
    ),
    PlotKind.LINE: PlotData(
        PlotKind.LINE,
        "index",
        "loss",
        (PlotSeries("adam", (0.0, 1.0), (2.0, 1.0), (0.5, 0.0), (2, 1)),),
    ),
    PlotKind.SCATTER: PlotData(
        PlotKind.SCATTER,
        "lr",
        "loss",
        (PlotSeries("adam", (0.1, 0.2), (2.0, 1.0)),),
    ),
}


@pytest.mark.parametrize(
    ("report_name", "stem"),
    [
        ("Loss curve", "Loss_curve"),
        ("../../etc/passwd", "etc_passwd"),
        ("...", "plot"),
        ("a/b:c", "a_b_c"),
    ],
)
def test_plot_file_stem_is_safe(report_name: str, stem: str) -> None:
    assert build_plot_file_stem(report_name) == stem


def test_locator_reserves_unique_paths_and_links_relatively(
    tmp_path: Path,
) -> None:
    locator = PlotFileLocator(tmp_path / "plots", tmp_path, "svg")

    path = locator.reserve("Loss curve")

    assert path == tmp_path / "plots" / "Loss_curve.svg"
    assert locator.link(path) == "plots/Loss_curve.svg"
    with pytest.raises(SpecError, match="would both be written"):
        locator.reserve("Loss/curve")


def test_locator_rejects_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported plot format"):
        PlotFileLocator(tmp_path, tmp_path, "gif")


def test_writer_rejects_invalid_dpi() -> None:
    with pytest.raises(ValueError, match="dpi"):
        MatplotlibPlotWriter(0)


@pytest.mark.parametrize("kind", list(PlotKind))
def test_writer_draws_every_plot_kind(tmp_path: Path, kind: PlotKind) -> None:
    path = tmp_path / "nested" / f"{kind.value}.png"

    MatplotlibPlotWriter(20).write(path, kind.value, PLOTS[kind])

    assert path.read_bytes().startswith(PNG_SIGNATURE)


def test_locator_links_absolutely_across_drives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_different_drives(path: object, start: object) -> str:
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr("os.path.relpath", raise_different_drives)
    locator = PlotFileLocator(tmp_path, tmp_path, "png")

    assert locator.link(tmp_path / "a.png") == (tmp_path / "a.png").as_posix()


def test_bar_drawer_colors_bars_by_category() -> None:
    plot = PlotData(
        PlotKind.BAR,
        "",
        "acc",
        tuple(
            PlotSeries(label, (float(index),), (1.0,), (0.0,), (1,), category)
            for index, (label, category) in enumerate(
                [("a, b, c", "b"), ("a, b, e", "b"), ("a, d, f", "d")]
            )
        ),
        category_label="g2",
    )
    axes = Figure().add_subplot()

    BarPlotDrawer().draw(axes, plot)

    colors = [to_hex(bar.get_facecolor()) for bar in axes.patches]
    assert colors[0] == colors[1] != colors[2]
    legend = axes.get_legend()
    assert legend is not None
    assert legend.get_title().get_text() == "g2"
    assert [text.get_text() for text in legend.get_texts()] == ["b", "d"]


def test_bar_drawer_without_category_has_no_legend() -> None:
    axes = Figure().add_subplot()

    BarPlotDrawer().draw(axes, PLOTS[PlotKind.BAR])

    assert axes.get_legend() is None
