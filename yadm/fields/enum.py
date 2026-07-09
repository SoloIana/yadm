from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar

from yadm.fields.base import DocumentLike, pass_null
from yadm.fields.simple import SimpleField
from yadm.markers import AttributeNotSet

if TYPE_CHECKING:
    from typing import Self

E = TypeVar('E', bound=Enum)


class EnumField(SimpleField[E]):
    """ Field for enum.Enum .
    """
    def __init__(self, enum: Type[E], **kwargs: Any) -> None:
        self.type = enum
        super().__init__(**kwargs)

    def copy(self) -> Self:
        return self.__class__(self.type,
                              smart_null=self.smart_null,
                              default=self.default)

    @pass_null
    def to_mongo(self, document: DocumentLike, value: E) -> Any:
        return value.value


class EnumStateSetError(Exception):
    def __init__(self, current: Any, new: Any) -> None:
        self.current = current
        self.new = new
        self.message = ("Not allowed in rules: {} -> {}"
                        "".format(current, new))

        super().__init__(self.message)


class EnumStateInvalidInitial(Exception):
    def __init__(self, initial_value: Any) -> None:
        self.message = ("{} is not allowed as initial value in rules "
                        "".format(initial_value))

        super().__init__(self.message)


class EnumStateField(EnumField[E]):
    """ Simple state machine with states are enum.Enum .
    """
    rules: Any = None

    def __init__(self, enum: Type[E], rules: Optional[dict] = None,
                 start: Any = AttributeNotSet, **kwargs: Any) -> None:
        if 'default' not in kwargs:
            kwargs = {'default': start, **kwargs}

        super().__init__(enum, **kwargs)

        if rules is not None:
            self.rules = rules

        if not self.rules:  # pragma: no cover
            raise ValueError("Rules list is empty")

    def copy(self) -> Self:
        return self.__class__(self.type, self.rules,
                              smart_null=self.smart_null,
                              default=self.default)

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        current_value = getattr(document, self.name, AttributeNotSet)
        new_value = super().prepare_value(document, value)

        if current_value is AttributeNotSet:
            if new_value != self.default:
                raise EnumStateInvalidInitial(new_value)

        else:
            if (new_value != current_value and
                    new_value not in self.rules.get(current_value, [])):
                raise EnumStateSetError(current_value, new_value)

        return new_value
