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


# Columns added after the first release: (table, column, SQL definition, backfill run once when added).
_ADDED_COLUMNS = [
    ("drop", "is_waste", "BOOLEAN NOT NULL DEFAULT 1", None),
    ("drop", "waste_note", "VARCHAR", None),
    ("drop", "edible_fraction", "FLOAT NOT NULL DEFAULT 1.0", None),
    ("drop", "waste_kg", "FLOAT", None),
    ("drop", "model", "VARCHAR", None),
    ("drop", "model_prompt", "VARCHAR", None),
    ("drop", "model_reasoning", "VARCHAR", None),
    ("drop", "model_output", "VARCHAR", None),
    # Before demo markers existed, demo rows can still be recognised by their seed weigh-ins.
    ("preplog", "is_demo", "BOOLEAN NOT NULL DEFAULT 0",
     'UPDATE preplog SET is_demo = 1 WHERE EXISTS (SELECT 1 FROM "drop" d WHERE d.classified_by = \'seed\' '
     "AND d.stall_id = preplog.stall_id AND date(d.created_at) = preplog.day)"),
    ("composttransfer", "is_demo", "BOOLEAN NOT NULL DEFAULT 0",
     'UPDATE composttransfer SET is_demo = 1 WHERE id IN (SELECT transfer_id FROM "drop" WHERE classified_by = \'seed\')'),
]


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    tables = {t for t, *_ in _ADDED_COLUMNS}
    existing = {t: {c["name"] for c in inspect(engine).get_columns(t)} for t in tables}
    with engine.begin() as conn:
        for table, column, ddl, backfill in _ADDED_COLUMNS:
            if column not in existing[table]:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))
                if backfill:
                    conn.execute(text(backfill))
        # Rows from before the edible-fraction estimate: all of the weight counts, unless marked not waste.
        conn.execute(text(
            'UPDATE "drop" SET waste_kg = CASE WHEN is_waste THEN weight_kg ELSE 0 END WHERE waste_kg IS NULL'
        ))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
