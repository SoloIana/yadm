from __future__ import annotations

import abc
from typing import Any, List


class CacheInterface(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def __getitem__(self, key: Any) -> Any:  # pragma: no cover
        pass

    @abc.abstractmethod
    def __setitem__(self, key: Any, value: Any) -> None:  # pragma: no cover
        pass

    @abc.abstractmethod
    def __delitem__(self, key: Any) -> None:  # pragma: no cover
        pass

    @abc.abstractmethod
    def __contains__(self, key: Any) -> bool:  # pragma: no cover
        pass

    @abc.abstractmethod
    def __len__(self, key: Any) -> int:  # pragma: no cover
        pass


@CacheInterface.register
class NotACache:
    def __getitem__(self, key: Any) -> Any:  # pragma: no cover
        raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:  # pragma: no cover
        pass

    def __delitem__(self, key: Any) -> None:  # pragma: no cover
        pass

    def __contains__(self, key: Any) -> bool:  # pragma: no cover
        return False

    def __len__(self, key: Any) -> int:  # pragma: no cover
        return 0


@CacheInterface.register
class StackCache(dict):
    def __init__(self, size: int) -> None:
        self.size = size
        self._stack: List[Any] = []

    def __setitem__(self, key: Any, item: Any) -> None:
        if key not in self:
            self._stack.append(key)

            if len(self._stack) > self.size:
                del self[self._stack[0]]

        super().__setitem__(key, item)

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self._stack.remove(key)
