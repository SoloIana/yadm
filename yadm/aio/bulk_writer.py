from __future__ import annotations

import functools
from typing import Any, List, Optional

from pymongo import (
    InsertOne,
    UpdateOne,
    UpdateMany,
    ReplaceOne,
    DeleteOne,
    DeleteMany,
)
from pymongo.results import BulkWriteResult

from yadm.bulk_writer import EMPTY_RESULT, BATCH_SIZE
from yadm.serialize import to_mongo


def _async_check_and_send(meth: Any) -> Any:
    @functools.wraps(meth)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
        meth(self, *args, **kwargs)
        if len(self._batch) >= self._batch_size:
            await self.send_batch()

    return wrapper


class AioBulkWriter:
    def __init__(self, db: Any, document_class: Any,
                 ordered: bool = False,
                 collection_params: Optional[dict] = None,
                 batch_size: int = BATCH_SIZE) -> None:
        self._db = db
        self._document_class = document_class
        self._ordered = ordered
        self._collection_params = collection_params
        self._batch_size = batch_size

        self._batch: List[Any] = []
        self._result = EMPTY_RESULT

    async def __aenter__(self) -> AioBulkWriter:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._batch:
            await self.send_batch()

    async def send_batch(self) -> None:
        data, self._batch = self._batch, []
        col = self._db._get_collection(self._document_class,
                                       self._collection_params)
        result = await col.bulk_write(data, ordered=self._ordered)
        self._result = _union_results(self._result, result)

    @property
    def result(self) -> BulkWriteResult:
        return self._result

    @_async_check_and_send
    def insert_one(self, document: Any) -> Any:
        self._batch.append(InsertOne(to_mongo(document)))

    @_async_check_and_send
    def update_one(self, cliteria: Any, query: Any, upsert: bool = False) -> Any:
        self._batch.append(UpdateOne(cliteria, query, upsert=upsert))

    @_async_check_and_send
    def update_many(self, cliteria: Any, query: Any, upsert: bool = False) -> Any:
        self._batch.append(UpdateMany(cliteria, query, upsert=upsert))

    @_async_check_and_send
    def replace_one(self, cliteria: Any, document: Any, upsert: bool = False) -> Any:
        self._batch.append(ReplaceOne(cliteria, to_mongo(document), upsert=upsert))

    @_async_check_and_send
    def delete_one(self, cliteria: Any) -> Any:
        self._batch.append(DeleteOne(cliteria))

    @_async_check_and_send
    def delete_many(self, cliteria: Any) -> Any:
        self._batch.append(DeleteMany(cliteria))

    async def replace(self, document: Any) -> None:
        await self.replace_one({'_id': document.id}, document)

    async def delete(self, document: Any) -> None:
        await self.delete_one({'_id': document.id})


def _union_results(first: BulkWriteResult,
                   second: BulkWriteResult) -> BulkWriteResult:
    acknowledged = first.acknowledged and second.acknowledged

    bulk_api_result = {
        'nInserted': _sum_ints(first, second, 'nInserted'),
        'nMatched': _sum_ints(first, second, 'nMatched'),
        'nModified': _sum_ints(first, second, 'nModified'),
        'nRemoved': _sum_ints(first, second, 'nRemoved'),
        'nUpserted': _sum_ints(first, second, 'nUpserted'),
        'upserted': (first.bulk_api_result['upserted'] +
                     second.bulk_api_result['upserted'])
    }
    return BulkWriteResult(bulk_api_result, acknowledged)


def _sum_ints(first: BulkWriteResult, second: BulkWriteResult,
              key: str) -> int:
    return ((first.bulk_api_result.get(key, 0) or 0) +
            (second.bulk_api_result.get(key, 0) or 0))
