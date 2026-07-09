"""
Base classes for containers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, NamedTuple, Optional, Type, TypeVar

from yadm.markers import AttributeNotSet
from yadm.fields.base import Field, DocumentLike
from yadm.documents import DocumentItemMixin
from yadm.log_items import ChangeChild  # noqa

if TYPE_CHECKING:
    from typing import Self


class ContainerSetItem(NamedTuple):
    item: Any
    value: Any
    op: str = 'container_setitem'


class ContainerDelitem(NamedTuple):
    item: Any
    op: str = 'container_delitem'


class ContainerReload(NamedTuple):
    op: str = 'container_reload'


class Container(DocumentItemMixin):
    """ Base class for containers.
    """
    _field: Any
    _item_field: Any
    _data: Any

    def __init__(self, field: Any, parent: Any, value: Any) -> None:
        super().__init__()
        self.__name__ = field.name
        self.__parent__ = parent
        self._field = field
        self._item_field = field.item_field
        self._data = value

    def __iter__(self) -> Iterator[Any]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, item: Any) -> Any:
        return self._data[item]

    def __setitem__(self, item: Any, value: Any) -> None:
        self._data[item] = self._prepare_item(item, value)
        self.__log__.append(ContainerSetItem(item=item, value=value))

    def __delitem__(self, item: Any) -> None:
        del self._data[item]
        self.__log__.append(ContainerDelitem(item=item))

    def __contains__(self, item: Any) -> bool:
        return item in self._data

    def __repr__(self) -> str:
        return '{}({!r})'.format(self.__class__.__name__, self._data)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Container):
            return self._data == other._data
        else:
            return self._data == other

    def _prepare_item(self, item: Any, value: Any) -> Any:
        return self._field.prepare_item(self, item, value)

    def _get_queryset(self) -> Any:
        """ Return queryset for got data for this field.
        """
        db = self.__db__
        if db is None:
            raise RuntimeError('object not binded to database')

        document = self.__document__
        assert document is not None
        qs = db.get_queryset(document.__class__)
        qs = qs.find({'_id': document.id})
        return qs.fields(self.__field_name__)

    def reload(self) -> None:
        """ Reload all object from database.
        """
        if len(list(self.__path__)) > 1:
            raise ValueError("can't reload deep objects: {}"
                             "".format(self.__field_name__))

        doc = self._get_queryset().read_primary().find_one()
        self._data = self.__get_value__(doc)._data
        self.__log__.append(ContainerReload())


TContainer = TypeVar('TContainer', bound=Container)


class ContainerField(Field[TContainer]):
    """ Base class for container fields.
    """
    container: Type[Container] = Container
    item_field: Any
    auto_create: bool

    def __init__(self, item_field: Optional[Field[Any]] = None, *,
                 auto_create: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if not isinstance(item_field, (Field, type(None))):
            raise TypeError("first argument must be field isinstance or None,"
                            " but {}".format(item_field))

        self.item_field = item_field
        self.auto_create = auto_create

    def copy(self) -> Self:
        """ Return copy of field.
        """
        return self.__class__(
            item_field=self.item_field,
            auto_create=self.auto_create,
            smart_null=self.smart_null,
        )

    def get_default(self, document: DocumentLike) -> Any:
        if self.auto_create:
            return self.container(self, document, self.get_default_value())
        else:
            return AttributeNotSet

    def prepare_item(self, container: Container, item: Any, value: Any) -> Any:
        if self.item_field is not None:
            value = self.item_field.prepare_value(container, value)
            self._set_parent(container, item, value)
            return value
        else:
            raise NotImplementedError(
                "item_field is None, but prepare_item is not implemented")

    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        # return self.container(self, document, value)
        raise NotImplementedError

    def get_default_value(self) -> Any:
        raise NotImplementedError

    def to_mongo(self, document: DocumentLike, value: Any) -> Any:
        # return value._data
        raise NotImplementedError

    def from_mongo(self, document: DocumentLike, value: Any) -> Any:
        # return self.container(self, document, value)
        raise NotImplementedError

    def _set_parent(self, container: Container, name: Any, value: Any) -> Any:
        if isinstance(value, DocumentItemMixin):
            value.__parent__ = container
            value.__name__ = name

        return value
