import asyncio
import functools
import time
import uuid
from typing import Any, Callable, Optional

from ._client import _client
from ._context import _reset_run_id, _set_run_id


def track(
    _func: Optional[Callable[..., Any]] = None,
    *,
    agent_name: Optional[str] = None,
):
    """Wrap a function as a Beacon run.

    Generates a run_id, binds it to the contextvar so any nested emits land in
    the right run, emits run_started before and run_ended (or run_failed)
    after.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                run_id = str(uuid.uuid4())
                token = _set_run_id(run_id)
                started = time.time()
                _client.emit(
                    "run_started",
                    {"function": func.__name__},
                    run_id=run_id,
                    agent_name=agent_name,
                )
                try:
                    result = await func(*args, **kwargs)
                except BaseException as e:
                    _client.emit(
                        "run_failed",
                        {
                            "function": func.__name__,
                            "duration_s": time.time() - started,
                            "error": repr(e),
                        },
                        run_id=run_id,
                        agent_name=agent_name,
                    )
                    raise
                else:
                    _client.emit(
                        "run_ended",
                        {
                            "function": func.__name__,
                            "duration_s": time.time() - started,
                        },
                        run_id=run_id,
                        agent_name=agent_name,
                    )
                    return result
                finally:
                    _reset_run_id(token)

            return awrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            run_id = str(uuid.uuid4())
            token = _set_run_id(run_id)
            started = time.time()
            _client.emit(
                "run_started",
                {"function": func.__name__},
                run_id=run_id,
                agent_name=agent_name,
            )
            try:
                result = func(*args, **kwargs)
            except BaseException as e:
                _client.emit(
                    "run_failed",
                    {
                        "function": func.__name__,
                        "duration_s": time.time() - started,
                        "error": repr(e),
                    },
                    run_id=run_id,
                    agent_name=agent_name,
                )
                raise
            else:
                _client.emit(
                    "run_ended",
                    {
                        "function": func.__name__,
                        "duration_s": time.time() - started,
                    },
                    run_id=run_id,
                    agent_name=agent_name,
                )
                return result
            finally:
                _reset_run_id(token)

        return wrapper

    if _func is None:
        return decorator
    return decorator(_func)
