import logging
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

import numpy as np
from matplotlib import rcParams
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from zlog.config import SUPPORTED_PLOT_FORMATS
from zlog.errors import SpecError
from zlog.plotting import PlotData, PlotKind, PlotSeries

LOGGER = logging.getLogger(__name__)

UNSAFE_FILE_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
FILE_NAME_REPLACEMENT = "_"
FILE_NAME_TRIMMED_CHARACTERS = "._"
FALLBACK_PLOT_FILE_STEM = "plot"
FIGURE_LAYOUT: Final = "constrained"
BAR_ERROR_CAP_SIZE = 4
BAR_LABEL_ROTATION = 30
BAND_OPACITY = 0.2
SCATTER_MARKER_SIZE = 12
COLOR_CYCLE_PROPERTY: Final = "axes.prop_cycle"


class PlotWriter(Protocol):
    def write(self, path: Path, title: str, plot: PlotData) -> None: ...


class PlotDrawer(Protocol):
    def draw(self, axes: Axes, plot: PlotData) -> None: ...


def build_plot_file_stem(report_name: str) -> str:
    stem = UNSAFE_FILE_NAME_CHARACTERS.sub(FILE_NAME_REPLACEMENT, report_name)
    return stem.strip(FILE_NAME_TRIMMED_CHARACTERS) or FALLBACK_PLOT_FILE_STEM


class PlotFileLocator:
    def __init__(
        self, directory: Path, link_base: Path, plot_format: str
    ) -> None:
        if plot_format in SUPPORTED_PLOT_FORMATS:
            self._directory = directory
            self._link_base = link_base
            self._plot_format = plot_format
            self._reserved: dict[Path, str] = {}
        else:
            raise ValueError(f"unsupported plot format {plot_format!r}")

    def reserve(self, report_name: str) -> Path:
        file_name = f"{build_plot_file_stem(report_name)}.{self._plot_format}"
        path = self._directory / file_name
        if path not in self._reserved:
            self._reserved[path] = report_name
            LOGGER.debug("plot %r goes to %s", report_name, path)
            return path
        else:
            raise SpecError(
                f"plots {self._reserved[path]!r} and {report_name!r} "
                f"would both be written to {path}"
            )

    def link(self, path: Path) -> str:
        try:
            return Path(os.path.relpath(path, self._link_base)).as_posix()
        except ValueError:
            return path.resolve().as_posix()


def assign_category_colors(series: Sequence[PlotSeries]) -> dict[str, str]:
    palette = rcParams[COLOR_CYCLE_PROPERTY].by_key()["color"]
    categories = dict.fromkeys(item.category for item in series)
    return {
        category: palette[index % len(palette)]
        for index, category in enumerate(categories)
    }


def draw_series_legend(axes: Axes, plot: PlotData) -> None:
    if any(series.label for series in plot.series):
        axes.legend()
    else:
        LOGGER.debug("plot has a single unlabelled series, no legend")


class BarPlotDrawer:
    def draw(self, axes: Axes, plot: PlotData) -> None:
        positions = [series.x[0] for series in plot.series]
        colors = assign_category_colors(plot.series)
        axes.bar(
            positions,
            [series.y[0] for series in plot.series],
            yerr=np.nan_to_num([series.spread[0] for series in plot.series]),
            capsize=BAR_ERROR_CAP_SIZE,
            color=[colors[series.category] for series in plot.series],
        )
        axes.set_xticks(
            positions,
            [series.axis_label for series in plot.series],
            rotation=BAR_LABEL_ROTATION,
            ha="right",
        )
        self._draw_category_legend(axes, plot, colors)

    @staticmethod
    def _draw_category_legend(
        axes: Axes, plot: PlotData, colors: Mapping[str, str]
    ) -> None:
        if plot.category_label:
            axes.legend(
                handles=[
                    Patch(color=color, label=category)
                    for category, color in colors.items()
                ],
                title=plot.category_label,
            )
        else:
            LOGGER.debug("bar plot has a single category, no legend")


class LinePlotDrawer:
    def draw(self, axes: Axes, plot: PlotData) -> None:
        for series in plot.series:
            means = np.asarray(series.y)
            spreads = np.asarray(series.spread)
            (line,) = axes.plot(series.x, means, label=series.label)
            axes.fill_between(
                series.x,
                means - spreads,
                means + spreads,
                color=line.get_color(),
                alpha=BAND_OPACITY,
            )
        draw_series_legend(axes, plot)


class ScatterPlotDrawer:
    def draw(self, axes: Axes, plot: PlotData) -> None:
        for series in plot.series:
            axes.scatter(
                series.x, series.y, s=SCATTER_MARKER_SIZE, label=series.label
            )
        draw_series_legend(axes, plot)


BUILTIN_PLOT_DRAWERS: Mapping[PlotKind, PlotDrawer] = MappingProxyType(
    {
        PlotKind.BAR: BarPlotDrawer(),
        PlotKind.LINE: LinePlotDrawer(),
        PlotKind.SCATTER: ScatterPlotDrawer(),
    }
)


class MatplotlibPlotWriter:
    def __init__(
        self,
        dpi: int,
        drawers: Mapping[PlotKind, PlotDrawer] = BUILTIN_PLOT_DRAWERS,
    ) -> None:
        if dpi >= 1:
            self._dpi = dpi
            self._drawers = drawers
        else:
            raise ValueError("dpi must be at least 1")

    def write(self, path: Path, title: str, plot: PlotData) -> None:
        assert plot.series, "plot needs at least one series"
        figure = Figure(layout=FIGURE_LAYOUT)
        axes = figure.add_subplot()
        self._drawers[plot.kind].draw(axes, plot)
        axes.set_title(title)
        axes.set_xlabel(plot.x_label)
        axes.set_ylabel(plot.y_label)
        path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, dpi=self._dpi)
        LOGGER.info("wrote %s plot %r to %s", plot.kind.value, title, path)
