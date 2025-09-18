"""List field container implementation.

Example usage::

    class Doc(Document):
        __collection__ = 'docs'
        integers = fields.ListField(fields.IntegerField)

    doc = Doc()
    doc.integers.append(1)
    doc.integers.append(2)
    assert doc.integers == [1, 2]

    db.insert_one(doc)
    doc = db.get_queryset(Doc).find_one(doc.id)  # reload

    doc.integers.append(3)  # do not save
    assert doc.integers == [1, 2, 3]
    doc = db.get_queryset(Doc).find_one(doc.id)  # reload
    assert doc.integers == [1, 2]

    doc.integers.remove(2)  # do not save too
    assert doc.integers == [1]
    doc = db.get_queryset(Doc).find_one(doc.id)  # reload
    assert doc.integers == [1, 2]

    doc.integers.push(3)  # $push query
    assert doc.integers == [1, 2, 3]
    doc = db.get_queryset(Doc).find_one(doc.id)  # reload
    assert doc.integers == [1, 2, 3]

    doc.integers.pull(2)  # $pull query
    assert doc.integers == [1, 3]
    doc = db.get_queryset(Doc).find_one(doc.id)  # reload
    assert doc.integers == [1, 3]
"""
from __future__ import annotations

from collections.abc import Iterable, MutableSequence, Sequence
from dataclasses import dataclass
from typing import Any, List as TypingList, Mapping, Union, cast, overload

from yadm.fields.base import pass_null
from yadm.fields.containers import (
    Container,
    ContainerDelitem,
    ContainerField,
    ContainerSetItem,
)


@dataclass(frozen=True)
class ListInsert:
    index: int
    value: Any
    op: str = 'list_insert'


@dataclass(frozen=True)
class ListAppend:
    value: Any
    op: str = 'list_append'


@dataclass(frozen=True)
class ListRemove:
    value: Any
    op: str = 'list_remove'


@dataclass(frozen=True)
class ListPush:
    value: Any
    op: str = 'list_push'


@dataclass(frozen=True)
class ListPull:
    query: Any
    op: str = 'list_pull'


class List(Container, MutableSequence[Any]):
    """Container for list values bound to a document."""

    _data: TypingList[Any]

    @overload
    def __getitem__(self, index: int) -> Any:
        ...

    @overload
    def __getitem__(self, index: slice) -> TypingList[Any]:
        ...

    def __getitem__(self, index: Union[int, slice]) -> Union[Any, TypingList[Any]]:
        return self._data[index]

    @overload
    def __setitem__(self, index: int, value: Any) -> None:
        ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[Any]) -> None:
        ...

    def __setitem__(self, index: Union[int, slice], value: Union[Any, Iterable[Any]]) -> None:
        if isinstance(index, slice):
            items = list(cast(Iterable[Any], value))
            start, stop, step = index.indices(len(self._data))
            indices = list(range(start, stop, step))

            if step != 1 and len(items) != len(indices):
                raise ValueError(
                    'attempt to assign sequence of size {given} '
                    'to extended slice of size {expected}'.format(
                        given=len(items),
                        expected=len(indices),
                    ),
                )

            def target_offset(offset: int) -> int:
                if step == 1:
                    return start + offset
                return indices[offset]

            prepared = [
                self._prepare_item(target_offset(offset), item)
                for offset, item in enumerate(items)
            ]
            self._data[index] = prepared

            for offset, original in enumerate(items):
                self.__log__.append(
                    ContainerSetItem(
                        item=target_offset(offset),
                        value=original,
                    ),
                )
        else:
            super().__setitem__(index, cast(Any, value))

    @overload
    def __delitem__(self, index: int) -> None:
        ...

    @overload
    def __delitem__(self, index: slice) -> None:
        ...

    def __delitem__(self, index: Union[int, slice]) -> None:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self._data))
            for idx in reversed(range(start, stop, step)):
                del self._data[idx]
                self.__log__.append(ContainerDelitem(item=idx))
        else:
            super().__delitem__(index)

    def insert(self, index: int, item: Any) -> None:
        """Append item to list without persisting it."""

        self._data.insert(index, self._prepare_item(index, item))
        self.__log__.append(ListInsert(index=index, value=item))

    def append(self, item: Any) -> None:
        """Append item to list without persisting it."""

        index = len(self)
        self._data.append(self._prepare_item(index, item))
        self.__log__.append(ListAppend(value=item))

    def remove(self, item: Any) -> None:
        """Remove item from list without persisting the change."""

        self._data.remove(item)
        self.__log__.append(ListRemove(value=item))

    def push(self, item: Any, reload: bool = True) -> None:
        """Push item directly to MongoDB using the ``$push`` operator."""

        index = len(self)
        prepared_item = self._prepare_item(index, item)
        item_field = self._item_field
        if item_field is None:
            raise TypeError('List container has no item field configured')

        data = item_field.to_mongo(self, prepared_item)

        qs = self._get_queryset()
        qs.update_one({'$push': {self.__field_name__: data}})
        self._data.append(prepared_item)
        self.__log__.append(ListPush(value=prepared_item))

        if reload:
            self.reload()

    def pull(self, query: Any, reload: bool = True) -> None:
        """Remove items directly from MongoDB with the ``$pull`` operator."""

        qs = self._get_queryset()
        qs.update_one({'$pull': {self.__field_name__: query}})
        self.__log__.append(ListPull(query=query))

        if reload:
            self.reload()

    def replace(self, query: Mapping[str, Any], item: Any, reload: bool = True) -> None:
        """Replace list elements matching ``query`` with ``item``."""

        item_field = self._item_field
        if item_field is None:
            raise TypeError('List container has no item field configured')

        data = item_field.to_mongo(self, item)

        processed_query: dict[str, Any] = {}
        for key, value in query.items():
            processed_query['.'.join([self.__field_name__, key])] = value

        qs = self._get_queryset()
        qs = qs.find(processed_query)
        qs.update_one({'$set': {'.'.join([self.__field_name__, '$']): data}})

        if reload:
            self.reload()

    def update(
        self,
        query: Mapping[str, Any],
        values: Mapping[str, Any],
        reload: bool = True,
    ) -> None:
        """Update fields in embedded documents matching ``query``."""

        processed_query: dict[str, Any] = {}
        for key, value in query.items():
            processed_query['.'.join([self.__field_name__, key])] = value

        data: dict[str, Any] = {}
        for key, value in values.items():
            data['.'.join([self.__field_name__, '$', key])] = value

        qs = self._get_queryset()
        qs = qs.find(processed_query)
        qs.update_one({'$set': data})

        if reload:
            self.reload()


class ListField(ContainerField):
    """Field for list values.

    For example, document with list of integers::

        class TestDoc(Document):
            __collection__ = 'testdoc'
            li = fields.ListField(fields.IntegerField())
    """

    container: type[Container] = List

    def get_default_value(self) -> TypingList[Any]:
        return []

    def prepare_value(self, document: Any, value: Iterable[Any]) -> List:
        container = cast(List, self.container(self, document, []))
        prepared_items = [
            self.prepare_item(container, index, item)
            for index, item in enumerate(value)
        ]
        container._data.extend(prepared_items)
        return container

    @pass_null
    def to_mongo(self, document: Any, value: Sequence[Any]) -> TypingList[Any]:
        item_field = self.item_field
        if item_field is None:
            raise TypeError('ListField requires an item_field instance')

        return [item_field.to_mongo(value, item) for item in value]

    @pass_null
    def from_mongo(self, document: Any, value: Sequence[Any]) -> List:
        item_field = self.item_field
        if item_field is None:
            raise TypeError('ListField requires an item_field instance')

        container = cast(List, self.container(self, document, []))
        prepared_items = [
            self._set_parent(container, index, item_field.from_mongo(container, item))
            for index, item in enumerate(value)
        ]
        container._data.extend(prepared_items)
        return container
