"""Adapters: the outside systems the app talks to, behind one interface per kind.

    adapters/crm/        the CRM the call desk reads leads from and writes call results to (crm.py uses it)
    adapters/telephony/  the phone system recordings come from and the softphone signs in to (telephony.py uses it)

Each kind has a base class (base.py) that says what an adapter must do and the shape of the data it hands back,
and one module per product (twenty.py, govoice.py). The rest of the app only ever calls crm.py and telephony.py,
so connecting another CRM or phone system is writing one adapter and choosing it in Settings (CRM_PROVIDER,
TELEPHONY_PROVIDER), without touching the call desk, the pipeline or the UI's API.
"""
import importlib
import threading
from typing import Callable, Generic, TypeVar

from ..config import live

T = TypeVar("T")


class Registry(Generic[T]):
    """The adapters of one kind by name, and the one chosen in Settings (`setting`, else `default`).

    Built-in adapters are given as "module:Class" so only the chosen one is imported. Others can be added with
    register(), e.g. from a plugin: telephony.registry.register("3cx", ThreeCxTelephony)."""

    def __init__(self, kind: str, setting: str, default: str, builtin: dict[str, str]):
        self.kind, self.setting, self.default = kind, setting, default
        self._factories: dict[str, str | Callable[[], T]] = dict(builtin)
        self._instances: dict[str, T] = {}
        self._override: T | None = None
        self._lock = threading.Lock()

    def register(self, name: str, factory: str | Callable[[], T]) -> None:
        with self._lock:
            self._factories[name.lower()] = factory
            self._instances.pop(name.lower(), None)

    def names(self) -> list[str]:
        return sorted(self._factories)

    def active_name(self) -> str:
        return live(self.setting, self.default).lower()

    def get(self, name: str | None = None) -> T:
        """The adapter called `name`, or the one chosen in Settings. Adapters read their own settings live, so one
        instance per name is kept."""
        if self._override is not None and name is None:
            return self._override
        name = (name or self.active_name()).lower()
        with self._lock:
            if name not in self._instances:
                factory = self._factories.get(name)
                if factory is None:
                    raise RuntimeError(f"Unknown {self.kind} {name!r} ({self.setting}): choose one of "
                                       f"{', '.join(self.names())}")
                if isinstance(factory, str):
                    module, _, attr = factory.partition(":")
                    factory = getattr(importlib.import_module(module, __package__), attr)
                self._instances[name] = factory()
            return self._instances[name]

    def use(self, adapter: T | None) -> None:
        """Use this adapter instead of the chosen one until use(None), e.g. a fake in the tests."""
        self._override = adapter
