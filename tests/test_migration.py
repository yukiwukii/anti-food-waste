import sqlite3

from sqlalchemy import create_engine, inspect


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE "drop" (id INTEGER PRIMARY KEY, weight_kg FLOAT)')
    con.execute('INSERT INTO "drop" (weight_kg) VALUES (0.2)')
    con.commit()
    con.close()

    from app import db

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{path}"))
    db.init_db()
    cols = {c["name"] for c in inspect(db.engine).get_columns("drop")}
    assert {"is_waste", "waste_note"} <= cols
    with db.engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT is_waste FROM "drop"').scalar() == 1
