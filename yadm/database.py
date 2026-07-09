"""
This module for provide work with MongoDB database.

.. code-block:: python

    import pymongo
    from yadm.database import Database

    from mydocs import Doc

    client = pymongo.MongoClient("localhost", 27017)
    db = Database(self.client, 'test')

    doc = Doc()
    db.insert_one(doc)

    doc.arg = 13
    db.save(doc)

    qs = db.get_queryset(Doc).find({'arg': {'$gt': 10}})
    for doc in qs:
        print(doc)
"""
from __future__ import annotations

import itertools
import warnings
from typing import Any, Iterable, Optional, Type

import pymongo
from pymongo.results import DeleteResult, InsertManyResult, InsertOneResult, UpdateResult
from bson import ObjectId

from yadm.documents import Document
from yadm.log_items import Insert, Save, UpdateOne, DeleteOne, Reload
from yadm.aggregation import Aggregator
from yadm.queryset import BaseQuerySet, QuerySet
from yadm.bulk_writer import BulkWriter, BATCH_SIZE as BULK_BATCH_SIZE
from yadm.serialize import to_mongo, from_mongo
from yadm.common import Projection, TDoc, build_update_query


RPS = pymongo.read_preferences


class BaseDatabase:  # pragma: no cover
    aio: Optional[bool] = None

    def __init__(self, client: Any, name: str, **database_params: Any) -> None:
        self.client = client
        self.name = name
        self.database_params = database_params
        self.db: Any = client.get_database(name, **database_params)

    def __repr__(self) -> str:  # pragma: no cover
        return '{}({!r})'.format(self.__class__.__name__, self.db)

    def __call__(self, document_class: Type[TDoc],
                 **params: Any) -> BaseQuerySet[TDoc]:
        return self.get_queryset(document_class, **params)

    def _get_collection(self, document_class: Any,
                        params: Optional[dict] = None) -> Any:
        """ Return pymongo collection for document class.
        """
        return self.db.get_collection(document_class.__collection__,
                                      **(params or {}))

    def insert_one(self, document: Document,
                   **collection_params: Any) -> Any:
        raise NotImplementedError

    def insert_many(self, documents: Iterable[Document],
                    **collection_params: Any) -> Any:
        raise NotImplementedError

    def save(self, document: Document, full: bool = False,
             upsert: bool = False, **collection_params: Any) -> Any:
        raise NotImplementedError

    def update_one(self, document: Document, *, reload: bool = True,
                   set: Optional[dict] = None,
                   unset: Any = None,
                   inc: Optional[dict] = None,
                   push: Optional[dict] = None,
                   pull: Optional[dict] = None,
                   **collection_params: Any) -> Any:
        raise NotImplementedError

    def delete_one(self, document: Document,
                   **collection_params: Any) -> Any:
        raise NotImplementedError

    def reload(self, document: Document, new_instance: bool = False, *,
               projection: Optional[Projection] = None,
               **collection_params: Any) -> Any:
        raise NotImplementedError

    def get_queryset(self, document_class: Type[TDoc], *,
                     projection: Optional[Projection] = None,
                     cache: Any = None,
                     **collection_params: Any) -> BaseQuerySet[TDoc]:
        raise NotImplementedError

    def get_document(self, document_class: Type[TDoc], _id: Any, *,
                     projection: Optional[Projection] = None,
                     exc: Optional[Type[BaseException]] = None,
                     read_preference: Any = RPS.PrimaryPreferred(),
                     **collection_params: Any) -> Any:
        raise NotImplementedError

    def estimated_document_count(self, document_class: Any,
                                 **collection_params: Any) -> Any:
        raise NotImplementedError

    def aggregate(self, document_class: Any, *,
                  pipeline: Any = None, **collection_params: Any) -> Any:
        raise NotImplementedError

    def bulk_write(self, document_class: Any, *,
                   ordered: bool = False, **collection_params: Any) -> Any:
        raise NotImplementedError


class Database(BaseDatabase):
    """ Main object who provide work with database.

    :param pymongo.Client client: database connection
    :param str name: database name
    """
    aio = False

    def insert_one(self, document: Document,
                   **collection_params: Any) -> InsertOneResult:
        """ Insert document to database.
        """
        document.__db__ = self
        collection = self._get_collection(document.__class__,
                                          collection_params)

        result = collection.insert_one(to_mongo(document))

        document._id = result.inserted_id
        document.__log__.append(Insert(id=result.inserted_id))
        return result

    def insert_many(self, documents: Iterable[Document], *,
                    ordered: bool = True,
                    **collection_params: Any) -> InsertManyResult:
        """ Insert documents from iterator.

        Collection get from first document.
        """
        def gen(documents: Iterable[Document]) -> Any:
            for document in documents:
                yield to_mongo(document)
                document.__log__.append(Insert())

        # TODO: rewrite this!
        if ordered:
            documents = list(documents)
            if documents:
                collection = self._get_collection(documents[0].__class__,
                                                  collection_params)

                result = collection.insert_many(
                    gen(documents),
                    ordered=True,
                )

                for _id, document in zip(result.inserted_ids, documents):
                    document.__db__ = self
                    document.id = _id

                return result
            else:
                return pymongo.results.InsertManyResult([], True)

        else:
            iterator = iter(documents)
            first = next(iterator)
            collection = self._get_collection(first.__class__,
                                              collection_params)

            return collection.insert_many(
                gen(itertools.chain([first], iterator)),
                ordered=False,
            )

    def save(self, document: TDoc,  # type: ignore[override]
             **collection_params: Any) -> TDoc:
        """ Save document to database.
        """
        document.__db__ = self
        if not hasattr(document, 'id'):
            document.id = ObjectId()

        raw = to_mongo(document)
        collection = self._get_collection(document, collection_params)
        raw_new = collection.find_one_and_replace(
            filter={'_id': document.id},
            replacement=raw,
            return_document=pymongo.collection.ReturnDocument.AFTER,
            upsert=True,
        )
        document.__raw__ = raw_new
        document.__log__.append(Save(id=document.id))
        return document

    def update_one(self, document: Document, *, reload: bool = True,
                   set: Optional[dict] = None,
                   unset: Any = None,
                   inc: Optional[dict] = None,
                   push: Optional[dict] = None,
                   pull: Optional[dict] = None,
                   **collection_params: Any,
                   ) -> Optional[UpdateResult]:  # TODO: extend
        """ Update one document.
        """
        update_data = build_update_query(set=set, unset=unset, inc=inc,
                                         push=push, pull=pull)

        if update_data:
            collection = self._get_collection(document, collection_params)
            result = collection.update_one(
                {'_id': document.id},
                update_data,
                upsert=False,
            )
            document.__log__.append(UpdateOne(update_data=update_data))
        else:
            result = None

        if reload:
            self.reload(document, **collection_params)

        return result

    def delete_one(self, document: Document,
                   **collection_params: Any) -> DeleteResult:
        """ Remove a single document from database.
        """
        collection = self._get_collection(document.__class__, collection_params)
        res = collection.delete_one({'_id': document._id})
        document.__log__.append(DeleteOne())
        return res

    def reload(self, document: TDoc, new_instance: bool = False, *,
               projection: Optional[Projection] = None,
               read_preference: Any = RPS.PrimaryPreferred(),
               **collection_params: Any) -> TDoc:
        """ Reload document.
        """
        new: Any
        collection_params['read_preference'] = read_preference
        qs = self.get_queryset(document.__class__,
                               projection=projection,
                               **collection_params)

        if projection is not None:
            new = qs.find_one(document.id, projection)
        else:
            new = qs.find_one(document.id)

        if new_instance:
            return new
        else:
            document.__raw__.clear()
            document.__raw__.update(new.__raw__)
            document.__cache__.clear()
            document.__log__.append(Reload())
            document.__not_loaded__ = new.__not_loaded__
            return document

    def get_document(self, document_class: Type[TDoc], _id: Any, *,
                     projection: Optional[Projection] = None,
                     exc: Optional[Type[BaseException]] = None,
                     read_preference: Any = RPS.PrimaryPreferred(),
                     **collection_params: Any) -> Optional[TDoc]:
        """ Get document for it _id.

        Default ReadPreference is PrimaryPreferred.
        """
        collection_params['read_preference'] = read_preference
        col = self.db.get_collection(document_class.__collection__,
                                     **collection_params)

        if projection is None:
            projection = document_class.__default_projection__

        if projection is not None:
            raw = col.find_one({'_id': _id}, projection)
            not_loaded = [k for k, v in projection.items() if not v]
        else:
            raw = col.find_one({'_id': _id})
            not_loaded = []

        if raw:
            doc = from_mongo(document_class, raw, not_loaded=not_loaded)
            doc.__db__ = self
            return doc

        elif exc is not None:
            raise exc((document_class, _id, collection_params))
        else:
            return None

    def get_queryset(self, document_class: Type[TDoc], *,
                     projection: Optional[Projection] = None,
                     cache: Any = None,
                     **collection_params: Any) -> QuerySet[TDoc]:
        """ Return queryset for document class.

        This create instance of :class:`yadm.queryset.QuerySet`
        with presetted document's collection information.
        """
        if projection is None:
            projection = document_class.__default_projection__

        return QuerySet(self, document_class,
                        projection=projection,
                        cache=cache,
                        collection_params=collection_params)

    def estimated_document_count(self, document_class: Any,
                                 **collection_params: Any) -> int:
        """ Get an estimate of the number of documents in this collection.
        """
        collection = self._get_collection(document_class, collection_params)
        return collection.estimated_document_count()

    def aggregate(self, document_class: Any, *,
                  pipeline: Any = None,
                  **collection_params: Any) -> Aggregator:
        """ Return aggregator for use aggregation framework.

        :param document_class: :class:`yadm.documents.Document`
        :param list pipeline: initial pipeline
        :param **collection_params: params for get_collection
        """
        return Aggregator(self, document_class, pipeline=pipeline,
                          collection_params=collection_params)

    def bulk_write(self, document_class: Any, *,
                   ordered: bool = False,
                   batch_size: int = BULK_BATCH_SIZE,
                   **collection_params: Any) -> BulkWriter:
        """ Return BulkWriter for realize bulk_write from pymongo.
        """
        return BulkWriter(self, document_class,
                          ordered=ordered, batch_size=batch_size,
                          collection_params=collection_params)

    def insert(self, document: Document,
               **collection_params: Any) -> Document:  # pragma: no cover
        warnings.warn("Use insert_one!", DeprecationWarning)
        self.insert_one(document, **collection_params)
        return document

    def remove(self, document: Document,
               **collection_params: Any) -> Any:  # pragma: no cover
        warnings.warn("Use delete_one!", DeprecationWarning)
        return self.delete_one(document, **collection_params)
