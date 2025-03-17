from typing import Callable, List, Tuple
from flask import Flask

_initializers: List[Tuple[Callable, int]] = []

def initializer(priority: int = 10) -> Callable:
    def decorator(func: Callable) -> Callable:
        _initializers.append((func, priority))
        return func
    return decorator

def run_initializers(app: Flask):
    with app.app_context():
        for func, _ in sorted(_initializers, key=lambda x: x[1]):
            func()