import os
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--e2e-base-url",
        action="store",
        dest="e2e_base_url",
        default=None,
        help="Base URL for the legacy E2E suite (test_bgc_journey).",
    )
    parser.addoption(
        "--e2e-v2-base-url",
        action="store",
        dest="e2e_v2_base_url",
        default=None,
        help=(
            "Base URL for the v2 Discovery dashboard E2E suite "
            "(test_v2_discovery_journey). Defaults to http://localhost:8000."
        ),
    )


@pytest.fixture(scope="session")
def e2e_base_url(pytestconfig) -> str:
    # Priority: CLI option > env var > default dev host
    cli_val = pytestconfig.getoption("e2e_base_url")
    env_val = os.environ.get("E2E_BASE_URL")
    base = cli_val or env_val or "https://bgc-portal-dev.mgnify.org"
    return base.rstrip("/")


@pytest.fixture(scope="session")
def e2e_v2_base_url(pytestconfig) -> str:
    """Base URL for the v2 iBGC-first dashboard.

    Defaults to ``http://localhost:8000`` since staging may still be running
    the legacy UI; pass ``--e2e-v2-base-url`` (or set ``E2E_V2_BASE_URL``)
    once a v2 deployment is reachable.
    """
    cli_val = pytestconfig.getoption("e2e_v2_base_url")
    env_val = os.environ.get("E2E_V2_BASE_URL")
    base = cli_val or env_val or "http://localhost:8000"
    return base.rstrip("/")
