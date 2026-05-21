from collections.abc import Callable

_initializers: list[tuple[Callable, int]] = []


def initializer(priority: int = 10) -> Callable:
    def decorator(func: Callable) -> Callable:
        _initializers.append((func, priority))
        return func
    return decorator
