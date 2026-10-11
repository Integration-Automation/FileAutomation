"""Pipeline canvas: tasks as nodes that can be dragged, dependencies as arrows between them.

The canvas is a view over a :class:`~automation_file.app.PipelineDraft` and
keeps no state of its own beyond the selection: every node and every arrow is
rebuilt from the draft when the draft says it changed, and dragging a node
writes its position back with ``draft.set_position``.

Two tasks are connected by selecting them one after the other; the order of the
selection is the direction of the arrow, and :meth:`PipelineCanvas.selected_tasks`
returns the tasks in that order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QListWidget,
    QListWidgetItem,
)

from automation_file.app import PipelineDraft
from automation_file.app.pipeline_draft import CHANGE_HEADER, CHANGE_POSITION

ACTION_MIME = "application/x-automation-file-action"
NODE_WIDTH = 190.0
NODE_HEIGHT = 62.0

_CORNER = 8.0
_PADDING = 8.0
_ARROW_LENGTH = 11.0
_ARROW_HALF_WIDTH = 5.0
_MIN_BEND = 40.0
_EDGE_HIT_WIDTH = 12.0
_NO_ACTION = "(no action)"
_NODE_FILL = "#f4f6f8"
_NODE_BORDER = "#5f6b7a"
_SELECTED = "#1a73e8"
_TEXT = "#1d1f21"
_MUTED_TEXT = "#5f6b7a"
_EDGE = "#5f6b7a"
#: Task status -> the colour of its node while a run is followed.
STATUS_COLOURS: dict[str, str] = {
    "pending": "#eceff1",
    "planned": "#e3f2fd",
    "running": "#bbdefb",
    "succeeded": "#c8e6c9",
    "failed": "#ffcdd2",
    "timeout": "#ffcdd2",
    "cancelled": "#ffe0b2",
    "skipped": "#fff9c4",
}

MoveHandler = Callable[[str, float, float], None]


class TaskNode(QGraphicsRectItem):
    """One task on the canvas: its ID, its action and, during a run, its status."""

    def __init__(self, task_id: str, action: str, on_moved: MoveHandler) -> None:
        super().__init__(0.0, 0.0, NODE_WIDTH, NODE_HEIGHT)
        self.task_id = task_id
        self.action = action
        self.status = ""
        self._on_moved = on_moved
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1.0)
        self.setToolTip(f"{task_id}\n{action or _NO_ACTION}")

    def output_point(self) -> QPointF:
        """Where an arrow leaves the node: the middle of its right side."""
        return self.pos() + QPointF(NODE_WIDTH, NODE_HEIGHT / 2)

    def input_point(self) -> QPointF:
        """Where an arrow reaches the node: the middle of its left side."""
        return self.pos() + QPointF(0.0, NODE_HEIGHT / 2)

    def itemChange(self, change: Any, value: Any) -> Any:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._on_moved(self.task_id, self.pos().x(), self.pos().y())
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, _option: Any, _widget: Any = None) -> None:
        selected = self.isSelected()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(QColor(_SELECTED if selected else _NODE_BORDER), 2.5 if selected else 1.2)
        )
        painter.setBrush(QBrush(QColor(STATUS_COLOURS.get(self.status, _NODE_FILL))))
        painter.drawRoundedRect(self.rect(), _CORNER, _CORNER)
        half = NODE_HEIGHT / 2
        text_width = NODE_WIDTH - 2 * _PADDING
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(_TEXT))
        metrics = painter.fontMetrics()
        painter.drawText(
            QRectF(_PADDING, 4.0, text_width, half - 4.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(self.task_id, Qt.TextElideMode.ElideRight, int(text_width)),
        )
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(_MUTED_TEXT))
        caption = self.action or _NO_ACTION
        if self.status:
            caption = f"{caption}  [{self.status}]"
        painter.drawText(
            QRectF(_PADDING, half, text_width, half - 4.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            painter.fontMetrics().elidedText(
                caption, Qt.TextElideMode.ElideMiddle, int(text_width)
            ),
        )


class EdgeItem(QGraphicsPathItem):
    """A dependency: an arrow from the upstream task to the task that depends on it."""

    def __init__(self, upstream: TaskNode, downstream: TaskNode) -> None:
        super().__init__()
        self.upstream_id = upstream.task_id
        self.downstream_id = downstream.task_id
        self._upstream = upstream
        self._downstream = downstream
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(0.0)
        self.setPen(QPen(QColor(_EDGE), 1.6))
        self.setToolTip(f"{self.downstream_id} depends on {self.upstream_id}")
        self.refresh()

    def refresh(self) -> None:
        """Redraw the arrow between the current positions of its two nodes."""
        start, end = self._upstream.output_point(), self._downstream.input_point()
        bend = max(abs(end.x() - start.x()) / 2, _MIN_BEND)
        path = QPainterPath(start)
        path.cubicTo(start + QPointF(bend, 0.0), end - QPointF(bend, 0.0), end)
        path.moveTo(end)
        path.lineTo(end + QPointF(-_ARROW_LENGTH, -_ARROW_HALF_WIDTH))
        path.moveTo(end)
        path.lineTo(end + QPointF(-_ARROW_LENGTH, _ARROW_HALF_WIDTH))
        self.setPath(path)

    def shape(self) -> QPainterPath:
        """Make the thin curve easy to click: a band around it counts as the arrow."""
        stroker = QPainterPathStroker()
        stroker.setWidth(_EDGE_HIT_WIDTH)
        return stroker.createStroke(self.path())

    def itemChange(self, change: Any, value: Any) -> Any:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.setPen(QPen(QColor(_SELECTED if value else _EDGE), 2.6 if value else 1.6))
        return super().itemChange(change, value)


class ActionPalette(QListWidget):
    """The registered actions; an entry can be dragged onto the canvas to add a task."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def set_actions(self, names: list[str]) -> None:
        """Replace the entries."""
        self.clear()
        self.addItems(names)

    def filter_actions(self, text: str) -> None:
        """Show only the entries that contain ``text``, whatever its case."""
        wanted = text.strip().casefold()
        for row in range(self.count()):
            entry = self.item(row)
            entry.setHidden(bool(wanted) and wanted not in entry.text().casefold())

    def selected_action(self) -> str:
        """Return the selected action name, or an empty text."""
        entry = self.currentItem()
        return "" if entry is None or entry.isHidden() else entry.text()

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        data = QMimeData()
        if items:
            data.setData(ACTION_MIME, items[0].text().encode("utf-8"))
            data.setText(items[0].text())
        return data


class PipelineCanvas(QGraphicsView):
    """Shows a draft as a graph and lets the user arrange and select its tasks."""

    #: The selected task IDs, in the order they were selected.
    selection_changed = Signal(list)
    #: An action name dropped from the palette, and where: ``(name, x, y)`` in scene coordinates.
    action_dropped = Signal(str, float, float)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setAcceptDrops(True)
        self._draft: PipelineDraft | None = None
        self._nodes: dict[str, TaskNode] = {}
        self._edges: list[EdgeItem] = []
        self._order: list[str] = []
        self._statuses: dict[str, str] = {}
        self._syncing = False
        self._scene.selectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------ the draft

    def set_draft(self, draft: PipelineDraft | None) -> None:
        """Show ``draft`` from now on and follow its changes."""
        if self._draft is not None:
            self._draft.remove_listener(self._on_draft_changed)
        self._draft = draft
        self._statuses = {}
        self._order = []
        if draft is not None:
            draft.add_listener(self._on_draft_changed)
        self.sync()

    def sync(self) -> None:
        """Rebuild every node and every arrow from the draft, keeping the selection."""
        keep = list(self._order)
        self._syncing = True
        try:
            self._scene.clear()
            self._nodes, self._edges = {}, []
            self._build()
            self._order = [task_id for task_id in keep if task_id in self._nodes]
            for task_id in self._order:
                self._nodes[task_id].setSelected(True)
        finally:
            self._syncing = False
        self.selection_changed.emit(list(self._order))

    def _build(self) -> None:
        if self._draft is None:
            return
        for task in self._draft.tasks:
            node = TaskNode(task.task_id, task.action, self._node_moved)
            node.status = self._statuses.get(task.task_id, "")
            node.setPos(task.x, task.y)
            self._scene.addItem(node)
            self._nodes[task.task_id] = node
        for upstream, downstream in self._draft.edges():
            edge = EdgeItem(self._nodes[upstream], self._nodes[downstream])
            self._scene.addItem(edge)
            self._edges.append(edge)

    def _on_draft_changed(self, change: str) -> None:
        if change == CHANGE_POSITION:
            self._place_nodes()
        elif change != CHANGE_HEADER:
            self.sync()

    def _place_nodes(self) -> None:
        """Move the nodes to where the draft says they are (after an automatic layout)."""
        if self._draft is None or self._syncing:
            return
        self._syncing = True
        try:
            for task_id, (x, y) in self._draft.positions().items():
                node = self._nodes.get(task_id)
                if node is not None and (node.pos().x(), node.pos().y()) != (x, y):
                    node.setPos(x, y)
            for edge in self._edges:
                edge.refresh()
        finally:
            self._syncing = False

    def _node_moved(self, task_id: str, x: float, y: float) -> None:
        if self._syncing or self._draft is None:
            return
        self._syncing = True
        try:
            self._draft.set_position(task_id, x, y)
        finally:
            self._syncing = False
        for edge in self._edges:
            if task_id in (edge.upstream_id, edge.downstream_id):
                edge.refresh()

    # ------------------------------------------------------------------ what it shows

    def node(self, task_id: str) -> TaskNode | None:
        """Return the node of the task ``task_id``, or ``None``."""
        return self._nodes.get(task_id)

    def node_ids(self) -> list[str]:
        """Return the IDs of the tasks on the canvas, in the draft's order."""
        return list(self._nodes)

    def edge_pairs(self) -> list[tuple[str, str]]:
        """Return ``(upstream, downstream)`` for every arrow on the canvas."""
        return [(edge.upstream_id, edge.downstream_id) for edge in self._edges]

    def set_statuses(self, statuses: dict[str, str]) -> None:
        """Colour the nodes by task status; an empty mapping clears the colours."""
        self._statuses = dict(statuses)
        for task_id, node in self._nodes.items():
            node.status = self._statuses.get(task_id, "")
            node.update()

    # ------------------------------------------------------------------ selection

    def selected_tasks(self) -> list[str]:
        """Return the selected task IDs, in the order they were selected."""
        return list(self._order)

    def selected_edges(self) -> list[tuple[str, str]]:
        """Return ``(upstream, downstream)`` for every selected arrow."""
        return [
            (item.upstream_id, item.downstream_id)
            for item in self._scene.selectedItems()
            if isinstance(item, EdgeItem)
        ]

    def select_tasks(self, task_ids: list[str]) -> None:
        """Select exactly ``task_ids``, in that order, and report the selection once."""
        chosen = [task_id for task_id in dict.fromkeys(task_ids) if task_id in self._nodes]
        self._syncing = True
        try:
            self._scene.clearSelection()
            for task_id in chosen:
                self._nodes[task_id].setSelected(True)
        finally:
            self._syncing = False
        self._order = chosen
        self.selection_changed.emit(list(chosen))

    def select_edge(self, upstream: str, downstream: str) -> bool:
        """Select the arrow from ``upstream`` to ``downstream``; return whether there is one."""
        for edge in self._edges:
            if (edge.upstream_id, edge.downstream_id) == (upstream, downstream):
                self._scene.clearSelection()
                edge.setSelected(True)
                return True
        return False

    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        current = [
            item.task_id for item in self._scene.selectedItems() if isinstance(item, TaskNode)
        ]
        kept = [task_id for task_id in self._order if task_id in current]
        self._order = kept + [task_id for task_id in current if task_id not in kept]
        self.selection_changed.emit(list(self._order))

    # ------------------------------------------------------------------ drop from the palette

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if event.mimeData().hasFormat(ACTION_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if event.mimeData().hasFormat(ACTION_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: Any) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        data = event.mimeData()
        if not data.hasFormat(ACTION_MIME):
            super().dropEvent(event)
            return
        action = bytes(data.data(ACTION_MIME).data()).decode("utf-8")
        point = self.mapToScene(event.position().toPoint())
        event.acceptProposedAction()
        self.action_dropped.emit(action, point.x(), point.y())
