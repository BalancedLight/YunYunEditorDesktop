from __future__ import annotations

from dataclasses import dataclass
import copy

from .editor_state import ChartState, EditorState


@dataclass
class HistorySnapshot:
    chart: ChartState
    playhead_tick: int
    selection: set[str]


class HistoryManager:
    def __init__(self, limit: int = 100) -> None:
        self.limit = max(1, int(limit))
        self.undo_stack: list[HistorySnapshot] = []
        self.redo_stack: list[HistorySnapshot] = []

    def clear(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()

    def push(self, state: EditorState) -> None:
        self.undo_stack.append(self.snapshot(state))
        if len(self.undo_stack) > self.limit:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def undo(self, state: EditorState) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot(state))
        self.restore(state, self.undo_stack.pop())
        return True

    def redo(self, state: EditorState) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot(state))
        self.restore(state, self.redo_stack.pop())
        return True

    @staticmethod
    def snapshot(state: EditorState) -> HistorySnapshot:
        return HistorySnapshot(
            chart=copy.deepcopy(state.chart),
            playhead_tick=state.playhead_tick,
            selection=set(state.selection),
        )

    @staticmethod
    def restore(state: EditorState, snapshot: HistorySnapshot) -> None:
        state.chart = copy.deepcopy(snapshot.chart)
        state.playhead_tick = snapshot.playhead_tick
        state.selection = set(snapshot.selection)

