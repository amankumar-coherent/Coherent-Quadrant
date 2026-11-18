"""Duplicates that differ by a plural, a bracketed city, or a missing website (owner 2026-11-14)."""
from vendor_intel.pipeline.quadrant_pipeline import dedupe_companies


def _groups(rows):
    reps, groups = dedupe_companies(rows)
    return sorted(sorted(g) for g in groups.values())


def test_plural_and_bracketed_city_are_one_company():
    g = _groups([{"name": "Jiahua Chemicals"},
                 {"name": "Jiahua Chemical (Shanghai) Co., Ltd.", "website": "https://jiahua.com"}])
    assert len(g) == 1


def test_a_name_that_is_another_rows_domain_label_is_that_company():
    g = _groups([{"name": "SABIC"},
                 {"name": "Saudi Basic Industries Corporation", "website": "sabic.com"}])
    assert len(g) == 1


def test_distinct_companies_stay_apart():
    g = _groups([{"name": "Dow Inc.", "website": "dow.com"}, {"name": "BASF SE", "website": "basf.com"},
                 {"name": "Maoming Yunlong Industrial Development Co., Ltd."},
                 {"name": "Glass Industries"}, {"name": "Glass Industry"}])
    assert len(g) == 5
