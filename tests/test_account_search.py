from app.admin_helpers import extract_short_link_slug, normalize_account_search


def test_extract_slug_from_full_url():
    assert extract_short_link_slug("http://bytl.org/r/s3h8ys6") == "s3h8ys6"
    assert extract_short_link_slug("https://bytl.org/r/s3h8ys6/") == "s3h8ys6"
    assert extract_short_link_slug("bytl.org/r/s3h8ys6") == "s3h8ys6"
    assert extract_short_link_slug("/r/s3h8ys6") == "s3h8ys6"


def test_extract_slug_ignores_plain_handle():
    assert extract_short_link_slug("s3h8ys6") is None
    assert extract_short_link_slug("teodorbratanov") is None


def test_normalize_account_search_prefers_slug_from_url():
    assert normalize_account_search("http://bytl.org/r/s3h8ys6") == "s3h8ys6"
    assert normalize_account_search("  s3h8ys6  ") == "s3h8ys6"
    assert normalize_account_search("") is None
