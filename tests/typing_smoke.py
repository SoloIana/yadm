""" Static typing smoke test.

This file is checked with mypy only (it is not collected by pytest):

    mypy --warn-unused-ignores tests/typing_smoke.py
"""
from __future__ import annotations

from typing import Dict, Optional, assert_type

from bson import ObjectId

from yadm import fields
from yadm.aio.database import AioDatabase
from yadm.aio.queryset import AioQuerySet
from yadm.database import Database
from yadm.documents import Document, EmbeddedDocument
from yadm.fields.simple import StringField
from yadm.queryset import QuerySet


class MyEDoc(EmbeddedDocument):
    x = fields.IntegerField()


class User(Document):
    __collection__ = 'users'

    name = fields.StringField()
    age = fields.IntegerField()
    active = fields.BooleanField()
    rate = fields.FloatField()
    edoc = fields.EmbeddedDocumentField(MyEDoc)


def check_fields(user: User) -> None:
    assert_type(user.name, str)
    assert_type(User.name, StringField)
    assert_type(user._id, ObjectId)
    assert_type(user.age, int)
    assert_type(user.active, bool)
    assert_type(user.rate, float)
    assert_type(user.edoc, MyEDoc)
    assert_type(user.edoc.x, int)

    user.name = 'yana'
    user.age = 13


def check_sync(db: Database, oid: ObjectId) -> None:
    qs = db.get_queryset(User)
    assert_type(qs, QuerySet[User])

    chained = qs.find({'age': {'$gt': 3}}).sort(('age', 1)).fields('age')
    assert_type(chained, QuerySet[User])

    assert_type(qs.find_one(), Optional[User])

    for u in qs:
        assert_type(u, User)

    assert_type(qs.bulk(), Dict[ObjectId, User])
    assert_type(db.save(User()), User)
    assert_type(db.get_document(User, oid), Optional[User])


async def check_aio(adb: AioDatabase, oid: ObjectId) -> None:
    aqs = adb.get_queryset(User)
    assert_type(aqs, AioQuerySet[User])

    found = await aqs.find_one()
    assert_type(found, Optional[User])

    async for u in aqs:
        assert_type(u, User)

    assert_type(await aqs.bulk(), Dict[ObjectId, User])
    assert_type(await adb.save(User()), User)
    assert_type(await adb.get_document(User, oid), Optional[User])
