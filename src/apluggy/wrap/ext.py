import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Coroutine

from pluggy import HookCaller
from pluggy import PluginManager as PluginManager_

from apluggy.stack import AGenCtxMngr, GenCtxMngr, async_stack_gen_ctxs, stack_gen_ctxs

if TYPE_CHECKING:
    from pluggy._hooks import HookImpl


async def _call_firstresult(
    hook: HookCaller,
    caller_kwargs: dict[str, Any],
) -> Any:
    """Await hookimpls in pluggy order, returning the first non-None result.

    Pluggy's _multicall returns a single coroutine for firstresult=True hooks,
    which is not iterable and cannot be passed to asyncio.gather. This function
    bypasses _multicall entirely and drives dispatch manually.
    """
    # Retrieve implementations in pluggy's storage order, then iterate in
    # reverse to match pluggy's _multicall execution order:
    # tryfirst first, then plain impls in registration order, trylast last.
    hookimpls: list[HookImpl] = hook.get_hookimpls()

    for hook_impl in reversed(hookimpls):
        # Build kwargs from argnames only, matching pluggy's _multicall behavior.
        # kwargnames is intentionally excluded — pluggy does not pass keyword-only
        # parameters through hook dispatch.
        impl_kwargs = {k: caller_kwargs[k] for k in hook_impl.argnames}

        # Invoke the hookimpl function to get a coroutine, then await it.
        result = await hook_impl.function(**impl_kwargs)

        # First non-None result stops the chain (firstresult semantics).
        if result is not None:
            return result

    # All implementations returned None; return None to the caller.
    return None


async def _async_multicall(
    hook_name: str,
    hookimpls: list["HookImpl"],
    caller_kwargs: dict[str, Any],
    firstresult: bool,
) -> Any:
    """Drive async hook dispatch for hooks that include wrapper=True hookimpls.

    Mirrors pluggy's _multicall (_callers.py:76-169) but handles async
    non-wrappers and sync generator wrappers. Wrappers are set up first
    (pre-yield code runs during setup), then non-wrappers are awaited, then
    wrappers are torn down in reverse order (post-yield code runs, result or
    exception is passed back via send/throw).

    Wrappers must be sync generators — they cannot perform async I/O. The
    async I/O happens in non-wrapper hookimpls, which this function awaits.

    Args:
        hook_name: Name of the hook, used in error messages.
        hookimpls: All hookimpls for this hook, in pluggy storage order.
                   This function iterates them in reverse (execution order).
        caller_kwargs: Keyword arguments passed by the caller.
        firstresult: If True, stop after the first non-None result from
                     non-wrappers; aggregate is a single value. If False,
                     collect all results into a list.
    """
    # teardowns holds sync generators for each wrapper hookimpl, in the order
    # they were set up (outermost first). Teardown iterates this in reverse so
    # innermost teardown runs first.
    teardowns: list[Any] = []

    # results accumulates return values from non-wrapper hookimpls.
    results: list[Any] = []

    # exception captures any exception raised during setup or invocation, so
    # teardown wrappers can receive it via throw().
    exception: BaseException | None = None

    try:
        # -----------------------------------------------------------------------
        # Setup phase: iterate hookimpls in pluggy execution order (reversed).
        # Wrappers run their pre-yield code; non-wrappers are awaited.
        # -----------------------------------------------------------------------
        for hook_impl in reversed(hookimpls):
            # Build kwargs by selecting only the args this hookimpl declares.
            # pluggy strips 'self' from argnames, so we never need to pass it.
            impl_kwargs = {k: caller_kwargs[k] for k in hook_impl.argnames}

            if hook_impl.hookwrapper:
                # Old-style hookwrapper=True is not supported in this dispatch path.
                raise NotImplementedError(
                    f"{hook_name}: hookwrapper=True hookimpls are not supported "
                    "by _async_multicall; use wrapper=True instead"
                )

            if hook_impl.wrapper:
                # Wrapper hookimpl: call function to get a sync generator,
                # then advance to its first yield (running pre-yield code).
                gen = hook_impl.function(**impl_kwargs)

                try:
                    # Advance the generator to its yield point.
                    # If it raises StopIteration, it never yielded — programming error.
                    next(gen)
                except StopIteration:
                    raise RuntimeError(
                        f"{hook_name}: wrapper {hook_impl.function!r} did not yield"
                    )

                # Push the generator onto the teardown stack for post-yield processing.
                teardowns.append(gen)

            else:
                # Regular (non-wrapper) hookimpl: await its coroutine and collect the result.
                result = await hook_impl.function(**impl_kwargs)
                results.append(result)

                # firstresult semantics: stop after the first non-None result.
                if firstresult and result is not None:
                    break

    except BaseException as e:
        # Any exception during setup or invocation (from a wrapper's pre-yield
        # code or from a non-wrapper) is captured here. Teardown will throw it
        # into any already-pushed wrappers.
        exception = e

    # -----------------------------------------------------------------------
    # Compute aggregate result from non-wrapper invocations.
    # -----------------------------------------------------------------------
    if firstresult:
        # Return the single first non-None result, or None if all returned None.
        aggregate: Any = next((r for r in results if r is not None), None)
    else:
        # Return all collected results as a list.
        aggregate = results

    # -----------------------------------------------------------------------
    # Teardown phase: drive wrappers in reverse setup order (innermost first).
    # Send the aggregate result (or throw any exception) into each wrapper's
    # generator to run its post-yield code.
    # -----------------------------------------------------------------------
    for gen in reversed(teardowns):
        try:
            if exception is not None:
                # An exception is in flight — throw it into the wrapper generator.
                # The wrapper can catch it, recover, and return a new result, or
                # re-raise (or raise a new exception), which replaces 'exception'.
                try:
                    gen.throw(exception)
                except RuntimeError as re:
                    # Python 3.7+: if the thrown exception was a StopIteration,
                    # Python wraps it in RuntimeError inside the generator body.
                    # Match pluggy's handling at _callers.py:140-148.
                    if isinstance(exception, StopIteration) and re.__cause__ is exception:
                        # Close the generator cleanly and continue to the next wrapper.
                        gen.close()
                        continue
                    else:
                        # A genuine RuntimeError from the wrapper — let it replace
                        # the current exception in the outer except BaseException block.
                        raise
            else:
                # No exception: send the current aggregate result into the wrapper.
                gen.send(aggregate)

            # If we reach here without an exception, the generator yielded again,
            # which is illegal (wrappers must yield exactly once).
            gen.close()
            raise RuntimeError(f"{hook_name}: wrapper yielded twice")

        except StopIteration as si:
            # Normal success path: the wrapper returned a value via 'return'.
            # Capture the returned value as the new aggregate result.
            aggregate = si.value
            exception = None  # wrapper handled any in-flight exception

        except BaseException as e:
            # Wrapper raised during teardown (re-raised or raised a new exception).
            # This replaces the current exception; continue teardown to the next wrapper.
            exception = e
            continue

    # -----------------------------------------------------------------------
    # Final result: raise any surviving exception, or return the aggregate.
    # -----------------------------------------------------------------------
    if exception is not None:
        raise exception

    return aggregate


class AHook:
    def __init__(self, pm: PluginManager_) -> None:
        self.pm = pm

    def __getattr__(self, name: str) -> Callable[..., Coroutine[Any, Any, Any]]:
        async def call(*args: Any, **kwargs: Any) -> Any:
            # Resolve the named HookCaller from pluggy's hook namespace.
            hook: HookCaller = getattr(self.pm.hook, name)

            # Check whether this hookspec uses firstresult semantics.
            # A missing spec means no hookspec was registered; treat as False.
            firstresult: bool = bool(
                hook.spec and hook.spec.opts.get("firstresult", False)
            )

            # Check whether any hookimpl is a wrapper (wrapper=True or hookwrapper=True).
            # When wrappers are present, we must use _async_multicall to drive the
            # sync generator teardown protocol.
            hookimpls = hook.get_hookimpls()
            has_wrappers = any(hi.wrapper or hi.hookwrapper for hi in hookimpls)

            if has_wrappers:
                # Wrapper path: drive setup, invocation, and teardown manually.
                # Handles both firstresult=True and firstresult=False.
                return await _async_multicall(name, hookimpls, kwargs, firstresult)
            elif firstresult:
                # firstresult=True, no wrappers: bypass _multicall; iterate impls
                # sequentially. _multicall returns a single coroutine for these
                # hooks, which is not iterable and would crash asyncio.gather.
                # Positional args are intentionally not forwarded here — pluggy
                # hookspecs use keyword arguments exclusively.
                return await _call_firstresult(hook, kwargs)
            else:
                # firstresult=False, no wrappers: collect unawaited coroutines from
                # pluggy's _multicall and run them concurrently.
                coros: list[asyncio.Future] = hook(*args, **kwargs)
                return await asyncio.gather(*coros)

        return call


class With:
    def __init__(self, pm: PluginManager_, reverse: bool = False) -> None:
        self.pm = pm
        self.reverse = reverse

    def __getattr__(self, name: str) -> Callable[..., GenCtxMngr[list]]:
        hook: HookCaller = getattr(self.pm.hook, name)

        def call(*args: Any, **kwargs: Any) -> GenCtxMngr[list]:
            ctxs = hook(*args, **kwargs)
            if self.reverse:
                ctxs = list(reversed(ctxs))
            return stack_gen_ctxs(ctxs)

        return call


class AWith:
    def __init__(self, pm: PluginManager_, reverse: bool = False) -> None:
        self.pm = pm
        self.reverse = reverse

    def __getattr__(self, name: str) -> Callable[..., AGenCtxMngr]:
        hook: HookCaller = getattr(self.pm.hook, name)

        def call(*args: Any, **kwargs: Any) -> AGenCtxMngr[list]:
            ctxs = hook(*args, **kwargs)
            if self.reverse:
                ctxs = list(reversed(ctxs))
            return async_stack_gen_ctxs(ctxs)

        return call
