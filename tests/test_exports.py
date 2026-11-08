import os

from core import database, exports


def make_db(tmp_path, name="a.db", foreign=None):
    """БД с двумя записями; CSV лежат в её подпапке экспорта."""
    root = tmp_path / "exports"
    folder = root / os.path.splitext(name)[0]
    folder.mkdir(parents=True)
    one = folder / "h1_table_1.csv"
    two = folder / "h1_table_2.csv"
    one.write_text("x", encoding="utf-8")
    two.write_text("y", encoding="utf-8")
    (folder / "_report_ВОР.tsv").write_text("r", encoding="utf-8")
    db_path = str(tmp_path / name)
    connection = database.init_db(db_path)
    database.add_file(connection, "h1", "p1", "f1")
    database.update_file_status(connection, 1, "SAVED", "%s;%s" % (one, two))
    if foreign:
        database.add_file(connection, "h2", "p2", "f2")
        database.update_file_status(connection, 2, "SAVED", str(foreign))
    connection.close()
    return db_path, str(root), folder


def test_exports_dir_per_db():
    assert exports.exports_dir_for("data/new.db", "data/exports") == os.path.join("data/exports", "new")


def test_prune_finds_orphans_and_missing(tmp_path):
    db_path, root, folder = make_db(tmp_path)
    (folder / "old_table_1.csv").write_text("z", encoding="utf-8")
    os.remove(folder / "h1_table_2.csv")

    result = exports.prune_exports(db_path, root, apply=False)
    assert [os.path.basename(p) for p in result["orphans"]] == ["old_table_1.csv"]
    assert len(result["missing"]) == 1
    assert (folder / "old_table_1.csv").exists()  # без apply ничего не тронуто

    result = exports.prune_exports(db_path, root, apply=True)
    assert not (folder / "old_table_1.csv").exists()
    assert (folder / "_orphans" / "old_table_1.csv").exists()
    assert (folder / "_report_ВОР.tsv").exists()  # отчёт сиротой не считается


def test_drop_database_archives_csv_then_db(tmp_path):
    foreign = tmp_path / "shared.csv"
    foreign.write_text("f", encoding="utf-8")
    db_path, root, folder = make_db(tmp_path, foreign=foreign)
    archive_root = str(tmp_path / "archive")

    result = exports.drop_database(db_path, root, archive_root)
    assert len(result["csv_done"]) == 2
    assert len(result["csv_foreign"]) == 1
    assert foreign.exists()  # чужой CSV не тронут
    assert not os.path.exists(db_path)
    assert not folder.exists()
    archive = result["archive_dir"]
    assert os.path.isfile(os.path.join(archive, "a.db"))
    assert os.path.isfile(os.path.join(archive, "exports", "h1_table_1.csv"))
    assert os.path.isfile(os.path.join(archive, "exports", "_report_ВОР.tsv"))


def test_drop_database_dry_run_and_no_archive(tmp_path):
    db_path, root, folder = make_db(tmp_path)
    archive_root = str(tmp_path / "archive")

    exports.drop_database(db_path, root, archive_root, dry_run=True)
    assert os.path.exists(db_path) and (folder / "h1_table_1.csv").exists()

    exports.drop_database(db_path, root, archive_root, archive=False)
    assert not os.path.exists(db_path) and not folder.exists()
    assert not os.path.exists(archive_root)


def test_prune_apply_migrates_old_shared_csv(tmp_path):
    root = tmp_path / "exports"
    root.mkdir()
    own = root / "own_table_1.csv"
    shared = root / "shared_table_1.csv"
    own.write_text("a", encoding="utf-8")
    shared.write_text("b", encoding="utf-8")
    db_path = str(tmp_path / "a.db")
    other_path = str(tmp_path / "b.db")
    for path, csv in ((db_path, "%s;%s" % (own, shared)), (other_path, str(shared))):
        connection = database.init_db(path)
        database.add_file(connection, "h", "p", "f")
        database.update_file_status(connection, 1, "SAVED", csv)
        connection.close()

    result = exports.prune_exports(db_path, str(root), apply=True)
    folder = root / "a"
    assert (folder / "own_table_1.csv").exists() and not own.exists()
    assert (folder / "shared_table_1.csv").exists() and shared.exists()  # скопирован
    assert len(result["migrated"]) == 2
    again = exports.check_exports(db_path, str(root))
    assert again["outside"] == [] and again["missing"] == []
