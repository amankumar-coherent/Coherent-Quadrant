"""SEO doorway-network collapsing.

Regression from a real North America run: 53 of 191 exported "companies" were one
operator's per-country landing pages — "Rupture Discs Argentina" on
rupturediscsargentina.com, "Rupture Discs Bahrain" on rupturediscsbahrain.com, and
so on. Every per-row gate passed them correctly; the pattern only exists across rows.
"""
from __future__ import annotations

from vendor_intel.pipeline.doorway_filter import (
    dedupe_name_variants,
    domain_stem,
    ends_with_place,
    filter_doorways,
    find_clusters,
    is_doorway_cluster,
)

PLACES = ["Argentina", "Bahrain", "Belgium", "Brazil", "Chile", "Kenya", "Oman"]


def _network(places=PLACES):
    return [
        {"company": f"Rupture Discs {p}", "domain": f"rupturediscs{p.lower()}.com",
         "quality_score": 0.6}
        for p in places
    ]


def _real():
    return [
        {"company": "Fike Corporation", "domain": "fike.com", "quality_score": 0.9},
        {"company": "BS&B Safety Systems", "domain": "bsbsystems.com", "quality_score": 0.9},
        {"company": "Continental Disc Corporation", "domain": "contdisc.com", "quality_score": 0.9},
    ]


# ── helpers ───────────────────────────────────────────────────────────────
def test_domain_stem_takes_the_first_label():
    assert domain_stem("rupturediscsargentina.com") == "rupturediscsargentina"
    assert domain_stem("https://www.rupturediscs.com.au/x") == "rupturediscs"
    assert domain_stem("") == ""


def test_ends_with_place_handles_multiword_places():
    assert ends_with_place("Rupture Discs Bahrain") == "bahrain"
    assert ends_with_place("Rupture Discs United Arab Emirates") == "united arab emirates"
    assert ends_with_place("Rupture Discs Middle East") == "middle east"
    assert ends_with_place("Fike Corporation") == ""


def test_place_alone_is_not_a_name_tail():
    """A bare place must not read as "<something> <place>"."""
    assert ends_with_place("Brazil") == ""


# ── clustering (signal 1) ─────────────────────────────────────────────────
def test_shared_domain_stem_forms_one_cluster():
    rows = _network()
    clusters = find_clusters(rows)
    assert len(clusters) == 1
    assert len(clusters[0]) == len(rows)


def test_unrelated_domains_do_not_cluster():
    assert find_clusters(_real()) == []


def test_two_similar_domains_are_not_a_network():
    """MIN_CLUSTER guards against coincidence."""
    rows = _network(["Argentina", "Bahrain"])
    assert all(len(c) < 3 for c in find_clusters(rows)) or find_clusters(rows) == []


# ── both signals together ─────────────────────────────────────────────────
def test_doorway_network_is_detected():
    rows = _network()
    (cluster,) = find_clusters(rows)
    assert is_doorway_cluster(rows, cluster) is True


def test_similar_domains_with_real_names_are_not_a_network():
    """Signal 1 alone would merge these; signal 2 must save them."""
    rows = [
        {"company": "Rupture Disc Solutions", "domain": "rupturediscsolutions.com"},
        {"company": "Rupture Disc Technology", "domain": "rupturedisctechnology.com"},
        {"company": "Rupture Disc Engineering", "domain": "rupturediscengineering.com"},
    ]
    for cluster in find_clusters(rows):
        assert is_doorway_cluster(rows, cluster) is False


def test_singular_plural_member_does_not_break_detection():
    """The real cluster contained "Rupture Disc Solutions" (singular).

    An earlier shared-prefix implementation collapsed to one common word and the
    tails became "discs australia", matching no place — so nothing was filtered.
    """
    rows = _network() + [
        {"company": "Rupture Disc Solutions", "domain": "rupturediscsolutions.com", "quality_score": 0.5}
    ]
    kept, dropped = filter_doorways(rows)
    assert len(dropped) >= len(PLACES) - 1


# ── end to end ────────────────────────────────────────────────────────────
def test_one_canonical_row_survives_the_network():
    rows = _network()
    kept, dropped = filter_doorways(rows)
    assert len(kept) == 1
    assert len(dropped) == len(rows) - 1
    assert all(d["export_reject"].startswith("doorway_network:") for d in dropped)


def test_real_companies_are_untouched():
    rows = _network() + _real()
    kept, _ = filter_doorways(rows)
    names = {r["company"] for r in kept}
    for want in ("Fike Corporation", "BS&B Safety Systems", "Continental Disc Corporation"):
        assert want in names


def test_best_evidenced_member_is_kept():
    rows = _network(["Argentina", "Bahrain", "Belgium"])
    rows[1]["quality_score"] = 0.95
    kept, _ = filter_doorways(rows)
    assert kept[0]["company"] == "Rupture Discs Bahrain"


# ── name-variant dedupe ───────────────────────────────────────────────────
def test_legal_suffix_variants_collapse():
    rows = [
        {"company": "Parker Hannifin", "domain": "parker.com", "quality_score": 0.9},
        {"company": "Parker Hannifin Corporation", "domain": "parkerhannifin.com", "quality_score": 0.7},
    ]
    kept, dropped = dedupe_name_variants(rows)
    assert len(kept) == 1
    assert kept[0]["company"] == "Parker Hannifin"
    assert dropped[0]["export_reject"].startswith("duplicate_name:")


def test_distinct_companies_are_not_collapsed():
    kept, dropped = dedupe_name_variants(_real())
    assert len(kept) == 3 and dropped == []
