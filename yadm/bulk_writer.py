from __future__ import annotations

import functools
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    Type,
    TypeVar,
    cast,
)

from pymongo import (
    InsertOne,
    UpdateOne,
    UpdateMany,
    ReplaceOne,
    DeleteOne,
    DeleteMany,
)
from pymongo.results import BulkWriteResult

from .common import Criteria
from .serialize import to_mongo

if TYPE_CHECKING:
    from yadm.database import BaseDatabase
    from yadm.documents import Document

_F = TypeVar('_F', bound=Callable[..., Any])

BATCH_SIZE = 1000

EMPTY_RESULT = BulkWriteResult(
    bulk_api_result={
        'nInserted': 0,
        'nMatched': 0,
        'nModified': 0,
        'nRemoved': 0,
        'nUpserted': 0,
        'upserted': []
    },
    acknowledged=True,
)


def _check_and_send(meth: _F) -> _F:
    @functools.wraps(meth)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
        meth(self, *args, **kwargs)
        if len(self._batch) >= self._batch_size:
            self.send_batch()

    return cast('_F', wrapper)


class BulkWriter:
    def __init__(self, db: BaseDatabase, document_class: Type[Document],
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

    def __enter__(self) -> BulkWriter:
        return self

    def __exit__(self,
                 exc_type: Optional[Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]) -> None:
        if self._batch:
            self.send_batch()

    def send_batch(self) -> None:
        data, self._batch = self._batch, []
        col = self._db._get_collection(self._document_class,
                                       self._collection_params)
        result = col.bulk_write(data, ordered=self._ordered)
        self._result = _union_results(self._result, result)

    @property
    def result(self) -> BulkWriteResult:
        return self._result

    @_check_and_send
    def insert_one(self, document: Document) -> None:
        self._batch.append(InsertOne(to_mongo(document)))

    @_check_and_send
    def update_one(self, cliteria: Criteria, query: Criteria, upsert: bool = False) -> None:
        self._batch.append(UpdateOne(cliteria, query, upsert=upsert))

    @_check_and_send
    def update_many(self, cliteria: Criteria, query: Criteria, upsert: bool = False) -> None:
        self._batch.append(UpdateMany(cliteria, query, upsert=upsert))

    @_check_and_send
    def replace_one(self, cliteria: Criteria, document: Document, upsert: bool = False) -> None:
        self._batch.append(ReplaceOne(cliteria, to_mongo(document), upsert=upsert))

    @_check_and_send
    def delete_one(self, cliteria: Criteria) -> None:
        self._batch.append(DeleteOne(cliteria))

    @_check_and_send
    def delete_many(self, cliteria: Criteria) -> None:
        self._batch.append(DeleteMany(cliteria))

    def replace(self, document: Document) -> None:
        self.replace_one({'_id': document.id}, document)

    def delete(self, document: Document) -> None:
        self.delete_one({'_id': document.id})


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
