"""Tests for AHook with wrapper=True hookimpls (async middleware chains).

Wrappers are sync generators decorated with ``@hookimpl(wrapper=True)``.
Non-wrappers are async def functions. The dispatch layer handles awaiting
non-wrappers and driving the sync generator teardown loop.

These tests are expected to FAIL until ``_async_multicall`` is implemented
and ``AHook.__getattr__`` is updated to route through it when wrappers are
present.
"""

import pytest

import apluggy as pluggy
from apluggy import PluginManager

# ---------------------------------------------------------------------------
# Shared markers
# ---------------------------------------------------------------------------

_PROJECT = "test_ahook_wrapper"

hookspec = pluggy.HookspecMarker(_PROJECT)
hookimpl = pluggy.HookimplMarker(_PROJECT)


# ---------------------------------------------------------------------------
# Hookspec namespace
# ---------------------------------------------------------------------------


class Spec:
    """Hookspec namespace for wrapper tests."""

    @hookspec
    async def ahook(self, value: int) -> int:
        """firstresult=False hook — wrapper tests use this by default."""
        ...  # pragma: no cover

    @hookspec(firstresult=True)
    async def ahook_first(self, value: int) -> int | None:
        """firstresult=True hook — for firstresult interaction tests."""
        ...  # pragma: no cover


# ===========================================================================
# Basic wrapper semantics (4 tests)
# ===========================================================================


async def test_wrapper_basic_pre_post_order() -> None:
    """Single sync wrapper around single async non-wrapper; verify pre/post order.

    The call_log should show: wrapper_pre → non_wrapper → wrapper_post.
    """
    call_log: list[str] = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            call_log.append("non_wrapper")
            return value * 2

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            call_log.append("wrapper_pre")
            result = yield
            call_log.append("wrapper_post")
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook(value=5)

    assert call_log == ["wrapper_pre", "non_wrapper", "wrapper_post"], (
        f"Expected pre→non_wrapper→post order, got {call_log}"
    )
    # firstresult=False with one non-wrapper: result is a list containing [10]
    assert result == [10]


async def test_wrapper_modifies_result() -> None:
    """Wrapper modifies the result returned to the caller."""

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            return value + 1  # returns 6 for value=5

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            result = yield
            # result is [6] (firstresult=False, one non-wrapper)
            # return a modified list
            return [x * 10 for x in result]

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook(value=5)

    assert result == [60], f"Expected [60], got {result}"


async def test_wrapper_passes_through() -> None:
    """Wrapper that returns result unchanged passes through the inner value."""

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            return value * 3  # returns 15 for value=5

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            result = yield
            return result  # pass through unchanged

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook(value=5)

    # firstresult=False with one non-wrapper: [15] passed through unchanged
    assert result == [15], f"Expected [15], got {result}"


async def test_wrapper_no_non_wrappers() -> None:
    """Wrapper with no non-wrappers receives an empty list (firstresult=False)."""
    received: list = []

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            result = yield
            received.append(result)
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook(value=1)

    # No non-wrappers: aggregate is empty list for firstresult=False
    assert received == [[]], f"Wrapper should receive [], got {received}"
    assert result == [], f"Expected [], got {result}"


# ===========================================================================
# Multiple wrappers (2 tests)
# ===========================================================================


async def test_two_wrappers_nesting_order() -> None:
    """Two wrappers; verify nesting: outer_pre → inner_pre → non_wrapper → inner_post → outer_post.

    Pluggy execution order (reversed hookimpls): tryfirst_wrappers first, then
    plain wrappers. We register outer wrapper with tryfirst=True so it runs
    outermost.
    """
    call_log: list[str] = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            call_log.append("non_wrapper")
            return value

    class Plugin_InnerWrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            call_log.append("inner_pre")
            result = yield
            call_log.append("inner_post")
            return result

    class Plugin_OuterWrapper:
        @hookimpl(wrapper=True, tryfirst=True)
        def ahook(self, value: int):
            call_log.append("outer_pre")
            result = yield
            call_log.append("outer_post")
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_InnerWrapper())
    pm.register(Plugin_OuterWrapper())

    await pm.ahook.ahook(value=1)

    assert call_log == [
        "outer_pre",
        "inner_pre",
        "non_wrapper",
        "inner_post",
        "outer_post",
    ], f"Wrong nesting order: {call_log}"


async def test_inner_wrapper_modifies_outer_sees_it() -> None:
    """Inner wrapper modifies result; outer wrapper receives the modified value."""
    received_by_outer: list = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            return value  # returns [5] as list

    class Plugin_InnerWrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            result = yield
            # result is [5]; multiply each element by 10
            return [x * 10 for x in result]

    class Plugin_OuterWrapper:
        @hookimpl(wrapper=True, tryfirst=True)
        def ahook(self, value: int):
            result = yield
            received_by_outer.append(result)
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_InnerWrapper())
    pm.register(Plugin_OuterWrapper())

    result = await pm.ahook.ahook(value=5)

    # Inner modified [5] → [50]; outer sees [50] and passes through
    assert received_by_outer == [[50]], (
        f"Outer should receive [50] from inner, got {received_by_outer}"
    )
    assert result == [50], f"Expected [50], got {result}"


# ===========================================================================
# Ordering (3 tests)
# ===========================================================================


async def test_tryfirst_wrapper_runs_before_default_wrapper() -> None:
    """tryfirst wrapper's pre-yield runs before the default wrapper's pre-yield.

    pluggy ordering: tryfirst_wrappers run outermost (their pre-yield executes
    first; their post-yield executes last).
    """
    call_log: list[str] = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            call_log.append("non_wrapper")
            return value

    class Plugin_DefaultWrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            call_log.append("default_pre")
            result = yield
            call_log.append("default_post")
            return result

    class Plugin_TryFirstWrapper:
        @hookimpl(wrapper=True, tryfirst=True)
        def ahook(self, value: int):
            call_log.append("tryfirst_pre")
            result = yield
            call_log.append("tryfirst_post")
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_DefaultWrapper())
    pm.register(Plugin_TryFirstWrapper())

    await pm.ahook.ahook(value=1)

    # tryfirst is outermost: tryfirst_pre first, tryfirst_post last
    assert call_log == [
        "tryfirst_pre",
        "default_pre",
        "non_wrapper",
        "default_post",
        "tryfirst_post",
    ], f"Wrong ordering with tryfirst wrapper: {call_log}"


async def test_trylast_wrapper_runs_after_default_wrapper() -> None:
    """trylast wrapper's pre-yield runs after the default wrapper's pre-yield.

    pluggy ordering: trylast_wrappers run innermost (their pre-yield executes
    last among wrappers; their post-yield executes first among wrappers).
    """
    call_log: list[str] = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            call_log.append("non_wrapper")
            return value

    class Plugin_DefaultWrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            call_log.append("default_pre")
            result = yield
            call_log.append("default_post")
            return result

    class Plugin_TryLastWrapper:
        @hookimpl(wrapper=True, trylast=True)
        def ahook(self, value: int):
            call_log.append("trylast_pre")
            result = yield
            call_log.append("trylast_post")
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_DefaultWrapper())
    pm.register(Plugin_TryLastWrapper())

    await pm.ahook.ahook(value=1)

    # trylast wrapper is innermost among wrappers
    assert call_log == [
        "default_pre",
        "trylast_pre",
        "non_wrapper",
        "trylast_post",
        "default_post",
    ], f"Wrong ordering with trylast wrapper: {call_log}"


async def test_tryfirst_trylast_on_non_wrappers_inside_wrapper_chain() -> None:
    """tryfirst/trylast on non-wrappers control their execution order within the chain.

    Inside the wrapper layer, non-wrappers execute as:
    tryfirst_nonwrappers → plain_nonwrappers → trylast_nonwrappers
    (pluggy reversed order applied to non-wrapper segment).
    """
    call_log: list[str] = []

    class Plugin_PlainNonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            call_log.append("plain")
            return value

    class Plugin_TryFirstNonWrapper:
        @hookimpl(tryfirst=True)
        async def ahook(self, value: int) -> int:
            call_log.append("tryfirst_nonwrapper")
            return value + 1

    class Plugin_TryLastNonWrapper:
        @hookimpl(trylast=True)
        async def ahook(self, value: int) -> int:
            call_log.append("trylast_nonwrapper")
            return value + 2

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            result = yield
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_PlainNonWrapper())
    pm.register(Plugin_TryFirstNonWrapper())
    pm.register(Plugin_TryLastNonWrapper())
    pm.register(Plugin_Wrapper())

    await pm.ahook.ahook(value=1)

    # Non-wrapper execution order: tryfirst → plain → trylast
    assert call_log == ["tryfirst_nonwrapper", "plain", "trylast_nonwrapper"], (
        f"Wrong non-wrapper execution order: {call_log}"
    )


# ===========================================================================
# firstresult interaction (2 tests)
# ===========================================================================


async def test_wrapper_around_firstresult_receives_single_value() -> None:
    """Wrapper around firstresult=True hook receives a single value, not a list."""
    received: list = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook_first(self, value: int) -> int:
            return value * 2  # returns 10 for value=5

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook_first(self, value: int):
            result = yield
            received.append(result)
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook_first(value=5)

    # firstresult=True: wrapper sees single value (10), not [10]
    assert received == [10], (
        f"Wrapper should receive single int 10, not a list; got {received}"
    )
    assert result == 10, f"Expected 10, got {result}"


async def test_wrapper_modifies_firstresult_value() -> None:
    """Wrapper can modify the firstresult value before returning it to caller."""

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook_first(self, value: int) -> int:
            return value + 1  # returns 6 for value=5

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook_first(self, value: int):
            result = yield
            # result is 6 (single int for firstresult=True)
            return result * 10  # return 60

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook_first(value=5)

    assert result == 60, f"Expected 60, got {result}"


# ===========================================================================
# Error handling (4 tests)
# ===========================================================================


async def test_error_non_wrapper_raises_exception_thrown_into_wrapper() -> None:
    """Non-wrapper raises an exception; it is thrown into the wrapper at yield point."""
    saw_exception: list[Exception] = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            raise ValueError(f"bad value: {value}")

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            try:
                result = yield
            except ValueError as exc:
                saw_exception.append(exc)
                return []  # recovery: return empty list
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    # Wrapper catches the exception; caller sees recovery value
    result = await pm.ahook.ahook(value=42)

    assert len(saw_exception) == 1
    assert "bad value: 42" in str(saw_exception[0])
    assert result == [], f"Expected recovery value [], got {result}"


async def test_error_wrapper_catches_exception_returns_recovery() -> None:
    """Wrapper catches the exception thrown into it and returns a recovery value."""

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            raise RuntimeError("inner failure")

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            try:
                result = yield
            except RuntimeError:
                return [-1]  # recovery value
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    result = await pm.ahook.ahook(value=1)

    assert result == [-1], f"Expected recovery value [-1], got {result}"


async def test_error_wrapper_reraises_exception_propagates_to_caller() -> None:
    """Wrapper re-raises the exception; it propagates to the caller."""

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            raise ValueError("propagate me")

    class Plugin_Wrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            try:
                result = yield
            except ValueError:
                raise  # re-raise; caller must see it
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_Wrapper())

    with pytest.raises(ValueError, match="propagate me"):
        await pm.ahook.ahook(value=1)


async def test_error_exception_in_wrapper_pre_yield_triggers_outer_teardown() -> None:
    """Exception during wrapper pre-yield code causes already-pushed wrappers to be torn down.

    Setup: outer wrapper is registered (tryfirst) → inner wrapper raises before yield.
    Outer wrapper's teardown (post-yield) must still run so it can clean up.
    """
    teardown_log: list[str] = []

    class Plugin_NonWrapper:
        @hookimpl
        async def ahook(self, value: int) -> int:
            return value

    class Plugin_InnerWrapper:
        @hookimpl(wrapper=True)
        def ahook(self, value: int):
            raise RuntimeError("pre-yield failure")
            yield  # never reached — makes this a generator

    class Plugin_OuterWrapper:
        @hookimpl(wrapper=True, tryfirst=True)
        def ahook(self, value: int):
            try:
                result = yield
            except RuntimeError:
                teardown_log.append("outer_caught")
                raise  # re-raise so it propagates
            return result

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_NonWrapper())
    pm.register(Plugin_InnerWrapper())
    pm.register(Plugin_OuterWrapper())

    # The RuntimeError from InnerWrapper's pre-yield should reach outer wrapper,
    # then propagate to the caller.
    with pytest.raises(RuntimeError, match="pre-yield failure"):
        await pm.ahook.ahook(value=1)

    # Outer wrapper teardown must have run
    assert teardown_log == ["outer_caught"], (
        f"Outer wrapper teardown should have run, got {teardown_log}"
    )


# ===========================================================================
# Regression guards (2 tests)
# ===========================================================================


async def test_regression_no_wrappers_firstresult_false_returns_list() -> None:
    """No wrappers + firstresult=False → returns list via gather path (unchanged behavior)."""

    class Plugin_A:
        @hookimpl
        async def ahook(self, value: int) -> int:
            return value + 1

    class Plugin_B:
        @hookimpl
        async def ahook(self, value: int) -> int:
            return value + 2

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_A())
    pm.register(Plugin_B())

    result = await pm.ahook.ahook(value=10)

    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert set(result) == {11, 12}, f"Expected {{11, 12}}, got {set(result)}"
    assert len(result) == 2


async def test_regression_no_wrappers_firstresult_true_returns_single_value() -> None:
    """No wrappers + firstresult=True → returns single value via firstresult path (unchanged)."""

    class Plugin_A:
        @hookimpl
        async def ahook_first(self, value: int) -> int:
            return value * 10  # would return 50

    class Plugin_B:
        @hookimpl
        async def ahook_first(self, value: int) -> int:
            return value * 2  # returns 10 — runs first (registered last)

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_A())
    pm.register(Plugin_B())  # runs first in reverse registration order

    result = await pm.ahook.ahook_first(value=5)

    # Plugin_B runs first and returns 10; chain stops.
    assert result == 10, f"Expected 10 (firstresult from Plugin_B), got {result}"
