import pytest

from odrclone.vfs.ranges import ByteRange, parse_range_header


def test_normal_range():
    assert parse_range_header("bytes=10-19", 100) == ByteRange(10, 19)


def test_open_range():
    assert parse_range_header("bytes=90-", 100) == ByteRange(90, 99)


def test_suffix_range():
    assert parse_range_header("bytes=-10", 100) == ByteRange(90, 99)


def test_unsatisfiable():
    with pytest.raises(IndexError):
        parse_range_header("bytes=100-", 100)
