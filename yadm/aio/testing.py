from __future__ import annotations

from collections import Counter
from types import GeneratorType, CoroutineType
from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar

import pymongo
from faker import Faker

from yadm.documents import BaseDocument, Document, EmbeddedDocument
from yadm.markers import AttributeNotSet
from yadm.testing import DEFAULT_DEPTH

if TYPE_CHECKING:
    from yadm.aio.database import AioDatabase
    from yadm.fields.base import DocumentLike

TB = TypeVar('TB', bound=BaseDocument)


async def aio_create_fake(__document_class__: Type[TB],
                          __db__: Optional[AioDatabase] = None,
                          __faker__: Optional[Faker] = None,
                          *,
                          __parent__: Optional[DocumentLike] = None,
                          __name__: Optional[str] = None,
                          __depth__: int = DEFAULT_DEPTH,
                          __write_concern__: pymongo.WriteConcern = pymongo.WriteConcern(w='majority'),
                          **values: Any) -> TB:
    if not issubclass(__document_class__, BaseDocument):  # pragma: no cover
        raise TypeError("only BaseDocument subclasses is allowed")

    aio_create_fake.counter[__document_class__] += 1  # type: ignore[attr-defined]

    if __depth__ < 0:
        return AttributeNotSet  # type: ignore[return-value]

    if __faker__ is None:
        aio_create_fake.counter['__without_faker__'] += 1  # type: ignore[attr-defined]
        __faker__ = Faker()

    document: Any = __document_class__()

    if isinstance(document, Document):
        document.__db__ = __db__
    elif isinstance(document, EmbeddedDocument):
        document.__parent__ = __parent__
        document.__name__ = __name__

    doc_fake_proc = document.__fake__(values, __faker__, __depth__ - 1)

    # extend values from __fake__ method
    if isinstance(doc_fake_proc, GeneratorType):
        values = next(doc_fake_proc)
    elif isinstance(doc_fake_proc, dict):
        values = doc_fake_proc

    # first: set values
    for name, fake in values.items():
        if fake is not AttributeNotSet:
            setattr(document, name, fake)

    # second: field faker
    for name, field in __document_class__.__fields__.items():
        if name not in values and not hasattr(document, '__fake__{}__'.format(name)):
            fake = field.get_fake(document, __faker__, __depth__ - 1)

            if isinstance(fake, CoroutineType):
                fake = await fake
            if fake is not AttributeNotSet:
                setattr(document, name, fake)

    # third: __fake__{name}__ methods
    for name, field in __document_class__.__fields__.items():
        if name not in values and hasattr(document, '__fake__{}__'.format(name)):
            attr = getattr(document, '__fake__{}__'.format(name))
            fake = attr(__faker__, __depth__ - 1)
            if isinstance(fake, CoroutineType):
                fake = await fake

            if fake is not AttributeNotSet:
                setattr(document, name, fake)

    if isinstance(doc_fake_proc, GeneratorType):
        # pre save processor
        try:
            next(doc_fake_proc)
        except StopIteration:
            doc_fake_proc = None

    if __db__ is not None:
        await __db__.insert_one(document, write_concern=__write_concern__)

        # post save processor
        if isinstance(doc_fake_proc, GeneratorType):
            try:
                next(doc_fake_proc)
            except StopIteration:
                pass

    return document


aio_create_fake.counter = Counter()  # type: ignore[attr-defined]
