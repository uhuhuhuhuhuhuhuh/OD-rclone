from odrclone.database import Database
from odrclone.schemas import Candidate
from odrclone.vfs.catalog import Catalog


def test_catalog_roundtrip(tmp_path):
    db = Database(f"sqlite:///{tmp_path/'db.sqlite'}")
    db.create_all()
    catalog = Catalog(db)
    candidate = Candidate(provider="test", filename="x.mkv", url="https://example.test/x.mkv", size=123)
    vf = catalog.add_candidate(candidate, "/TV/Test/x.mkv")
    assert vf.size == 123
    dirs, files = catalog.list_directory("/TV/Test")
    assert not dirs
    assert files[0].filename == "x.mkv"
