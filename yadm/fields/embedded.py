"""
Work with embedded documents.

.. code-block:: python

    class EDoc(EmbeddedDocument):
        i = fields.IntegerField()

    class Doc(Document):
        __collection__ = 'docs'
        edoc = EmbeddedDocumentField(EDoc)

    doc = Doc()
    doc.edoc = EDoc()
    doc.edoc.i = 13
    db.insert_one(doc)
"""
from __future__ import annotations

import random
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Optional,
    Type,
    TypeVar,
    overload,
)

from yadm.common import EnclosedDocDescriptor
from yadm.documents import EmbeddedDocument, MetaDocument
from yadm.markers import AttributeNotSet
from yadm.fields.base import DocumentLike, Field, pass_null
from yadm.serialize import to_mongo, from_mongo
from yadm.testing import create_fake
from yadm.aio.testing import aio_create_fake

if TYPE_CHECKING:
    from faker import Faker

TEDoc = TypeVar('TEDoc', bound=EmbeddedDocument)


class BaseEmbeddedDocumentField(Field[TEDoc]):
    def get_embedded_document_class(
            self, document: Any, value: Any) -> Type[TEDoc]:
        """ Return class of embedded document for field.
        """
        raise NotImplementedError()

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        if value is AttributeNotSet:
            return value

        elif isinstance(value, EmbeddedDocument):
            value.__parent__ = document
            value.__name__ = self.name

        else:
            raise TypeError("Only EmbeddedDocument is allowed, but {!r} given"
                            "".format(type(value)))

        return value

    @pass_null
    def to_mongo(self, document: DocumentLike, value: Any) -> Any:
        return to_mongo(value)

    @pass_null
    def from_mongo(self, document: DocumentLike, value: Any) -> Any:
        ed_class = self.get_embedded_document_class(document, value)
        not_loaded = set()

        document_not_loaded = getattr(document, '__not_loaded__', None)
        if document_not_loaded:
            _sw = self.name + '.'
            for field_name in document_not_loaded:
                if field_name.startswith(_sw):
                    not_loaded.add(field_name[len(_sw):])

        return from_mongo(ed_class, value,
                          not_loaded=not_loaded,
                          parent=document,
                          name=self.name)


class EmbeddedDocumentField(BaseEmbeddedDocumentField[TEDoc]):
    """ Field for embedded objects.

    :param EmbeddedDocument embedded_document_class:
        class for embedded document
    :param bool auto_create: automatic creation embedded
        document from access
    """
    auto_create = True
    embedded_document_class = EnclosedDocDescriptor('embedded')

    @overload
    def __init__(self: EmbeddedDocumentField[TEDoc],
                 embedded_document_class: Type[TEDoc], *,
                 auto_create: bool = True, **kwargs: Any) -> None: ...

    @overload
    def __init__(self: EmbeddedDocumentField[Any],
                 embedded_document_class: Optional[str], *,
                 auto_create: bool = True, **kwargs: Any) -> None: ...

    def __init__(self, embedded_document_class: Any, *,
                 auto_create: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.embedded_document_class = embedded_document_class
        self.auto_create = auto_create

    def get_embedded_document_class(
            self, document: Any = None, value: Any = None) -> Type[TEDoc]:
        return self.embedded_document_class

    def get_if_attribute_not_set(self, document: DocumentLike) -> Any:
        """ Call if key not exist in document.

        If auto_create is True, create and return new
        embedded document. Else AttributeError is raised.
        """
        if self.auto_create:
            ed_class = self.get_embedded_document_class(document)
            ed = ed_class(__parent__=document, __name__=self.name)
            setattr(document, self.name, ed)
            return ed
        else:
            return super().get_if_attribute_not_set(document)

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Any:
        is_aio = False
        t_doc = document
        while True:
            db = getattr(t_doc, '__db__', None)
            if db is not None:
                is_aio = db.aio
                break
            else:
                parent = getattr(t_doc, '__parent__', None)
                if parent is not None:
                    t_doc = parent
                else:
                    break

        func: Callable[..., Any]
        if not is_aio:
            func = create_fake
        else:
            func = aio_create_fake
        return func(
            self.get_embedded_document_class(document),
            __parent__=document,
            __name__=self.name,
            __faker__=faker,
            __depth__=depth,
        )

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        if value is AttributeNotSet:
            return value

        ed_class = self.get_embedded_document_class(document, value)

        if isinstance(value, dict):
            value = ed_class(__parent__=document, __name__=self.name, **value)

        elif isinstance(value, ed_class):
            value.__parent__ = document
            value.__name__ = self.name

        else:
            raise TypeError("Only {!r}, dict or None is allowed, but {!r} given"
                            "".format(ed_class, type(value)))

        return value

    def copy(self) -> EmbeddedDocumentField[TEDoc]:
        """ Return copy of field.
        """
        ed_class = self.get_embedded_document_class()
        return self.__class__(ed_class, smart_null=self.smart_null)


class TypedEmbeddedDocumentField(BaseEmbeddedDocumentField[TEDoc]):
    """ Field for embedded document with variable types.

    :param str type_field: name of field in embedded document
        for select type
    :param dict types: map of type names to embedded document classes
    """
    # both stay Any: __init__ raises if they are left None, but mypy cannot
    # narrow None away across method bodies (get_fake does **{type_field: ...})
    type_field: Any = None
    types: Any = None

    def __init__(self, type_field: Optional[str] = None,
                 types: Optional[Dict[str, Type[EmbeddedDocument]]] = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.type_field = type_field or self.type_field
        self.types = types or self.types

        if self.types is None:
            raise TypeError("type attribute is not set")
        elif self.type_field is None:
            raise TypeError("type_field attribute is not set")

    def get_embedded_document_class(
            self, document: Any, value: Any) -> Type[TEDoc]:
        type_name = value.get(self.type_field, AttributeNotSet)
        ed_class = self.types.get(type_name, None)

        if ed_class is None:
            raise ValueError("Not found document type for {!r}"
                             "".format(type_name))
        else:
            return ed_class

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Any:
        type_name = random.choice(list(self.types))
        ed_class = self.get_embedded_document_class(
            document=document,
            value={self.type_field: type_name},
        )

        return create_fake(
            ed_class,
            __parent__=document,
            __name__=self.name,
            __faker__=faker,
            __depth__=depth,
            **{self.type_field: type_name}
        )


class SimpleEmbeddedDocumentField(EmbeddedDocumentField[Any]):
    """ Field for simply create embedded documents.

    Usage:

        class Doc(Document):
            embedded = SimpleEmbeddedDocumentField({
                'i': IntegerField(),
                's': StringField(),
            })
    """
    embedded_document_class: Any = None

    def __init__(self, fields: dict, *,
                 auto_create: bool = True, **kwargs: Any) -> None:
        if not isinstance(fields, dict):
            raise TypeError("First argument must be a dict, not {}"
                            "".format(type(fields)))
        elif not fields:
            raise ValueError("fields is empty")

        self.fields = fields

        super().__init__(None, auto_create=auto_create, **kwargs)

    def contribute_to_class(self, document_class: MetaDocument, name: str) -> None:
        super().contribute_to_class(document_class, name)

        self.embedded_document_class = type(
            '{}__{}'.format(document_class.__name__, name),
            (EmbeddedDocument,),
            self.fields,
        )
