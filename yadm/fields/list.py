"""
List of objects.

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

from collections import abc
from typing import NamedTuple, Any

from yadm.fields.base import DocumentLike, pass_null
from yadm.fields.containers import (
    Container,
    ContainerField,
)
from typing import Type


class ListInsert(NamedTuple):
    index: int  # type: ignore[assignment]
    value: Any
    op: str = 'list_insert'


class ListAppend(NamedTuple):
    value: Any
    op: str = 'list_append'


class ListRemove(NamedTuple):
    index: int  # type: ignore[assignment]
    op: str = 'list_remove'


class ListPush(NamedTuple):
    value: Any
    op: str = 'list_push'


class ListPull(NamedTuple):
    query: Any
    op: str = 'list_pull'


class List(Container, abc.MutableSequence):
    """ Container for list.
    """
    def insert(self, index: int, item: Any) -> None:
        """ Append item to list.

        This method does not save object!
        """
        self._data.insert(index, self._prepare_item(index, item))
        self.__log__.append(ListInsert(index=index, value=item))

    def append(self, item: Any) -> None:
        """ Append item to list.

        This method does not save object!
        """
        index = len(self)
        self._data.append(self._prepare_item(index, item))
        self.__log__.append(ListAppend(value=item))

    def remove(self, item: Any) -> None:
        """ Remove item from list.

        This method does not save object!
        """
        self._data.remove(item)
        self.__log__.append(ListRemove(index=item))

    def push(self, item: Any, reload: bool = True) -> None:
        """ Push item directly to database.

        See `$push` in MongoDB's `update_one`.
        """
        index = len(self)
        item = self._prepare_item(index, item)
        data = self._item_field.to_mongo(self, item)

        qs = self._get_queryset()
        qs.update_one({'$push': {self.__field_name__: data}})
        self._data.append(item)
        self.__log__.append(ListPush(value=item))

        if reload:
            self.reload()

    def pull(self, query: Any, reload: bool = True) -> None:
        """ Pull item from database.

        See `$pull` in MongoDB's `update_one`.
        """
        qs = self._get_queryset()
        qs.update_one({'$pull': {self.__field_name__: query}})
        self.__log__.append(ListPull(query=query))

        if reload:
            self.reload()

    def replace(self, query: Any, item: Any, reload: bool = True) -> None:
        """ Replace list elements.
        """
        data = self._item_field.to_mongo(self, item)

        processed_query = {}
        for key, value in query.items():
            processed_query['.'.join([self.__field_name__, key])] = value

        qs = self._get_queryset()
        qs = qs.find(processed_query)
        qs.update_one({'$set': {'.'.join([self.__field_name__, '$']): data}})

        if reload:
            self.reload()

    def update(self, query: Any, values: Any, reload: bool = True) -> None:
        """ Update fields in embedded documents.
        """
        processed_query = {}
        for key, value in query.items():
            processed_query['.'.join([self.__field_name__, key])] = value

        data = {}
        for key, value in values.items():
            data['.'.join([self.__field_name__, '$', key])] = value

        qs = self._get_queryset()
        qs = qs.find(processed_query)
        qs.update_one({'$set': data})

        if reload:
            self.reload()


class ListField(ContainerField[List]):
    """ Field for list values.

    For example, document with list of integers:

        class TestDoc(Document):
            __collection__ = 'testdoc'
            li = fields.ListField(fields.IntegerField())
    """
    container: Type[Container] = List

    def get_default_value(self) -> Any:
        return []

    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        pi = self.prepare_item
        container = self.container(self, document, [])
        g = (pi(container, n, i) for n, i in enumerate(value))
        container._data.extend(g)
        return container

    @pass_null
    def to_mongo(self, document: DocumentLike, value: Any) -> Any:
        tm = self.item_field.to_mongo
        return [tm(value, i) for i in value]

    @pass_null
    def from_mongo(self, document: DocumentLike, value: Any) -> Any:
        fm = self.item_field.from_mongo
        sp = self._set_parent

        container = self.container(self, document, [])
        g = (sp(container, n, fm(container, i)) for n, i in enumerate(value))
        container._data.extend(g)
        return container
