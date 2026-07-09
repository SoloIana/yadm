""" Common part for working with imports, documents and so on.
"""
from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from pymongo.read_preferences import (
    Nearest,
    Primary,
    PrimaryPreferred,
    Secondary,
    SecondaryPreferred,
)
from zope.dottedname.resolve import resolve

if TYPE_CHECKING:
    from yadm.documents import Document


Criteria = Dict[str, Any]
Projection = Dict[str, Any]
SortItem = Tuple[str, int]
Sort = List[SortItem]
Hint = Union[str, List[SortItem]]
Pipeline = List[Dict[str, Any]]
ReadPref = Union[Primary, PrimaryPreferred, Secondary,
                 SecondaryPreferred, Nearest]

TDoc = TypeVar('TDoc', bound='Document')


class EnclosedDocDescriptor:
    """ Descriptor for accessing an enclosed documens within an embedded
    (:py:class:`yadm.fields.embedded.EmbeddedDocumentField`) and a reference
    (:py:class:`yadm.fields.reference.ReferenceField`) fields.

    :param str enclosed_cls_type: Enclosed class type. Can take `embedded` or
        `reference` value. Otherwise :py:exc:`ValueError` will be raised.
    """

    _DOC_CLS = 'document_class'
    _RECURSIVE_REF_CONST = 'self'

    attr_name: str

    def __init__(self, enclosed_cls_type: str) -> None:
        if enclosed_cls_type in ('embedded', 'reference'):
            self.attr_name = '_{}_{}'.format(enclosed_cls_type, self._DOC_CLS)
        else:
            raise ValueError

    def __get__(self, instance: Any, owner: Optional[type] = None) -> Any:
        if not instance:
            return self

        value = getattr(instance, self.attr_name, None)

        if isinstance(value, str):
            if self._RECURSIVE_REF_CONST == value:
                value = getattr(instance, self._DOC_CLS)
            else:
                value = resolve(value)
            self.__set__(instance, value)

        return value

    def __set__(self, instance: Any, value: Any) -> None:
        setattr(instance, self.attr_name, value)

    def __delete__(self, instance: Any) -> None:
        delattr(instance, self.attr_name)


def build_update_query(
        set: Optional[Dict[str, Any]] = None,
        unset: Union[Dict[str, Any], Iterable[str], None] = None,
        inc: Optional[Dict[str, Any]] = None,
        push: Optional[Dict[str, Any]] = None,
        pull: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """ Helper for build update-queries.
    """
    query: Dict[str, Any] = {}

    if set:
        query['$set'] = set

    if unset:
        if isinstance(unset, dict):
            query['$unset'] = unset
        else:
            query['$unset'] = {f: True for f in unset}

    if inc:
        query['$inc'] = inc

    if push:
        query['$push'] = push

    if pull:
        query['$pull'] = pull

    return query or None
