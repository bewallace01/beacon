"""Iterator wrappers that observe streamed LLM responses without changing
what the user sees. Each chunk is forwarded as-is; `on_chunk` is invoked for
side-effect bookkeeping and `on_finish` is invoked exactly once when the
stream is exhausted, closed, or its context manager exits.

Exceptions inside `on_chunk` and `on_finish` are swallowed to honor Lightsei's
graceful-degradation rule.
"""

from typing import Any, Awaitable, Callable, Iterator


class _SyncStreamTap:
    def __init__(
        self,
        inner: Any,
        on_chunk: Callable[[Any], None],
        on_finish: Callable[[], None],
    ) -> None:
        self._inner = inner
        self._on_chunk = on_chunk
        self._on_finish = on_finish
        self._iter: Iterator[Any] | None = None
        self._finished = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._iter is None:
            self._iter = iter(self._inner)
        try:
            chunk = next(self._iter)
        except StopIteration:
            self._mark_finished()
            raise
        try:
            self._on_chunk(chunk)
        except Exception:
            pass
        return chunk

    def _mark_finished(self) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self._on_finish()
        except Exception:
            pass

    def __enter__(self):
        if hasattr(self._inner, "__enter__"):
            self._inner.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if hasattr(self._inner, "__exit__"):
                return self._inner.__exit__(exc_type, exc, tb)
        finally:
            self._mark_finished()

    def close(self) -> Any:
        try:
            return self._inner.close()
        finally:
            self._mark_finished()

    # Forward attribute access for everything else (text_stream, response, ...)
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _AsyncStreamTap:
    def __init__(
        self,
        inner: Any,
        on_chunk: Callable[[Any], None],
        on_finish: Callable[[], None],
    ) -> None:
        self._inner = inner
        self._on_chunk = on_chunk
        self._on_finish = on_finish
        self._iter: Any = None
        self._finished = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._iter is None:
            self._iter = self._inner.__aiter__()
        try:
            chunk = await self._iter.__anext__()
        except StopAsyncIteration:
            self._mark_finished()
            raise
        try:
            self._on_chunk(chunk)
        except Exception:
            pass
        return chunk

    def _mark_finished(self) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self._on_finish()
        except Exception:
            pass

    async def __aenter__(self):
        if hasattr(self._inner, "__aenter__"):
            await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if hasattr(self._inner, "__aexit__"):
                return await self._inner.__aexit__(exc_type, exc, tb)
        finally:
            self._mark_finished()

    async def close(self) -> Any:
        try:
            inner_close = self._inner.close
        except AttributeError:
            self._mark_finished()
            return None
        try:
            result = inner_close()
            if isinstance(result, Awaitable):
                return await result
            return result
        finally:
            self._mark_finished()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
