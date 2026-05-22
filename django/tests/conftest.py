"""Root conftest — shared fixtures across unit/, integration/, and e2e/ tests.

The legacy mgnify_bgcs fixtures (BgcFactory, ContigFactory, etc.) were
retired with the legacy app. v2 fixtures live next to the suites that
need them; importing here would couple unrelated tests.
"""
