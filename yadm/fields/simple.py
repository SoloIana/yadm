"""
Fields for basic data types.
"""
from __future__ import annotations

from random import choice
from typing import TYPE_CHECKING, Any, Collection, Optional, TypeVar

from bson import ObjectId

from yadm.fields.base import Field, DefaultMixin, DocumentLike, pass_null
from yadm.markers import AttributeNotSet

if TYPE_CHECKING:
    from typing import Self

    from faker import Faker

T = TypeVar('T')


class StaticField(Field[Any]):
    """ Field for static data.
    """
    def __init__(self, data: Any) -> None:
        self.data = data

    def get_default(self, document: DocumentLike) -> Any:
        return self.data

    def get_if_attribute_not_set(self, document: DocumentLike) -> Any:
        raise RuntimeError("value for {} not exist in database"
                           "".format(self.__class__.__name__))

    def copy(self) -> Self:  # pragma: no cover
        return self.__class__(self.data)

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Any:
        return AttributeNotSet

    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        raise AttributeError("can't set attribute {!r}.{}"
                             "".format(document, self.name))

    def to_mongo(self, document: DocumentLike, value: Any) -> Any:
        if value != self.data:
            raise RuntimeError("bad value for {}: {!r} != {!r}"  # pragma: no cover
                               "".format(self.__class__.__name__,
                                         value,
                                         self.data))
        else:
            return self.data

    def from_mongo(self, document: DocumentLike, value: Any) -> Any:
        if value != self.data:
            raise RuntimeError("bad value in database for {}: {!r} != {!r}"
                               "".format(self.__class__.__name__,
                                         value, self.data))
        else:
            return self.data


class SimpleField(DefaultMixin, Field[T]):
    """ Base field for simple types.

    :param default: default value
    :param set choices: set of possible values
    """
    type: Any = None
    choices: Optional[Collection[Any]] = None

    def __init__(self, default: Any = AttributeNotSet, *,
                 choices: Optional[Collection[Any]] = None,
                 **kwargs: Any) -> None:
        if self.type is None:  # pragma: no cover
            raise NotImplementedError("Attribute 'type' is not implemented!")

        self.choices = choices

        kwargs['default'] = default
        super().__init__(**kwargs)

        if default is not AttributeNotSet:
            self._check_choices(default)

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Any:  # pragma: no cover
        if self.choices is not None:
            return choice(list(self.choices))
        else:
            return super().get_fake(document, faker, depth)

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        if value is AttributeNotSet:
            return AttributeNotSet

        elif not isinstance(value, self.type):
            value = self.type(value)

        self._check_choices(value)
        return value

    @pass_null
    def from_mongo(self, document: DocumentLike, value: Any) -> Any:
        if value is AttributeNotSet:
            return AttributeNotSet  # pragma: no cover

        elif not isinstance(value, self.type):
            value = self.type(value)

        return value

    def _check_choices(self, value: Any) -> None:
        if self.choices is not None and value not in self.choices:
            raise ValueError("{!r} not in choices: {!r}"
                             "".format(value, self.choices))


class ObjectIdField(SimpleField[ObjectId]):
    """ Field for ObjectId.

    :param bool default_gen: generate default value if not set
    """
    type = ObjectId
    default_gen = False

    def __init__(self, default_gen: bool = False) -> None:
        super().__init__()
        self.default_gen = default_gen

    def get_default(self, document: DocumentLike) -> Any:
        if self.default_gen:
            return ObjectId()
        else:
            return AttributeNotSet

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> ObjectId:
        return ObjectId()

    def copy(self) -> Self:
        return self.__class__(default_gen=self.default_gen)


class BooleanField(SimpleField[bool]):
    """ Field for boolean values.
    """
    type = bool

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> bool:
        return faker.pybool()


class IntegerField(SimpleField[int]):
    """ Field for integer.
    """
    type = int

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> int:  # pragma: no cover
        if self.choices is not None:
            return choice(list(self.choices))
        else:
            return faker.pyint()


class FloatField(SimpleField[float]):
    """ Field for float.
    """
    type = float

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> float:  # pragma: no cover
        if self.choices is not None:
            return choice(list(self.choices))
        else:
            return faker.pyfloat()


class StringField(SimpleField[str]):
    """ Field for string.
    """
    type = str

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> str:  # pragma: no cover
        if self.choices is not None:
            return choice(list(self.choices))

        try:
            fake = getattr(faker, self.name)()
        except AttributeError:
            fake = None

        if isinstance(fake, str):
            return fake
        else:
            return faker.pystr()
