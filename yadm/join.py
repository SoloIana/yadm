from __future__ import annotations

from collections import abc
from collections import defaultdict
from typing import Any, Dict, Iterator, Optional, Set, Type

from bson import ObjectId

from yadm.documents import Document
from yadm.fields.reference import ReferenceField


class Join(abc.Sequence):
    """ Helper for build client-side joins.
    """
    def __init__(self, qs: Any) -> None:
        self._qs = qs
        self._document_class = qs._document_class
        self._db = qs._db

        self._indexes: Dict[Type[Document], Dict[ObjectId, Document]] = defaultdict(dict)
        self._map_name_type: Dict[str, Type[Document]] = {}
        self._map_type_names: Dict[Type[Document], Set[str]] = defaultdict(set)
        self._map_name_ids: Dict[str, Set[ObjectId]] = defaultdict(set)

        self._data = list(qs)

    # abc.Sequence method

    def __iter__(self) -> Iterator[Document]:  # pragma: no cover
        return iter(self._data)

    def __getitem__(self, idx: Any) -> Any:  # pragma: no cover
        return self._data[idx]

    def __contains__(self, item: Any) -> bool:  # pragma: no cover
        return item in self._data

    def __len__(self) -> int:  # pragma: no cover
        return len(self._data)

    def __reversed__(self) -> Iterator[Document]:  # pragma: no cover
        return reversed(self._data)

    def index(self, item: Any) -> int:  # type: ignore[override]  # pragma: no cover
        return self._data.index(item)

    # end abc.Sequence

    def get_queryset(self, field_name: str) -> Any:
        """ Return queryset for joined objects.
        """
        field = self._get_field(field_name)
        qs = self._db(field.reference_document_class)
        ids = self._get_joined_ids(field_name)
        return qs.find({'_id': {'$in': list(ids)}})

    def join(self, *field_names: str) -> None:
        """ Do manual join.
        """
        self._load_names_types_maps(*field_names)
        self._load_map_name_ids(*field_names)
        self._load_objects_to_indexes(*field_names)
        self._set_objects(*field_names)

    def _get_field(self, field_name: str) -> ReferenceField[Any]:
        document_fields = self._document_class.__fields__
        if field_name not in document_fields:
            raise ValueError("field not exists: {!r}".format(field_name))

        field = document_fields[field_name]

        if not isinstance(field, ReferenceField):
            raise ValueError("bad field type: {!r}".format(field_name))

        return field

    def _get_joined_ids(self, field_name: str) -> Set[ObjectId]:
        ids = set()
        for doc in self:
            value = doc.__raw__[field_name]

            _id = self._prepare_id(value)
            if _id:
                ids.add(_id)

        return ids

    def _load_names_types_maps(self, *field_names: str) -> None:
        for field_name in field_names:
            field = self._get_field(field_name)
            reference_document_class = field.reference_document_class
            self._map_name_type[field_name] = reference_document_class
            self._map_type_names[reference_document_class].add(field_name)

    def _load_map_name_ids(self, *field_names: str) -> None:
        for doc in self:
            for field_name in field_names:
                value = doc.__raw__.get(field_name)

                _id = self._prepare_id(value)
                if _id:
                    self._map_name_ids[field_name].add(_id)

    def _load_objects_to_indexes(self, *field_names: str) -> None:
        field_names_set = set(field_names)

        for joined_document_class, names in self._map_type_names.items():
            if not (field_names_set & names):
                continue

            ids = set()
            for field_name in names:
                ids.update(self._map_name_ids[field_name])

            new_ids = list(ids - set(self._indexes[joined_document_class]))
            qs = self._db(joined_document_class).find({'_id': {'$in': new_ids}})
            self._indexes[joined_document_class].update(qs.bulk())

    def _set_objects(self, *field_names: str) -> None:
        for doc in self:
            for field_name in field_names:
                value = doc.__raw__.get(field_name)

                _id = self._prepare_id(value)
                if _id:
                    joined_document_class = self._map_name_type[field_name]
                    index = self._indexes[joined_document_class]
                    doc.__cache__[field_name] = index.get(_id, value)

    def _prepare_id(self, value: Any) -> Optional[ObjectId]:
        if isinstance(value, ObjectId):
            return value
        elif isinstance(value, Document):
            return value.id
        else:
            return None
