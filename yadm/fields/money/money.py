""" Field for money.

Use :class:`yadm.fields.money.Money`, as value for money

.. code block: python

    class DocClass(Document):
        money = MoneyField()

    doc = DocClass()
    doc.money = Money('3.14', 'USD')

    db.insert_one(doc)

This code save to MongoDB document:

.. code block: javascript

    {
        id: ObjectId('534272984c78591787e1a964'),
        money: {v: 314, c: 'USD'}
    }
"""
from __future__ import annotations

import random
from decimal import Decimal, Context, ROUND_UP
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

from yadm.fields.base import DefaultMixin, DocumentLike, Field, pass_null
from .currency import DEFAULT_CURRENCY_STORAGE
from yadm.markers import AttributeNotSet

if TYPE_CHECKING:
    from faker import Faker

_F = TypeVar('_F', bound=Callable[..., Any])


def _checker(method: _F) -> _F:
    """ Decorator for check type of value.
    """
    @wraps(method)
    def wrapper(self: Any, value: Any) -> Any:
        if not isinstance(value, Money):
            return NotImplemented

        if self.currency != value.currency:
            raise ValueError("Money {!r} and {!r} must be with the"
                             " same currencies".format(str(self), str(value)))
        return method(self, value)

    return cast('_F', wrapper)


def _special_comparison(method: _F) -> _F:
    """ Decorator for special compression Money with other values.
    """
    @wraps(method)
    def wrapper(self: Any, value: Any) -> Any:
        if isinstance(value, int):
            # This need to compare Money with 0 only integer
            if value:
                return NotImplemented
            else:
                return method(self.value, value)

        elif isinstance(value, Money):
            if self.currency != value.currency:
                raise ValueError("Money {!r} and {!r} must be with"
                                 " the same currencies".format(self, value))
            else:
                return method(self.value, value.value)

        else:  # pragma: no cover
            return NotImplemented

    return cast('_F', wrapper)


class Money:
    _context = Context(rounding=ROUND_UP)

    def __init__(self, value: Any, currency: Any = None) -> None:
        if isinstance(value, Money):
            if currency is not None:
                raise TypeError("new Money from another Money not need"
                                " currency {!r} as parameter".format(currency))
            else:
                self._value = value.value
                self._currency = value.currency

        else:
            if currency is None:
                raise TypeError("Curency is not set.")
            else:
                self._currency = currency = DEFAULT_CURRENCY_STORAGE[currency]

            if isinstance(value, Decimal):
                precision_decimal = Decimal('1.' + '0' * currency.precision)
                self._value = value.quantize(precision_decimal, self._context.rounding)

            else:
                value = Decimal(value, context=self._context)
                precision_decimal = Decimal('1.' + '0' * currency.precision)
                self._value = value.quantize(precision_decimal, self._context.rounding)

    @classmethod
    def from_cents(cls, cents: int, currency: Any) -> 'Money':
        """ Return new Money object from cents.
        """
        _currency = DEFAULT_CURRENCY_STORAGE[currency]
        delimiter = Decimal(10 ** _currency.precision)
        return cls(cents / delimiter, _currency)

    @classmethod
    def from_string(cls, s: str) -> 'Money':
        c: Any
        v, c = s.strip().split()

        if c.isdigit():
            c = int(c)
        else:
            ValueError(s)

        try:
            return cls(v, DEFAULT_CURRENCY_STORAGE[c])
        except KeyError as exc:
            raise ValueError from exc

    @property
    def value(self) -> Decimal:
        return self._value

    @property
    def currency(self) -> Any:
        return self._currency

    @property
    def total_cents(self) -> int:
        """ Return total cents in this object.
        """
        precision = self.currency.precision
        precision_decimal = Decimal('1.' + '0' * precision)
        quantized = self.value.quantize(precision_decimal, self._context.rounding)
        return int(quantized * 10 ** precision)

    def __abs__(self) -> 'Money':
        return self.__class__(abs(self._value), self.currency)

    @_checker
    def __add__(self, target: Any) -> 'Money':
        return self.__class__(self.value + target.value, self.currency)

    @_checker
    def __sub__(self, target: Any) -> 'Money':
        return self.__class__(self.value - target.value, self.currency)

    def __neg__(self) -> 'Money':
        return Money(-self.value, self.currency)

    def __mul__(self, target: Any) -> Any:
        if isinstance(target, (int, Decimal)):
            return self.__class__(self.value * target, self.currency)
        else:
            return NotImplemented

    def __rmul__(self, target: Any) -> Any:
        return self.__mul__(target)

    def __truediv__(self, target: Any) -> Any:
        if isinstance(target, self.__class__):
            if self.currency == target.currency:
                return self.value / target.value
            else:
                raise ValueError("Money {!r} and {!r} must be with"
                                 " the same currencies".format(self, target))
        else:
            return self.__class__(self.value / target, self.currency)

    def __eq__(self, target: Any) -> bool:
        if target is 0:
            return self.value == target
        else:
            return (isinstance(target, self.__class__) and
                    self.value == target.value and
                    self.currency == target.currency)

    @_special_comparison
    def __gt__(self, other: Any) -> Any:
        return self > other

    @_special_comparison
    def __lt__(self, other: Any) -> Any:
        return self < other

    @_special_comparison
    def __ge__(self, other: Any) -> Any:
        return self > other or self == other

    @_special_comparison
    def __le__(self, other: Any) -> Any:
        return self < other or self == other

    def __bool__(self) -> bool:
        return bool(self.value)

    def __hash__(self) -> int:
        return hash(str(self))

    def __str__(self) -> str:
        precision = self.currency.precision
        precision_decimal = Decimal('1.' + '0' * precision)
        quantized = self.value.quantize(precision_decimal, self._context.rounding)
        return '{} {}'.format(quantized, self._currency.string)

    def __repr__(self) -> str:
        return 'Money({!s})'.format(self)

    def to_mongo(self) -> Any:
        # b/c
        return MoneyField.to_mongo(None, None, self)  # type: ignore[arg-type]

    def is_positive(self) -> bool:
        return self.value > 0

    def is_negative(self) -> bool:
        return self.value < 0

    def is_zero(self) -> bool:
        return self.value == 0


class MoneyField(DefaultMixin, Field[Money]):
    """ Field to storage money values.
    """
    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Any:  # pragma: no cover
        value = faker.pydecimal(left_digits=5, right_digits=2, positive=True)
        currency = random.choice(list(DEFAULT_CURRENCY_STORAGE.values()))
        return Money(value, currency)

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        if isinstance(value, Money):
            return value
        else:
            raise TypeError("Only money is allowed for asigment to MoneyField.")

    @pass_null
    def to_mongo(self, document: DocumentLike, value: Any) -> Any:
        return [value.total_cents, value.currency.code]

    @pass_null
    def from_mongo(self, document: DocumentLike, data: Any) -> Any:
        if data is AttributeNotSet:  # pragma: no cover
            return AttributeNotSet
        elif isinstance(data, list):
            value, currency_key = data
            currency = DEFAULT_CURRENCY_STORAGE[currency_key]
            new_value = Decimal(value) / (10 ** currency.precision)
            return Money(new_value, currency)
        else:  # pragma: no cover
            raise TypeError("Incorrect type of value {!r} for Money".format(type(data)))
