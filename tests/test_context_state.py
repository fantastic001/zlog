from zlog.context_state import ContextState
from zlog.context_updates import NumericAddUpdate, ReplaceUpdate


def test_update_reset_clear_and_snapshot() -> None:
    state = ContextState()
    state.update("a", ReplaceUpdate(), "x")
    state.update("n", NumericAddUpdate(10), "2")
    state.update("n", NumericAddUpdate(10), "3")
    snapshot = state.snapshot()

    state.reset({"a", "missing"})

    assert snapshot == {"a": "x", "n": "5"}
    assert state.snapshot() == {"n": "5"}
    state.clear()
    assert state.snapshot() == {}
