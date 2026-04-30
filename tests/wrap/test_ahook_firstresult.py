"""Tests for AHook with firstresult=True async hooks.

Each test sets up a minimal PluginManager with a firstresult=True hookspec
and a small set of hookimpls, then verifies firstresult semantics via
``pm.ahook``.
"""

import pytest

import apluggy as pluggy
from apluggy import PluginManager

# ---------------------------------------------------------------------------
# Shared markers
# ---------------------------------------------------------------------------

# Project name used throughout; arbitrary but consistent.
_PROJECT = "test_firstresult"

hookspec = pluggy.HookspecMarker(_PROJECT)
hookimpl = pluggy.HookimplMarker(_PROJECT)


# ---------------------------------------------------------------------------
# Hookspec namespace
# ---------------------------------------------------------------------------


class Spec:
    """Hookspec namespace containing firstresult and non-firstresult hooks."""

    @hookspec(firstresult=True)
    async def afunc_first(self, value: int) -> int | None:
        """firstresult=True hook — returns first non-None result."""
        ...  # pragma: no cover

    @hookspec
    async def afunc_all(self, value: int) -> int:
        """firstresult=False (default) hook — returns all results as list."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Test 1: Basic firstresult — two impls, first non-None wins
# ---------------------------------------------------------------------------


async def test_firstresult_basic_first_wins() -> None:
    """With two impls, the first (by execution order) to return non-None wins.

    Pluggy executes impls in reverse registration order, so Plugin_B (registered
    second) runs first. It returns a value, so Plugin_A (registered first) must
    never be called.
    """
    # Track call order to confirm the chain stops after the first non-None result.
    call_log: list[str] = []

    class Plugin_A:
        @hookimpl
        async def afunc_first(self, value: int) -> int:
            call_log.append("A")
            return value * 10  # would return 100 for value=10

    class Plugin_B:
        @hookimpl
        async def afunc_first(self, value: int) -> int:
            call_log.append("B")
            return value * 2  # returns 20 for value=10

    # Build the plugin manager with both plugins registered.
    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_A())
    pm.register(Plugin_B())  # runs first (reverse registration order)

    # Execute the firstresult hook.
    result = await pm.ahook.afunc_first(value=10)

    # Only Plugin_B should have run; it returned 20.
    assert result == 20
    assert call_log == ["B"], f"Expected only ['B'], got {call_log}"


# ---------------------------------------------------------------------------
# Test 2: All impls return None — hook returns None
# ---------------------------------------------------------------------------


async def test_firstresult_all_none() -> None:
    """When every impl returns None, the hook itself returns None."""

    class Plugin_None_1:
        @hookimpl
        async def afunc_first(self, value: int) -> None:
            return None

    class Plugin_None_2:
        @hookimpl
        async def afunc_first(self, value: int) -> None:
            return None

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_None_1())
    pm.register(Plugin_None_2())

    # All None → hook returns None, not a list.
    result = await pm.ahook.afunc_first(value=5)
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: No impls registered — returns None
# ---------------------------------------------------------------------------


async def test_firstresult_no_impls() -> None:
    """With no hookimpls registered, the hook returns None (not a list, not an error)."""
    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    # Intentionally no plugins registered.

    result = await pm.ahook.afunc_first(value=99)
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: Single impl — returns that impl's result
# ---------------------------------------------------------------------------


async def test_firstresult_single_impl() -> None:
    """A single impl that returns a value: hook returns that value directly."""

    class Plugin_One:
        @hookimpl
        async def afunc_first(self, value: int) -> int:
            return value + 1

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_One())

    result = await pm.ahook.afunc_first(value=7)
    assert result == 8


# ---------------------------------------------------------------------------
# Test 5: tryfirst runs before plain impl; tryfirst returns non-None — stops chain
# ---------------------------------------------------------------------------


async def test_firstresult_tryfirst_wins() -> None:
    """tryfirst impl runs before the plain impl.

    When tryfirst returns a non-None value, the plain impl is never called.
    """
    call_log: list[str] = []

    class Plugin_Plain:
        @hookimpl
        async def afunc_first(self, value: int) -> int:
            call_log.append("plain")
            return value * 3  # should never run

    class Plugin_TryFirst:
        @hookimpl(tryfirst=True)
        async def afunc_first(self, value: int) -> int:
            call_log.append("tryfirst")
            return value + 100  # returns 106 for value=6

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_Plain())
    pm.register(Plugin_TryFirst())

    result = await pm.ahook.afunc_first(value=6)

    # tryfirst runs first and wins; plain is never called.
    assert result == 106
    assert call_log == ["tryfirst"], f"Expected only ['tryfirst'], got {call_log}"


# ---------------------------------------------------------------------------
# Test 6: tryfirst returns None — chain continues to next handler (trylast wins)
# ---------------------------------------------------------------------------


async def test_firstresult_tryfirst_none_trylast_wins() -> None:
    """tryfirst returns None so the chain continues; trylast eventually returns a value.

    This verifies that:
    - tryfirst runs before plain impls (and trylast).
    - A None from tryfirst does NOT stop the chain.
    - Execution continues to plain impls, then trylast.
    - The trylast impl's non-None result is returned.
    """
    call_log: list[str] = []

    class Plugin_TryFirst:
        @hookimpl(tryfirst=True)
        async def afunc_first(self, value: int) -> None:
            call_log.append("tryfirst")
            return None  # yields control to the next impl

    class Plugin_Plain:
        @hookimpl
        async def afunc_first(self, value: int) -> None:
            call_log.append("plain")
            return None  # also None; keep going

    class Plugin_TryLast:
        @hookimpl(trylast=True)
        async def afunc_first(self, value: int) -> int:
            call_log.append("trylast")
            return value * 7  # returns 35 for value=5

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_Plain())
    pm.register(Plugin_TryFirst())
    pm.register(Plugin_TryLast())

    result = await pm.ahook.afunc_first(value=5)

    # All three must have run; trylast returned the only non-None value.
    assert result == 35
    assert call_log == ["tryfirst", "plain", "trylast"], (
        f"Expected ['tryfirst', 'plain', 'trylast'], got {call_log}"
    )


# ---------------------------------------------------------------------------
# Test 7: trylast is skipped when plain impl wins
# ---------------------------------------------------------------------------


async def test_firstresult_trylast_skipped_when_plain_wins() -> None:
    """Plain impl returns non-None; trylast impl is never called."""
    call_log: list[str] = []

    # Plain impl returns a non-None value, stopping the chain.
    class Plugin_Plain:
        @hookimpl
        async def afunc_first(self, value: int) -> int:
            call_log.append("plain")
            return value * 2

    # trylast impl should never run because the chain stops before it.
    class Plugin_TryLast:
        @hookimpl(trylast=True)
        async def afunc_first(self, value: int) -> int:
            call_log.append("trylast")
            return value * 99

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_Plain())
    pm.register(Plugin_TryLast())

    result = await pm.ahook.afunc_first(value=5)

    assert result == 10
    assert call_log == ["plain"], f"Expected only ['plain'], got {call_log}"


# ---------------------------------------------------------------------------
# Test 8: Exception propagation — exception from impl reaches caller
# ---------------------------------------------------------------------------


async def test_firstresult_exception_propagates() -> None:
    """An exception raised inside a hookimpl propagates to the caller immediately."""

    class Plugin_Raises:
        @hookimpl
        async def afunc_first(self, value: int) -> int:
            raise ValueError(f"bad value: {value}")

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_Raises())

    # The ValueError from the impl must reach the caller, not be swallowed.
    with pytest.raises(ValueError, match="bad value: 42"):
        await pm.ahook.afunc_first(value=42)


# ---------------------------------------------------------------------------
# Test 9: firstresult=False behavior unchanged — returns list of all results
# ---------------------------------------------------------------------------


async def test_firstresult_false_unaffected() -> None:
    """firstresult=False hooks still return a list of all results.

    Regression guard: the fix must not change the existing gather-based behavior
    for non-firstresult hooks.
    """

    class Plugin_A:
        @hookimpl
        async def afunc_all(self, value: int) -> int:
            return value + 1

    class Plugin_B:
        @hookimpl
        async def afunc_all(self, value: int) -> int:
            return value + 2

    pm = PluginManager(_PROJECT)
    pm.add_hookspecs(Spec)
    pm.register(Plugin_A())
    pm.register(Plugin_B())  # runs first in reverse order

    result = await pm.ahook.afunc_all(value=10)

    # Both results collected; pluggy returns in reverse registration order.
    assert isinstance(result, list)
    assert set(result) == {11, 12}  # order may vary; check contents
    assert len(result) == 2
