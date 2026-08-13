from odrclone.search.media_parser import parse_media_name


def test_episode_and_quality():
    parsed = parse_media_name("Example.Show.S03E07.1080p.WEB-DL.x265.HDR.mkv")
    assert (parsed.season, parsed.episode) == (3, 7)
    assert parsed.resolution == "1080p"
    assert parsed.codec == "x265"
    assert parsed.hdr is True


def test_movie_year():
    parsed = parse_media_name("Example Movie (2024) 2160p BluRay.mkv")
    assert parsed.year == 2024
    assert parsed.resolution == "2160p"
