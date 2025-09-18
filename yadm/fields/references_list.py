""" Field for list with references.

Usage:

    class Doc(Document):
        refs = ReferencesListField(RefDoc)


    doc = db(Doc).find_one(...)
    doc.ref.resolve()  # resolve all documents with one query
    for ref_doc in doc.ref:
        ...

With asyncio::

    await doc.ref.resolve()

ReferencesList behaves like a mutable sequence, but without resolving a
NotResolved error is raised for any actions with it (except ``__len__`` and
``__bool__``).

"""
from __future__ import annotations

from collections.abc import MutableSequence
from dataclasses import dataclass
from typing import (
    Any,
    Coroutine,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Union,
    overload,
)

from bson import ObjectId

from yadm.documents import BaseDocument, Document, MetaDocument
from yadm.document_item import DocumentItemMixin
from yadm.fields.base import Field
from yadm.queryset import NotFoundBehavior


class NotResolved(Exception):
    pass


class AlreadyResolved(Exception):
    pass


@dataclass(frozen=True)
class ReferencesListSetitem:
    index: int
    document: Document
    op: str = 'references_list_setitem'


@dataclass(frozen=True)
class ReferencesListDelitem:
    index: int
    op: str = 'references_list_delitem'


@dataclass(frozen=True)
class ReferencesListInsert:
    index: int
    document: Document
    op: str = 'references_list_insert'


@dataclass(frozen=True)
class ReferencesListAppend:
    document: Document
    op: str = 'references_list_append'


@dataclass(frozen=True)
class ReferencesListPop:
    index: int
    op: str = 'references_list_pop'


@dataclass(frozen=True)
class ReferencesListResolve:
    op: str = 'references_list_resolve'


class ReferencesList(MutableSequence[Document], DocumentItemMixin):
    _resolved: bool
    _reference_document_class: MetaDocument
    _field: Optional[Field]
    _ids: List[ObjectId]
    _documents: List[Document]

    def __init__(
        self,
        reference_document_class: MetaDocument,
        ids: Optional[List[ObjectId]] = None,
        field: Optional[Field] = None,
        parent: Union[BaseDocument, DocumentItemMixin, None] = None,
    ) -> None:
        super().__init__()
        self._reference_document_class = reference_document_class
        self.__parent__ = parent
        self._field = field
        self._ids = list(ids or [])
        self._documents = []
        self._resolved = not ids

    def __repr__(self) -> str:
        if self._resolved:
            items = ', '.join([repr(d) for d in self._documents])
        else:
            items = ', '.join([str(i) for i in self._ids])

        if len(items) > 200:  # pragma: nocover
            items = items[:75] + ' ... ' + items[-75:]

        return "{cname}({rdc} {resolved} {len} [{items}])".format(
            cname=self.__class__.__name__,
            rdc=self._reference_document_class.__name__,
            resolved='resolved' if self.resolved else '',
            len=len(self),
            items=items,
        )

    @overload
    def __getitem__(self, idx: int) -> Document:
        ...

    @overload
    def __getitem__(self, idx: slice) -> List[Document]:
        ...

    def __getitem__(self, idx: Union[int, slice]) -> Union[Document, List[Document]]:
        self._check_resolved_and_rise()
        return self._documents[idx]

    @overload
    def __setitem__(self, idx: int, document: Document) -> None:
        ...

    @overload
    def __setitem__(self, idx: slice, documents: Iterable[Document]) -> None:
        ...

    def __setitem__(self, idx: Union[int, slice], document: Union[Document, Iterable[Document]]) -> None:
        self._check_resolved_and_rise()
        if isinstance(idx, slice):
            docs = list(document if isinstance(document, Iterable) else [document])
            self._ids[idx] = [doc.id for doc in docs]
            self._documents[idx] = docs
            start_index = 0 if idx.start is None else idx.start
            for offset, doc in enumerate(docs):
                self.__log__.append(ReferencesListSetitem(index=start_index + offset,
                                                          document=doc))
        else:
            if not isinstance(document, Document):
                raise TypeError('document must be a Document instance')
            self._ids[idx] = document.id
            self._documents[idx] = document
            self.__log__.append(ReferencesListSetitem(index=idx, document=document))

    @overload
    def __delitem__(self, idx: int) -> None:
        ...

    @overload
    def __delitem__(self, idx: slice) -> None:
        ...

    def __delitem__(self, idx: Union[int, slice]) -> None:
        self._check_resolved_and_rise()
        if isinstance(idx, slice):
            start, stop, step = idx.indices(len(self._ids))
            range_indices = list(range(start, stop, step))
            for i in reversed(range_indices):
                del self._ids[i]
                del self._documents[i]
                self.__log__.append(ReferencesListDelitem(index=i))
        else:
            del self._ids[idx]
            del self._documents[idx]
            self.__log__.append(ReferencesListDelitem(index=idx))

    def __len__(self) -> int:
        return len(self._ids)

    def __bool__(self) -> bool:
        return bool(self._ids)

    def __iter__(self) -> Iterator[Document]:
        self._check_resolved_and_rise()
        return iter(self._documents)

    def __eq__(self, other: object) -> bool:  # pragma: nocover
        if isinstance(other, ReferencesList):
            return self._ids == other._ids
        else:
            return NotImplemented

    @property
    def resolved(self) -> bool:
        return self._resolved

    @property
    def ids(self) -> List[ObjectId]:
        return self._ids.copy()

    def insert(self, idx: int, document: Document):
        self._check_resolved_and_rise()
        self._ids.insert(idx, document.id)
        self._documents.insert(idx, document)
        self.__log__.append(ReferencesListInsert(index=idx, document=document))

    def append(self, document: Document):
        self._check_resolved_and_rise()
        self._ids.append(document.id)
        self._documents.append(document)
        self.__log__.append(ReferencesListAppend(document=document))

    def pop(self, idx: int=-1) -> Document:
        self._check_resolved_and_rise()
        del self._ids[idx]
        doc = self._documents.pop(idx)
        self.__log__.append(ReferencesListPop(index=idx))
        return doc

    def resolve(self) -> Optional[Coroutine[Any, Any, None]]:
        """ Resolve ids to documents.

        This method can be used with "await" if AioDatabase.
        """
        if self._resolved:
            raise AlreadyResolved()

        db = self.__db__
        if db is None:
            raise NotResolved()
        qs = db.get_queryset(self._reference_document_class)

        if not db.aio:
            self._documents = list(qs.find_in(
                self._ids,
                not_found=NotFoundBehavior.NONE
            ))
            self._resolved = True
            self.__log__.append(ReferencesListResolve())

        else:
            async def resolver_coro(self: 'ReferencesList') -> None:
                documents: List[Document] = []
                async for doc in qs.find_in(self._ids):
                    documents.append(doc)

                self._documents = documents
                self._resolved = True
                self.__log__.append(ReferencesListResolve())

            return resolver_coro(self)

        return None

    def _check_resolved_and_rise(self):
        if not self._resolved:
            raise NotResolved()


class ReferencesListField(Field):
    def __init__(self, reference_document_class: MetaDocument):
        self._reference_document_class = reference_document_class

    def copy(self) -> 'ReferencesListField':  # pragma: no cover
        return self.__class__(self._reference_document_class)

    def get_if_attribute_not_set(
        self,
        document: Document,
    ) -> ReferencesList:  # pragma: no cover
        rl = ReferencesList(
            self._reference_document_class,
            [],
            field=self,
            parent=document,
        )
        if self.name is None:
            raise AttributeError('Field name is not set')
        setattr(document, self.name, rl)
        return rl

    def get_default(self, document: Document) -> ReferencesList:
        rl = ReferencesList(
            self._reference_document_class,
            [],
            field=self,
            parent=document,
        )
        if self.name is None:
            raise AttributeError('Field name is not set')
        setattr(document, self.name, rl)
        return rl

    def prepare_value(
        self,
        document: Document,
        value: Union[ReferencesList, List[Document]],
    ) -> ReferencesList:
        if isinstance(value, ReferencesList):
            value._field = self
            value.__parent__ = document
            return value

        elif isinstance(value, list):
            ids = [i.id for i in value]
            res = ReferencesList(
                self._reference_document_class, ids,
                field=self,
                parent=document,
            )
            res._resolved = True
            res._documents = list(value)
            return res

        else:  # pragma: no cover
            raise TypeError(value)

    def from_mongo(
        self,
        document: Document,
        value: List[ObjectId],
    ) -> ReferencesList:
        return ReferencesList(
            self._reference_document_class, value,
            field=self,
            parent=document,
        )

    def to_mongo(self,
                 document: Document,
                 value: ReferencesList) -> List[ObjectId]:
        return value._ids
