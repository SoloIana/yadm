""" Fields for geo data.

See: http://docs.mongodb.org/manual/applications/geospatial-indexes/

GeoJSON: http://geojson.org/geojson-spec.html

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Iterator, List, Type, TypeVar

from yadm.documents import DocumentItemMixin
from yadm.fields.base import DocumentLike, Field, pass_null

if TYPE_CHECKING:
    from faker import Faker


TYPES: List[Type[Geo]] = []


def _geo_type(type: Type[TGeo]) -> Type[TGeo]:
    # class decorator for add geo types to TYPES
    TYPES.append(type)
    return type


class Geo(DocumentItemMixin):
    """ Base class for GeoJSON data.
    """
    type: Any = None


TGeo = TypeVar('TGeo', bound=Geo)


class GeoCoordinates(Geo):
    """ Base class for GeoJSON data with coordinates.
    """
    def get_coordinates(self) -> Any:  # pragma: no cover
        raise NotImplementedError('get_coordinates must be implemented')

    def to_mongo(self) -> dict:
        return {
            'type': self.type,
            'coordinates': self.get_coordinates(),
        }


@_geo_type
class Point(GeoCoordinates):
    """ Class for GeoJSON Point objects.

    See: http://geojson.org/geojson-spec.html#id2
    """
    type = 'Point'

    def __init__(self, longitude: float, latitude: float) -> None:
        self.longitude = longitude
        self.latitude = latitude

    def __getitem__(self, idx: Any) -> Any:
        return (self.longitude, self.latitude)[idx]

    def get_coordinates(self) -> Any:
        return [self.longitude, self.latitude]

    @classmethod
    def from_mongo(cls, data: Any) -> Point:
        try:
            coordinates = data['coordinates']
        except KeyError:  # pragma: no cover
            raise ValueError('coordinates not found in data: "{!r}"'.format(data))

        try:
            longitude, latitude = coordinates
        except IndexError:  # pragma: no cover
            raise ValueError('wrong coordinates in data: "{!r}"'.format(data))

        return cls(longitude, latitude)


@_geo_type
class MultiPoint(GeoCoordinates, Sequence):
    """ Class for GeoJSON MultiPoint objects.

    See: http://geojson.org/geojson-spec.html#id5
    """
    type = 'MultiPoint'

    def __init__(self, points: List[Point]) -> None:
        self._points = points

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self) -> Iterator[Point]:  # pragma: no cover
        return iter(self._points)

    def __getitem__(self, item: Any) -> Any:
        return self._points[item]

    def get_coordinates(self) -> Any:
        return [p.to_mongo()['coordinates'] for p in self._points]

    @classmethod
    def from_mongo(cls, data: Any) -> MultiPoint:
        try:
            coordinates = data['coordinates']
        except KeyError:  # pragma: no cover
            raise ValueError('coordinates not found in data: "{!r}"'.format(data))

        return cls([Point(*c) for c in coordinates])


class GeoField(Field[TGeo]):
    """ Base field for GeoJSON objects.
    """
    def __init__(self, types: List[Type[Geo]] = TYPES, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.types = types
        # values are the concrete geo classes; from_mongo() lives on them,
        # not on Geo, so the value type stays loose
        self.types_dict: dict = {t.type: t for t in types}

    @pass_null
    def to_mongo(self, document: DocumentLike, geo: GeoCoordinates) -> Any:
        return geo.to_mongo()

    @pass_null
    def from_mongo(self, document: DocumentLike, data: Any) -> Any:
        geo_type = self.types_dict.get(data['type'])

        if geo_type is None:  # pragma: no cover
            raise ValueError('unknown type in data: "{!r}"'.format(data))

        return geo_type.from_mongo(data)


class GeoOneTypeField(GeoField[TGeo]):
    """ Base field for GeoJSON objects with one acceptable type.
    """
    type: Any = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if self.type is None:  # pragma: no cover
            raise NotImplementedError('attribute "type" must be implemented')

        self.types = [self.type]
        self.types_dict = {self.type.type: self.type}

    @pass_null
    def prepare_value(self, document: DocumentLike, value: Any) -> Any:
        if isinstance(value, self.type):
            return value
        elif isinstance(value, dict):
            return self.type.from_mongo(value)
        else:  # pragma: no cover
            raise TypeError(value)

    def _get_fake_point(self, faker: Faker) -> Point:  # pragma: no cover
        return Point(float(faker.longitude()), float(faker.latitude()))


class PointField(GeoOneTypeField[Point]):
    """ Field for Point.
    """
    type = Point

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> Point:  # pragma: no cover
        return self._get_fake_point(faker)


class MultiPointField(GeoOneTypeField[MultiPoint]):
    """ Field for MultiPoint.
    """
    type = MultiPoint

    def get_fake(self, document: DocumentLike,
                 faker: Faker, depth: int) -> List[Point]:  # pragma: no cover
        return [self._get_fake_point(faker) for _ in range(4)]
