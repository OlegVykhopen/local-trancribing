import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "t.db")
    yield connection
    connection.close()
