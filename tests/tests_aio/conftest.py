import pytest_asyncio
import motor.motor_asyncio

from yadm.aio.database import AioDatabase


@pytest_asyncio.fixture()
async def client(mongo_args):
    host, port, _ = mongo_args
    if port is None:  # full mongodb:// uri
        return motor.motor_asyncio.AsyncIOMotorClient(host)
    return motor.motor_asyncio.AsyncIOMotorClient(host=host, port=port)


@pytest_asyncio.fixture()
async def db(client, mongo_args):
    _, _, name = mongo_args
    await client.drop_database(name)
    return AioDatabase(client, name)
