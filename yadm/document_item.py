from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Optional, Union, cast

from yadm.log_items import BaseLog, ChangeChild

if TYPE_CHECKING:  # pragma: no cover - imported only for typing
    from yadm.database import BaseDatabase
    from yadm.documents import BaseDocument
    from yadm.queryset import QuerySet


class ItemLog(BaseLog):
    def __init__(self, document_item):
        super().__init__()
        self.document_item = document_item

    def append(self, log_item):
        self.items.append(log_item)

        root = self.document_item.__document__
        if root is not None:
            self.document_item.__document__.__log__.append(
                ChangeChild(
                    path=self.document_item.__field_name__,
                    name=self.document_item.__name__,
                    log_item=log_item,
                ),
            )


class DocumentItemMixin:
    """ Mixin for custom all fields values, such as EmbeddedDocument,
        yadm.fields.containers.Container.
    """
    __parent__: Optional[Union['DocumentItemMixin', 'BaseDocument']] = None
    __name__: Optional[Union[str, int]] = None
    __log__: ItemLog

    def __init__(self, *args, **kwargs):
        self.__log__ = ItemLog(self)
        super().__init__(*args, **kwargs)

    @property
    def __document__(self) -> Optional['BaseDocument']:
        """ Root document.

        .. code-block:: python

                assert doc.f.l[0].__document__ is doc
        """
        obj: Any = self

        while isinstance(obj, DocumentItemMixin) and obj.__parent__ is not None:
            obj = obj.__parent__

        if obj is self:
            return None

        return cast(Optional['BaseDocument'], obj)

    @property
    def __db__(self) -> Optional['BaseDatabase']:
        """ Database object.

        .. code-block:: python

            assert doc.f.l[0].__db__ is doc.__db__
        """
        document = self.__document__
        if document is not None:
            return cast(Optional['BaseDatabase'], getattr(document, '__db__', None))
        return None  # pragma: no cover

    @property
    def __qs__(self) -> Optional['QuerySet']:
        """ Queryset object.
        """
        document = self.__document__
        if document is not None:
            return cast(Optional['QuerySet'], getattr(document, '__qs__', None))
        return None  # pragma: no cover

    @property
    def __path__(self) -> Iterator['DocumentItemMixin']:
        """ Path to root generator.

        .. code-block:: python

            assert list(doc.f.l[0].__path__) == [doc.f.l[0], doc.f.l, doc.f]
        """
        obj: Optional[DocumentItemMixin] = self

        while isinstance(obj, DocumentItemMixin) and obj.__parent__ is not None:
            yield obj
            parent = obj.__parent__
            if isinstance(parent, DocumentItemMixin):
                obj = parent
            else:
                break

    @property
    def __path_names__(self) -> Iterator[Union[str, int]]:
        """ Path to root generator.

        .. code-block:: python

            assert list(doc.f.l[0].__path__) == [0, 'l', 'f']
        """
        for item in self.__path__:
            name = item.__name__
            if name is not None:
                yield name

    @property
    def __field_name__(self) -> str:
        """ Dotted field name for MongoDB opperations, like as $set, $push and other...

        .. code-block:: python

            assert doc.f.l[0].__field_name__ == 'f.l.0'
        """
        return '.'.join(reversed([str(i) for i in self.__path_names__]))

    def __get_value__(self, document: 'BaseDocument') -> Any:
        """ Get value from document with path to self.
        """
        obj: Any = document

        for name in reversed(list(self.__path_names__)):
            if isinstance(name, int):
                obj = obj[name]
            else:
                obj = getattr(obj, name)

        return obj
