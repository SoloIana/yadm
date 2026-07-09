from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING, Any

import dateutil.parser
import pytz

from yadm.fields.base import DefaultMixin, DocumentLike, Field, pass_null

if TYPE_CHECKING:
    from faker import Faker


class DatetimeField(DefaultMixin, Field[datetime]):
    """ Field for time stamp.

    :param bool auto_now: datetime.now as default
        (default: False)
    """
    def __init__(self, *, auto_now: bool = False, **kwargs: Any) -> None:
        self.auto_now = auto_now
        super().__init__(**kwargs)

    @staticmethod
    def _fix_timezone(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=pytz.utc)
        else:
            return value

    def get_default(self, document: DocumentLike) -> Any:
        if self.auto_now:
            return datetime.now(pytz.utc)
        else:
            return super().default

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Any:  # pragma: no cover
        if self.auto_now:
            return datetime.now(pytz.utc)
        else:
            return faker.date_time()

    @classmethod
    @pass_null
    def prepare_value(cls, document: DocumentLike, value: Any) -> Any:
        if isinstance(value, datetime):
            return cls._fix_timezone(value)

        elif isinstance(value, date):
            return datetime(
                *value.timetuple()[:3],
                tzinfo=pytz.utc
            )

        elif isinstance(value, str):
            value = dateutil.parser.parse(value)
            return cls._fix_timezone(value)

        else:  # pragma: no cover
            raise TypeError("First value must be datetime,"
                            " date or string, but {!r}".format(type(value)))

    @classmethod
    @pass_null
    def to_mongo(cls, document: DocumentLike, value: datetime) -> Any:
        return cls._fix_timezone(value)

    @classmethod
    @pass_null
    def from_mongo(cls, document: DocumentLike, value: datetime) -> Any:
        return cls._fix_timezone(value)


class TimedeltaField(DefaultMixin, Field[timedelta]):
    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> timedelta:
        return faker.time_delta()

    @classmethod
    @pass_null
    def prepare_value(cls, document: DocumentLike, value: Any) -> Any:
        if isinstance(value, timedelta):
            return value
        else:
            raise TypeError("Only timedelta is allowed, but {} given"
                            "".format(type(value)))

    @classmethod
    @pass_null
    def to_mongo(cls, document: DocumentLike, value: timedelta) -> Any:
        return value.total_seconds()

    @classmethod
    @pass_null
    def from_mongo(cls, document: DocumentLike, value: float) -> Any:
        return timedelta(seconds=value)
