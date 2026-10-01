from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from . import config

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
