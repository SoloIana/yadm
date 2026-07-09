"""
Field with sets.

Similar as :py:mod:`yadm.fields.list`.
"""
from __future__ import annotations

from collections import abc
from typing import NamedTuple, Any

from typing import Type

from yadm.fields.containers import Container
from yadm.fields.list import ListField


class SetAdd(NamedTuple):
    value: Any
    op: str = 'set_add'


class SetDiscard(NamedTuple):
    value: Any
    op: str = 'set_discard'


class SetRemove(NamedTuple):
    value: Any
    op: str = 'set_remove'


class SetAddToSet(NamedTuple):
    value: Any
    op: str = 'set_add_to_set'


class SetPull(NamedTuple):
    query: Any
    op: str = 'set_pull'


class Set(Container, abc.MutableSet):
    """ Container for set.
    """
    def __getitem__(self, item: Any) -> Any:
        raise TypeError("'{}' object does not support indexing"
                        "".format(self.__class__.__name__))

    def __setitem__(self, item: Any, value: Any) -> None:
        raise TypeError("'{}' object does not support item assignment"
                        "".format(self.__class__.__name__))

    def __delitem__(self, item: Any) -> None:
        raise TypeError("'{}' object doesn't support item deletion"
                        "".format(self.__class__.__name__))

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, set):
            return set(self) == set(other)
        else:
            return False

    def add(self, item: Any) -> None:
        """ Append item to set.

        This method does not save object!
        """
        item = self._prepare_item(len(self), item)
        if item not in self._data:
            self._data.append(item)
            self.__log__.append(SetAdd(value=item))

    def discard(self, item: Any) -> None:
        """ Remove item from the set if it is present.

        This method does not save object!
        """
        try:
            self._data.remove(item)
        except ValueError:
            pass
        else:
            self.__log__.append(SetDiscard(value=item))

    def remove(self, item: Any) -> None:
        """ Remove item from set.

        This method does not save object!
        """
        try:
            self._data.remove(item)
        except ValueError as exc:
            raise KeyError from exc
        else:
            self.__log__.append(SetRemove(value=item))

    def add_to_set(self, item: Any, reload: bool = True) -> None:
        """ Add item directly to database.

        See `$addToSet` in MongoDB's `update_one`.
        """
        index = len(self)
        item = self._prepare_item(index, item)
        data = self._field.item_field.to_mongo(self.__document__, item)

        qs = self._get_queryset()
        qs.update_one({'$addToSet': {self.__field_name__: data}})

        item = self._prepare_item(len(self), item)
        if item not in self._data:
            self._data.append(item)

        self.__log__.append(SetAddToSet(value=item))

        if reload:
            self.reload()

    def pull(self, query: Any, reload: bool = True) -> None:
        """ Pull item from database.

        See `$pull` in MongoDB's `update_one`.
        """
        qs = self._get_queryset()
        qs.update_one({'$pull': {self.__field_name__: query}})

        self.__log__.append(SetPull(query=query))

        if reload:
            self.reload()


class SetField(ListField):
    """ Field for set values.
    """
    container: Type[Container] = Set
