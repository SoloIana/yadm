"""
Work with references.

.. code-block:: python

    class RDoc(Document):
        i = fields.IntegerField()

    class Doc(Document):
        rdoc = fields.ReferenceField(RDoc)

    rdoc = RDoc()
    rdoc.i = 13
    db.insert_one(rdoc)

    doc = Doc()
    doc.rdoc = rdoc
    db.insert_one(doc)

    doc = db.get_queryset(Doc).find_one(doc.id)  # reload doc
    assert doc.rdoc.id == rdoc.id
    assert doc.rdoc.i == 13

Or with asyncio:

.. code-block:: python

    rdoc = await doc.rdoc
    assert rdoc.id == rdoc.id
    assert rdoc.i == 13
    assert doc.rdoc == rdoc.id

"""
from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Optional,
    Type,
    TypeVar,
    overload,
)

from bson import ObjectId

from yadm.common import EnclosedDocDescriptor
from yadm.markers import AttributeNotSet
from yadm.documents import Document, DocumentItemMixin  # noqa
from yadm.fields.base import DocumentLike, Field, FieldDescriptor, pass_null
from yadm.serialize import from_mongo
from yadm.testing import create_fake
from yadm.aio.testing import aio_create_fake

if TYPE_CHECKING:
    from typing import Self

    from faker import Faker

TDoc = TypeVar('TDoc', bound=Document)


class BrokenReference(Exception):
    """ Raise if referrenced document is not found.
    """


class NotBindingToDatabase(Exception):  # noqa
    """ Raise if set ObjectId insted referenced document
    to new document, who not binded to database.
    """


class ReferenceFieldDescriptor(FieldDescriptor[Any]):

    def __get__(self, instance: Any, owner: Optional[type] = None) -> Any:
        if instance is None:
            return self.field

        name = self.name
        if (instance.__db__ is not None
                and name in instance.__cache__
                and instance.__db__.aio
                and isinstance(instance.__cache__[name], Document)):
            ref = Reference(instance.__cache__[name].id, instance, instance.__class__)
            ref.document = instance.__cache__[name]
            return ref
        else:
            return super().__get__(instance, owner)


class ReferenceField(Field[TDoc]):
    """ Field for work with references.

    :param reference_document_class: class for refered documents
    """
    descriptor_class = ReferenceFieldDescriptor
    reference_document_class = EnclosedDocDescriptor('reference')

    @overload
    def __init__(self: ReferenceField[TDoc],
                 reference_document_class: Type[TDoc],
                 **kwargs: Any) -> None: ...

    @overload
    def __init__(self: ReferenceField[Any],
                 reference_document_class: str,
                 **kwargs: Any) -> None: ...

    def __init__(self, reference_document_class: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.reference_document_class = reference_document_class

    if TYPE_CHECKING:
        # Instance access is typed Any: a sync database resolves the
        # reference to the document, an aio database returns an awaitable
        # Reference and smart_null may give None.
        @overload
        def __get__(self, instance: None, owner: type) -> Self: ...
        @overload
        def __get__(self, instance: Any, owner: type) -> Any: ...
        def __get__(self, instance: Any, owner: type) -> Any: ...

    def get_default(self, document: DocumentLike) -> Any:
        if self.smart_null:  # pragma: no cover
            return None
        else:
            return AttributeNotSet

    def _get_fake(self, document: Any,
                  faker: Faker, depth: int) -> Any:
        return create_fake(self.reference_document_class,
                           __db__=document.__db__,
                           __faker__=faker,
                           __depth__=depth)

    async def _get_fake_aio(self, document: Any,
                            faker: Faker, depth: int) -> Any:
        return await aio_create_fake(self.reference_document_class,
                                     __db__=document.__db__,
                                     __faker__=faker,
                                     __depth__=depth)

    def get_fake(self, document: Any,
                 faker: Faker, depth: int) -> Any:
        """ Try create referenced document.
        """
        if document.__db__ is not None and document.__db__.aio:
            return self._get_fake_aio(document, faker, depth)
        else:
            return self._get_fake(document, faker, depth)

    def copy(self) -> Self:
        return self.__class__(self.reference_document_class,
                              smart_null=self.smart_null)

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        if isinstance(value, Document):
            return value
        elif value is AttributeNotSet:  # pragma: no cover
            return AttributeNotSet
        else:
            return self.from_mongo(document, value)

    @pass_null
    def from_mongo(self, document: Any, value: Any) -> Any:
        """ Resolve reference.

        1. Lookup in querysets cache;
        2. Lookup in __yadm_lookups__[self.name];
        3. Lookup in database;
        4. Raise BrokenReference if not found.
        """
        rdc = self.reference_document_class

        if document.__qs__ is not None:
            cache = document.__qs__.cache
        else:
            cache = {}  # fake cache

        if (rdc, value) in cache:
            return cache[(rdc, value)]

        elif (isinstance(document, Document) and
                self.name in document.__yadm_lookups__):
            cache[(rdc, value)] = doc = from_mongo(
                document_class=rdc,
                raw=document.__yadm_lookups__[self.name],
            )
            doc.__db__ = document.__db__
            return doc

        elif document.__db__ is not None:
            if document.__db__.aio:
                cache[(rdc, value)] = ref = Reference(
                    value,
                    document,
                    self.reference_document_class,
                )
                return ref
            else:
                qs = document.__db__.get_queryset(rdc, cache=cache)
                doc = qs.find_one(value)
                if doc is None:  # pragma: no cover
                    doc = qs.read_primary().find_one(value, exc=BrokenReference)

                cache[(rdc, value)] = doc
                return doc

        else:
            raise NotBindingToDatabase((document, self, value))

    @pass_null
    def to_mongo(self, document: DocumentLike, value: Document) -> Any:
        return value.id


class Reference(ObjectId):
    """ Reference object.

    This is awaitable:

        doc = await doc.reference
    """
    document: Optional[Document] = None

    def __init__(self,
                 _id: ObjectId,
                 parent: Any,
                 document_class: Type[Document]) -> None:
        super().__init__(_id)
        self.parent = parent
        self.db = parent.__db__
        self.document_class = document_class

    def __repr__(self) -> str:
        n = self.__class__.__name__
        collection = self.document_class.__collection__
        status = '+' if self.document is not None else '-'
        return "{}({}:{} {})".format(n, collection, str(self), status)

    def __await__(self) -> Generator[Any, None, Any]:
        return self.get().__await__()

    async def get(self, force: bool = False) -> Optional[Document]:
        if self.document is None or force:
            self.document = await self.db(self.document_class).find_one(self)
            if self.document is None:  # pragma: no cover
                self.document = await self.db.get_document(self.document_class, self)

        return self.document
