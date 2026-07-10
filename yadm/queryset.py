from __future__ import annotations

import warnings
from collections import OrderedDict
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    Union,
    overload,
)

from pymongo import read_preferences, ReturnDocument
from pymongo.results import DeleteResult, UpdateResult
from bson import ObjectId

from yadm.common import (
    Criteria,
    Hint,
    Pipeline,
    Projection,
    ReadPref,
    Sort,
    SortItem,
    TDoc,
)
from yadm.join import Join
from yadm.cache import StackCache
from yadm.serialize import from_mongo, to_mongo, LOOKUPS_KEY, TRaw

if TYPE_CHECKING:
    from typing import Self

    from yadm.database import BaseDatabase
    from yadm.documents import Document

CACHE_SIZE = 100

_Primary = read_preferences.Primary()
_PrimaryPreferred = read_preferences.PrimaryPreferred()


class NotFoundBehavior(Enum):
    NONE = 'none'
    SKIP = 'skip'
    ERROR = 'error'


class NotFoundError(Exception):
    pass


class BaseQuerySet(Generic[TDoc]):
    """ Query builder.
    """
    def __init__(self, db: BaseDatabase, document_class: Type[TDoc], *,
                 cache: Any = None,
                 criteria: Optional[Criteria] = None,
                 projection: Optional[Projection] = None,
                 hint: Optional[Hint] = None,
                 sort: Optional[Sort] = None,
                 comment: Optional[str] = None,
                 lookup: Any = None,
                 slice: Optional[slice] = None,
                 batch_size: Optional[int] = None,
                 collection_params: Optional[dict] = None):

        self._db = db
        self._document_class = document_class
        self._cache = cache
        self._criteria = criteria or {}
        self._projection = projection
        self._hint = hint
        self._comment = comment
        self._sort = sort
        self._lookup = lookup or frozenset()
        self._slice = slice
        self._batch_size = batch_size
        self._collection_params = collection_params or {}

    def __repr__(self) -> str:
        return ("{s.__class__.__name__}({s._document_class.__collection__}"
                " {s._criteria!r} {s._projection!r} {s._hint!r} {s._comment!r}"
                " {s._sort!r})".format(s=self))

    def __call__(self,
                 criteria: Optional[Criteria] = None,
                 projection: Optional[Projection] = None,
                 ) -> Self:  # pragma: no cover
        return self.find(criteria, projection)

    @overload
    def __getitem__(self, item: int) -> Any: ...
    @overload
    def __getitem__(self, item: slice) -> Self: ...

    def __getitem__(self, item: Union[int, slice]) -> Any:
        if isinstance(item, slice):
            if item.step is not None:
                n = self.__class__.__name__
                raise TypeError("{} not support slicing with step".format(n))

            elif (item.start and item.start < 0) or (item.stop and item.stop < 0):
                n = self.__class__.__name__
                raise TypeError("{} not support negative slicing".format(n))

            return self.copy(slice=item)

        elif isinstance(item, int):
            return self._get_one(item)

        else:
            raise TypeError("Only slice or int accepted, but {}"
                            "".format(item.__class__))

    def _from_mongo_one(self, data: Optional[TRaw], *,
                        projection: Optional[Projection] = None) -> Any:
        """ Create document from raw data.
        """
        projection = projection or self._projection

        if data is None:  # pragma: no cover
            return None
        elif not projection:
            not_loaded: frozenset = frozenset()
        else:
            include = [f for f, v in projection.items() if v]
            exclude = {f for f, v in projection.items() if not v}

            if include:
                if exclude and exclude != {'_id'}:  # pragma: no cover
                    raise ValueError("projection cannot have a mix"
                                     " of inclusion and exclusion")

                for field_name in self._document_class.__fields__:
                    if field_name not in include and field_name != '_id':
                        exclude.add(field_name)

            not_loaded = frozenset(exclude)

        doc = from_mongo(self._document_class, data, not_loaded)
        doc.__db__ = self._db
        doc.__qs__ = self
        return doc

    @property
    def _collection(self) -> Any:  # noqa
        """ pymongo collection.
        """
        return self._db._get_collection(self._document_class,
                                        params=self._collection_params)

    @property
    def _cursor(self) -> Any:
        """ Raw cursor with parameters from queryset.
        """
        if not self._lookup:
            return self._get_cursor_find(
                self._collection,
                self._criteria,
                self._projection or None,
                self._hint,
                self._comment,
                self._sort,
                self._slice,
                self._batch_size,
            )
        else:
            if self._hint is not None:  # pragma: no cover
                raise NotImplementedError(
                    "hint() is not implemented for lookup queries")

            return self._get_cursor_aggregation(
                self._collection,
                self._criteria,
                self._projection or None,
                self._comment,
                self._sort,
                self._lookup,
                self._slice,
                self._batch_size,
            )

    @staticmethod
    def _get_cursor_find(collection: Any, criteria: Criteria,
                         projection: Optional[Projection],
                         hint: Optional[Hint], comment: Optional[str],
                         sort: Optional[Sort], slice: Optional[slice],
                         batch_size: Optional[int]) -> Any:
        cursor = collection.find(criteria, projection)

        if hint is not None:
            cursor = cursor.hint(hint)

        if comment is not None:
            cursor = cursor.comment(comment)

        if sort is not None:
            cursor = cursor.sort(sort)

        if slice is not None:
            if slice.start:
                cursor = cursor.skip(slice.start)

            if slice.stop:
                cursor = cursor.limit(slice.stop - (slice.start or 0))

        if batch_size is not None:
            cursor = cursor.batch_size(batch_size)

        return cursor

    @staticmethod
    def _get_cursor_aggregation(collection: Any, criteria: Criteria,
                                projection: Optional[Projection],
                                comment: Optional[str], sort: Optional[Sort],
                                lookup: Iterable[Tuple[str, str]],
                                slice: Optional[slice],
                                batch_size: Optional[int]) -> Any:
        pipeline: Pipeline = []

        if criteria:
            pipeline.append({'$match': criteria})

        if projection:
            pipeline.append({'$project': projection})

        for collection_name, field_name in lookup:
            pipeline.extend([
                {'$lookup': {'from': collection_name,
                             'localField': field_name,
                             'foreignField': '_id',
                             'as': f'{LOOKUPS_KEY}.{field_name}'}},
                {'$unwind': f'${LOOKUPS_KEY}.{field_name}'},
            ])

        if sort:
            pipeline.append({'$sort': OrderedDict(sort)})

        kwargs = {}
        if comment:
            kwargs['comment'] = comment

        cursor = collection.aggregate(pipeline, **kwargs)

        if batch_size is not None:
            cursor = cursor.batch_size(batch_size)

        return cursor

    @property
    def cache(self) -> Any:
        """ Queryset cache object.
        """
        if self._cache is None:
            self._cache = StackCache(size=CACHE_SIZE)

        return self._cache

    def copy(self, *, cache: Any = None,
             criteria: Optional[Criteria] = None,
             projection: Optional[Projection] = None,
             hint: Optional[Hint] = None,
             comment: Optional[str] = None,
             sort: Optional[Sort] = None,
             lookup: Any = None,
             slice: Optional[slice] = None,
             batch_size: Optional[int] = None,
             collection_params: Optional[dict] = None) -> Self:
        """ Copy queryset with new parameters.

        Only keywords arguments is alowed.
        Parameters simply replaced with given arguments.
        """
        return self.__class__(
            self._db, self._document_class,
            cache=cache or self._cache,
            criteria=criteria or self._criteria,
            projection=projection or self._projection,
            hint=hint or self._hint,
            comment=comment or self._comment,
            sort=sort or self._sort,
            lookup=lookup or self._lookup,
            slice=slice or self._slice,
            batch_size=batch_size or self._batch_size,
            collection_params=collection_params or self._collection_params,
        )

    def read_preference(self, read_preference: ReadPref) -> Self:
        """ Setup readPreference.

        Return new QuerySet instance.

        Deprecated since 1.4.0.
        Use `collection_params` argument in `copy`.
        """
        collection_params = (self._collection_params or {}).copy()
        collection_params['read_preference'] = read_preference
        return self.copy(collection_params=collection_params)

    def read_primary(self, preferred: bool = False) -> Self:
        """ Return queryset with setupd read concern for primary.

        If `preferred` argument is `True`, `PrimaryPreferred` is used
        else `Primary`.
        """
        collection_params = (self._collection_params or {}).copy()

        if not preferred:
            collection_params['read_preference'] = _Primary
        else:
            collection_params['read_preference'] = _PrimaryPreferred

        return self.copy(collection_params=collection_params)

    def find(self,
             criteria: Optional[Criteria] = None,
             projection: Optional[Projection] = None) -> Self:
        """ Return queryset copy with new criteria and projection.

        :param dict criteria: update queryset's criteria
        :param dict projection: set queryset's projection
        :return: new :class:`yadm.queryset.QuerySet`

        .. code:: python

            qs({'field': {'$gt': 3}}, {'field': True})
        """
        if criteria is not None:
            if not self._criteria:
                criteria_new = criteria
            elif set(self._criteria) & set(criteria):
                criteria_new = {'$and': [self._criteria, criteria]}
            else:
                criteria_new = self._criteria.copy()
                criteria_new.update(criteria)
        else:
            criteria_new = None

        if projection is not None:
            projection_new = projection
        elif self._projection is not None:
            projection_new = self._projection.copy()
        else:
            projection_new = None

        return self.copy(criteria=criteria_new, projection=projection_new)

    def fields(self, *fields: str) -> Self:
        """ Get only setted fields.

        Update projection with fields.

        :param str fields:
        :return: new :class:`yadm.queryset.QuerySet`

        .. code:: python

            qs('field', 'field2')
        """
        return self.find(projection=dict.fromkeys(fields, True))

    def fields_all(self) -> Self:
        """ Clear projection.
        """
        qs = self.copy()
        qs._projection = None
        return qs

    def hint(self, index: Union[str, List[SortItem]]) -> Self:
        """ Return queryset with hinting.

            qs = qs.hint([('field', 1)])
        """
        return self.copy(hint=index)

    def comment(self, comment: str) -> Self:
        """ Return queryset with commenting.

            qs = qs.comment('qwerty')
        """
        return self.copy(comment=comment)

    def sort(self, *sort: SortItem) -> Self:
        """ Return queryset with sorting.

            qs = qs.sort(('field_1', 1), ('field_2', -1))
        """
        sort_list = list(sort)

        if self._sort is None:
            return self.copy(sort=sort_list)
        else:
            return self.copy(sort=self._sort + sort_list)

    def lookup(self, *fields: str) -> Self:
        items = set()

        for field_name in fields:
            if field_name in self._document_class.__fields__:
                field = self._document_class.__fields__[field_name]
                if hasattr(field, 'reference_document_class'):
                    col_name = field.reference_document_class.__collection__
                    items.add((col_name, field_name))
                else:  # pragma: no cover
                    raise ValueError(f"Field {field_name!r} is not a ReferenceField")
            else:  # pragma: no cover
                raise ValueError(f"Field {field_name!r}"
                                 f" not found in {self._document_class!r}")

        return self.copy(lookup=(self._lookup | items))

    def batch_size(self, batch_size: Optional[int]) -> Self:
        """ Setup batch size to cursor for this queryset.
        """
        if batch_size is not None:
            return self.copy(batch_size=batch_size)
        else:
            qs = self.copy()
            qs._batch_size = None
            return qs

    def _get_one(self, index: int) -> Any:
        raise NotImplementedError  # pragma: no cover

    def __iter__(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def __contains__(self, document: Document) -> Any:
        raise NotImplementedError  # pragma: no cover

    def __bool__(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def find_one(self,
                 criteria: Union[Criteria, ObjectId, None] = None,
                 projection: Optional[Projection] = None, *,
                 exc: Optional[Type[BaseException]] = None) -> Any:
        raise NotImplementedError  # pragma: no cover

    def update_many(self, update: Criteria, *, upsert: bool = False) -> Any:
        raise NotImplementedError  # pragma: no cover

    def update_one(self, update: Criteria, *, upsert: bool = False) -> Any:
        raise NotImplementedError  # pragma: no cover

    def delete_one(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def delete_many(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def find_one_and_update(self, update: Criteria, *,
                            return_document: bool = ReturnDocument.BEFORE,
                            ) -> Any:
        raise NotImplementedError  # pragma: no cover

    def find_one_and_replace(self, document: TDoc, *,
                             return_document: bool = ReturnDocument.BEFORE,
                             ) -> Any:
        raise NotImplementedError  # pragma: no cover

    def find_one_and_delete(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def count(self) -> Any:  # pragma: no cover
        warnings.warn("Use count_documents!", DeprecationWarning)
        return self.count_documents()

    def count_documents(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def distinct(self, field: str) -> Any:
        raise NotImplementedError  # pragma: no cover

    def ids(self) -> Any:
        raise NotImplementedError  # pragma: no cover

    def join(self, *field_names: str) -> Any:
        raise NotImplementedError  # pragma: no cover

    def find_in(self, comparable: Iterable[Any], field: str = '_id', *,
                not_found: Union[NotFoundBehavior, str] = NotFoundBehavior.SKIP,
                ) -> Any:
        raise NotImplementedError  # pragma: no cover


class QuerySet(BaseQuerySet[TDoc]):
    def __iter__(self) -> Iterator[TDoc]:
        for raw in self._cursor:
            yield self._from_mongo_one(raw)

    def __len__(self) -> int:
        return self.count_documents()

    def __contains__(self, document: Document) -> bool:
        return self.find_one(document.id) is not None

    def __bool__(self) -> bool:
        qs = self.copy(sort=[], projection={'_id': True})
        return qs.find_one() is not None

    def _get_one(self, index: int) -> TDoc:
        return self._from_mongo_one(self._cursor[index])

    def find_one(self,
                 criteria: Union[Criteria, ObjectId, None] = None,
                 projection: Optional[Projection] = None, *,
                 exc: Optional[Type[BaseException]] = None,
                 ) -> Optional[TDoc]:
        """ Find and return only one document.

        :param dict criteria: update queryset's criteria
        :param dict projection: update queryset's projection
        :param Exception exc: raise given exception if not found
        :return: :class:`yadm.documents.Document` or **None**

        .. code:: python

            qs({'field': {'$gt': 3}}, {'field': True})
        """
        if isinstance(criteria, ObjectId):
            criteria = {'_id': criteria}

        qs = self.find(criteria=criteria, projection=projection)
        data = self._collection.find_one(qs._criteria, qs._projection)

        if data is None:
            if exc is not None:
                raise exc(qs)
            else:
                return None

        return self._from_mongo_one(data, projection=qs._projection)

    def update_one(self, update: Criteria, *,
                   upsert: bool = False) -> UpdateResult:
        """ Update a single document in queryset.
        """
        return self._collection.update_one(
            self._criteria,
            update,
            upsert=upsert,
        )

    def update_many(self, update: Criteria, *,
                    upsert: bool = False) -> UpdateResult:
        """ Update one or more documents in queryset.
        """
        return self._collection.update_many(
            self._criteria,
            update,
            upsert=upsert,
        )

    def delete_one(self) -> DeleteResult:
        """ Remove a single document in queryset.
        """
        return self._collection.delete_one(self._criteria)

    def delete_many(self) -> DeleteResult:
        """ Remove a single document in queryset.
        """
        return self._collection.delete_many(self._criteria)

    def find_one_and_update(self, update: Criteria, *,
                            upsert: bool = False,
                            return_document: bool = ReturnDocument.BEFORE,
                            ) -> Optional[TDoc]:
        """ Find a single document and update it.
        """
        data = self._collection.find_one_and_update(
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

    def find_one_and_replace(self, document: TDoc, *,
                             return_document: bool = ReturnDocument.BEFORE,
                             ) -> Optional[TDoc]:
        """ Find a single document and replace it.
        """
        data = self._collection.find_one_and_replace(
            filter=self._criteria,
            projection=self._projection,
            replacement=to_mongo(document),
            sort=self._sort,
            return_document=return_document,
        )
        if data is None:  # pragma: no cover
            return None

        return self._from_mongo_one(data, projection=self._projection)

    def find_one_and_delete(self) -> Optional[TDoc]:
        """ Find a single document and delete it.
        """
        data = self._collection.find_one_and_delete(
            filter=self._criteria,
            projection=self._projection,
            sort=self._sort,
        )
        if data is None:  # pragma: no cover
            return None

        return self._from_mongo_one(data, projection=self._projection)

    def count_documents(self) -> int:
        """ Count documents in queryset.
        """
        kwargs = {}
        if self._hint is not None:
            kwargs['hint'] = self._hint

        if self._comment is not None:
            kwargs['comment'] = self._comment

        return self._collection.count_documents(self._criteria, **kwargs)

    def distinct(self, field: str) -> List[Any]:
        """ Distinct query.
        """
        return self._cursor.distinct(field)

    def ids(self) -> Iterator[ObjectId]:
        """ Return all objects ids from queryset.
        """
        for raw in self.copy(projection={'_id': True})._cursor:
            yield raw['_id']

    def bulk(self) -> Dict[ObjectId, TDoc]:
        """ Return map {id: object}.

        :return: **dict**
        """
        qs = self.copy()
        qs._sort = None
        return {obj.id: obj for obj in qs}

    def join(self, *field_names: str) -> Join:
        """ Create `yadm.Join` object, join `field_names` and return it.

        :param str fields_names: fields for join
        :return: new :class:`yadm.join.Join`

        Next algorithm for join:
            1. Get all documents from queryset;
            2. Aggegate all ids from requested fields;
            3. Make *$in* queries for get joined documents;
            4. Bind joined documents to objects from first queryset;

        `Join` object is instance of `abc.Sequence`.
        """
        join = Join(self)

        if field_names:
            join.join(*field_names)

        return join

    def find_in(self, comparable: Iterable[Any], field: str = '_id', *,
                not_found: Union[NotFoundBehavior, str] = NotFoundBehavior.SKIP,
                ) -> Iterator[Optional[TDoc]]:
        """ Build ordered $in-query.

        Creates a query of the form {field: {'$in': comparable}} and
        returns the generator of documents with the same order as an elements
        in the argument 'comparable'.

        :param list comparable: values for compare in a query
        :param str field: field name of the document for comparison
        :param not_found: flag determines the behavior if the document
            with the specified value is not found
        :return: generator of docs

        not_found argument can take the following values:
            'none': If a document can not be found then a generator
                will return `None`.
            'skip': if a document can not be found then a generator
                will pass element.
            'error': if a document can not be found then a generator
                raise :class:`yadm.queryset.DocNotFoundError` exception.
        """
        not_found = NotFoundBehavior(not_found)
        hash_docs = {}

        for doc in self.find({field: {'$in': comparable}}):
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

    def update(self, update: Criteria, *,
               multi: bool = True, upsert: bool = False,
               ) -> UpdateResult:  # pragma: no cover
        warnings.warn("Use update_one or update_many!", DeprecationWarning)
        if multi:
            return self.update_many(update, upsert=upsert)
        else:
            return self.update_one(update, upsert=upsert)

    def remove(self, *, multi: bool = True) -> Any:  # pragma: no cover
        warnings.warn("Use remove_one or remove_many", DeprecationWarning)
        if multi:
            return self.delete_many()
        else:
            return self.delete_one()

    def find_and_modify(
            self, update: Optional[Criteria] = None, *, upsert: bool = False,
            full_response: bool = False, new: bool = False,
            **kwargs: Any) -> Any:  # pragma: no cover
        warnings.warn("Use find_one_and_* functions", DeprecationWarning)
        result = self._collection.find_and_modify(
            query=self._criteria,
            update=update,
            upsert=upsert,
            sort=self._sort or [],
            full_response=full_response,
            new=new,
            **kwargs
        )
        if not full_response:
            return self._from_mongo_one(result)
        else:
            result['value'] = self._from_mongo_one(result['value'])
            return result
