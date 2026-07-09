from __future__ import annotations

from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterable,
    List,
    Optional,
    Type,
    Union,
)

from pymongo import ReturnDocument
from pymongo.results import DeleteResult, UpdateResult
from bson import ObjectId

from yadm.common import Criteria, Projection, TDoc
from yadm.queryset import BaseQuerySet, NotFoundBehavior, NotFoundError
from yadm.serialize import to_mongo


class AioQuerySet(BaseQuerySet[TDoc]):
    async def __aiter__(self) -> AsyncIterator[TDoc]:
        async for raw in self._cursor:
            yield self._from_mongo_one(raw)

    async def _get_one(self, index: int) -> TDoc:
        cursor = self._cursor.skip(index).limit(1)
        try:
            raw = await cursor.__anext__()
        except StopAsyncIteration:
            raise IndexError(index)
        finally:
            await cursor.close()

        return self._from_mongo_one(raw)

    async def find_one(self,
                       criteria: Union[Criteria, ObjectId, None] = None,
                       projection: Optional[Projection] = None, *,
                       exc: Optional[Type[BaseException]] = None,
                       ) -> Optional[TDoc]:
        if isinstance(criteria, ObjectId):
            criteria = {'_id': criteria}

        qs = self.find(criteria=criteria, projection=projection)
        data = await self._collection.find_one(qs._criteria, qs._projection)

        if data is None:
            if exc is not None:
                raise exc(criteria)
            else:
                return None

        return self._from_mongo_one(data, projection=qs._projection)

    async def update_one(self, update: Criteria, *,
                         upsert: bool = False) -> UpdateResult:
        return await self._collection.update_one(
            self._criteria,
            update,
            upsert=upsert,
        )

    async def update_many(self, update: Criteria, *,
                          upsert: bool = False) -> UpdateResult:
        return await self._collection.update_many(
            self._criteria,
            update,
            upsert=upsert,
        )

    async def delete_one(self) -> DeleteResult:
        return await self._collection.delete_one(self._criteria)

    async def delete_many(self) -> DeleteResult:
        return await self._collection.delete_many(self._criteria)

    async def find_one_and_update(self, update: Criteria, *,
                                  upsert: bool = False,
                                  return_document: bool = ReturnDocument.BEFORE,
                                  ) -> Optional[TDoc]:
        """ Find a single document and update it.
        """
        data = await self._collection.find_one_and_update(
            filter=self._criteria,
            projection=self._projection,
            update=update,
            upsert=upsert,
            sort=self._sort,
            return_document=return_document,
        )
        if data is None:  # pragma: no cover
            return None

        return self._from_mongo_one(data, projection=self._projection)

    async def find_one_and_replace(self, document: TDoc, *,
                                   return_document: bool = ReturnDocument.BEFORE,
                                   ) -> Optional[TDoc]:
        """ Find a single document and replace it.
        """
        data = await self._collection.find_one_and_replace(
            filter=self._criteria,
            projection=self._projection,
            replacement=to_mongo(document),
            sort=self._sort,
            return_document=return_document,
        )
        if data is None:  # pragma: no cover
            return None

        return self._from_mongo_one(data, projection=self._projection)

    async def find_one_and_delete(self) -> Optional[TDoc]:
        """ Find a single document and delete it.
        """
        data = await self._collection.find_one_and_delete(
            filter=self._criteria,
            projection=self._projection,
            sort=self._sort,
        )
        if data is None:  # pragma: no cover
            return None

        return self._from_mongo_one(data, projection=self._projection)

    async def count_documents(self) -> int:
        kwargs = {}
        if self._hint is not None:
            kwargs['hint'] = self._hint

        if self._comment is not None:
            kwargs['comment'] = self._comment

        return await self._collection.count_documents(self._criteria, **kwargs)

    async def distinct(self, field: str) -> List[Any]:
        return await self._cursor.distinct(field)

    async def ids(self) -> AsyncIterator[ObjectId]:
        async for raw in self.copy(projection={'_id': True})._cursor:
            yield raw['_id']

    async def bulk(self) -> Dict[ObjectId, TDoc]:
        qs = self.copy()
        qs._sort = None
        return {obj.id: obj async for obj in qs}  # type: ignore[misc]

    async def join(self, *field_names: str) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def find_in(self, comparable: Iterable[Any], field: str = '_id', *,
                      not_found: Union[NotFoundBehavior, str] = NotFoundBehavior.SKIP,
                      ) -> AsyncIterator[Optional[TDoc]]:
        not_found = NotFoundBehavior(not_found)
        hash_docs = {}

        async for doc in self.find({field: {'$in': comparable}}):
            key = getattr(doc, field)
            if key not in hash_docs:
                hash_docs[key] = doc

        for cmp_item in comparable:
            value = hash_docs.get(cmp_item)

            if not_found is NotFoundBehavior.NONE:
                yield value

            elif not_found is NotFoundBehavior.SKIP:
                if value is not None:
                    yield value

            elif not_found is NotFoundBehavior.ERROR:
                if value is not None:
                    yield value
                else:
                    raise NotFoundError("Could not find a document with"
                                        " the field '{}' equal '{}'"
                                        "".format(field, cmp_item))
