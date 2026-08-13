from odrclone.servarr.automation import query_for_missing


def test_sonarr_query():
    query, path = query_for_missing("sonarr", {"series": {"title": "Example Show"}, "seasonNumber": 3, "episodeNumber": 7})
    assert query == "Example Show S03E07"
    assert path == "/TV/Example Show/Season 03"


def test_radarr_query():
    query, path = query_for_missing("radarr", {"title": "Example Movie", "year": 2024})
    assert query == "Example Movie 2024"
    assert path == "/Movies/Example Movie (2024)"
