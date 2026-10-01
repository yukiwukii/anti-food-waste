from collections.abc import Iterator

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from . import config

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _record):
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


# Columns added after the first release: (table, column, SQL definition).
_ADDED_COLUMNS = [
    ("drop", "is_waste", "BOOLEAN NOT NULL DEFAULT 1"),
    ("drop", "waste_note", "VARCHAR"),
]


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    existing = {t: {c["name"] for c in inspect(engine).get_columns(t)} for t in {t for t, _, _ in _ADDED_COLUMNS}}
    with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if column not in existing[table]:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
