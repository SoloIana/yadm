from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterator

from yadm.fields.base import DocumentLike, Field


class UnmutableMap(Mapping):
    def __init__(self, data: Any) -> None:
        self._data = data

    def __getitem__(self, item: Any) -> Any:
        return self._data[item]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover
        return repr("{}({!r})".format(self.__class__.__name__, self._data))


class MongoMapField(Field[UnmutableMap]):
    def __init__(self, smart_null: bool = False) -> None:
        super().__init__(smart_null=smart_null)

    def get_fake(self, document: DocumentLike,
                 faker: Any, deep: Any) -> Any:  # pragma: no cover
        return UnmutableMap({})

    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        return UnmutableMap(value)

    def from_mongo(self, document: DocumentLike, value: Any) -> Any:
        return UnmutableMap(value)

    def to_mongo(self, document: DocumentLike, value: Any) -> Any:
        return dict(value)
