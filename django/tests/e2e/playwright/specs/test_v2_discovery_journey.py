"""E2E spec covering the v2 iBGC-first Discovery dashboard.

Exercises the redesigned surface end-to-end:

  - landing on ``/`` renders the new dashboard with TopFiltersStrip + three-tab
    results card + reference/compare detail slots + protein info panel
  - tab switching between BGC roster / Variables map / UMAP
  - left-click on a roster row populates the Compare slot
  - right-click on a roster row → context menu → "Set as reference iBGC" pins
    the row in the Reference slot
  - "Add to shortlist" context-menu item increments the header shortlist badge
  - clicking "Generate Report" mints a token and opens ``/report?token=…`` in
    a new tab; the report root + Save-as-HTML / Print buttons render

Run against a local dev backend (default ``http://localhost:8000``) or pass
``--e2e-v2-base-url <url>``. Tests are defensive: they skip steps cleanly
when the dataset is empty so the spec can run on a freshly-seeded instance
without a clustering run.
"""

from __future__ import annotations

import re

import pytest


@pytest.mark.e2e
def test_v2_dashboard_shell_renders(page, e2e_v2_base_url):
    """The new dashboard shell + key panels mount on ``/``."""
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")

    page.wait_for_selector('[data-testid="ibgc-dashboard"]', timeout=30_000)
    page.wait_for_selector('[data-testid="results-card-slot"]')
    page.wait_for_selector('[data-testid="reference-detail-slot"]')
    page.wait_for_selector('[data-testid="compare-detail-slot"]')
    page.wait_for_selector('[data-testid="protein-info-slot"]')
    page.wait_for_selector('[data-testid="shortlist-trigger"]')

    # Run Query button (uses data-tour attribute) is present and enabled.
    run_query = page.locator('[data-tour="run-query"]')
    assert run_query.count() >= 1
    assert run_query.first.is_enabled()


@pytest.mark.e2e
def test_v2_results_tabs_switch(page, e2e_v2_base_url):
    """The three results tabs all activate and reveal their tab panel."""
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="results-tabs"]')

    # Roster is the default tab.
    page.wait_for_selector('[data-testid="ibgc-roster"]', timeout=30_000)

    # Switch to Variables map.
    page.locator('[data-testid="results-tab-variables"]').click()
    # Variables tab shows X/Y axis selectors (combobox role).
    page.wait_for_selector('text=/^Novelty$/', timeout=10_000)

    # Switch to UMAP.
    page.locator('[data-testid="results-tab-umap"]').click()
    # Tab content is rendered (the plot or its loading/empty placeholder).
    page.wait_for_timeout(500)

    # Back to roster.
    page.locator('[data-testid="results-tab-roster"]').click()
    page.wait_for_selector('[data-testid="ibgc-roster"]')


@pytest.mark.e2e
def test_v2_compare_slot_left_click(page, e2e_v2_base_url):
    """Left-clicking a roster row loads it into the Compare slot."""
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="ibgc-roster"]', timeout=30_000)

    rows = page.locator('[data-testid="ibgc-roster-row"]')
    if rows.count() == 0:
        pytest.skip("No iBGCs in the dataset — skipping compare-slot test")

    first_row = rows.first
    ibgc_id = first_row.get_attribute("data-ibgc-id")
    assert ibgc_id, "Expected data-ibgc-id on roster row"

    first_row.click()
    # Compare slot should render the iBGC label "iBGC-<id>" within ~5s.
    compare_slot = page.locator('[data-testid="compare-detail-slot"]')
    compare_slot.locator(f"text=iBGC-{ibgc_id}").wait_for(timeout=10_000)


@pytest.mark.e2e
def test_v2_set_reference_via_context_menu(page, e2e_v2_base_url):
    """Right-click → "Set as reference iBGC" pins the row in the Reference slot."""
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="ibgc-roster"]', timeout=30_000)

    rows = page.locator('[data-testid="ibgc-roster-row"]')
    if rows.count() == 0:
        pytest.skip("No iBGCs in the dataset — skipping reference-pin test")

    first_row = rows.first
    ibgc_id = first_row.get_attribute("data-ibgc-id")

    first_row.click(button="right")
    item = page.get_by_role("menuitem", name=re.compile("Set as reference", re.I))
    item.click()

    ref_slot = page.locator('[data-testid="reference-detail-slot"]')
    ref_slot.locator(f"text=iBGC-{ibgc_id}").wait_for(timeout=10_000)


@pytest.mark.e2e
def test_v2_shortlist_add_and_count(page, e2e_v2_base_url):
    """Adding via the context menu bumps the header shortlist badge count."""
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="ibgc-roster"]', timeout=30_000)

    rows = page.locator('[data-testid="ibgc-roster-row"]')
    if rows.count() == 0:
        pytest.skip("No iBGCs in the dataset — skipping shortlist test")

    badge = page.locator('[data-testid="shortlist-count"]')
    start = int(badge.inner_text().strip())

    rows.first.click(button="right")
    add_item = page.get_by_role("menuitem", name=re.compile("Add to shortlist", re.I))
    add_item.click()

    # Badge updates eagerly via the persisted Zustand store.
    page.wait_for_function(
        "(start) => parseInt("
        "document.querySelector('[data-testid=\"shortlist-count\"]')."
        "textContent.trim(), 10) > start",
        arg=start,
        timeout=5_000,
    )


@pytest.mark.e2e
def test_v2_architecture_tab_runs_query(page, e2e_v2_base_url):
    """Open the Domains chip → switch to the ARCH tab → type accs → Run.

    Defensive: the spec validates that the UI mounts the architecture
    controls and dispatches the query. If no ClusteringRun is materialised
    in the test environment the backend returns a 400/503; the toast/error
    surface is acceptable — what matters is the UI flow doesn't break.
    """
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="ibgc-dashboard"]', timeout=30_000)

    # Open the Domains chip (it lives in the filter strip).
    domains_chip = page.get_by_role(
        "button", name=re.compile(r"^Domains", re.I)
    ).first
    domains_chip.click()

    # The query builder mounts with AND active by default. Switch to ARCH.
    query_panel = page.locator('[data-tour="domain-query"]')
    query_panel.wait_for(timeout=10_000)
    arch_tab = query_panel.get_by_role(
        "radio", name=re.compile(r"^ARCH$", re.I)
    )
    if arch_tab.count() == 0:
        # Radix ToggleGroup may render as button; fall back.
        arch_tab = query_panel.locator("button", has_text=re.compile(r"^ARCH$"))
    arch_tab.first.click()

    # Textarea + slider show up.
    textarea = query_panel.locator("textarea")
    textarea.wait_for(timeout=5_000)
    textarea.fill("PF00109, PF02801, PF00501")

    # The Sørensen-Dice ↔ Adjacency slider is a Radix slider — verify the
    # accessible role is present (we don't move it; default 0.5 is fine).
    slider = query_panel.get_by_role("slider")
    assert slider.count() >= 1

    # Press Run Query. We don't assert results — empty datasets return an
    # error toast and that's expected on a freshly-seeded instance.
    page.locator('[data-tour="run-query"]').click()
    page.wait_for_timeout(1_500)


@pytest.mark.e2e
def test_v2_generate_report_opens_tab_and_renders(page, e2e_v2_base_url, context):
    """Generate Report mints a token and opens the Report page in a new tab."""
    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="ibgc-roster"]', timeout=30_000)

    rows = page.locator('[data-testid="ibgc-roster-row"]')
    if rows.count() == 0:
        pytest.skip("No iBGCs in the dataset — skipping report test")

    # Add the first iBGC to the shortlist.
    rows.first.click(button="right")
    page.get_by_role(
        "menuitem", name=re.compile("Add to shortlist", re.I)
    ).click()

    # Open the shortlist dropdown + click Generate Report; new tab opens.
    page.locator('[data-testid="shortlist-trigger"]').click()
    with context.expect_page(timeout=30_000) as new_tab_info:
        page.locator('[data-testid="generate-report"]').click()
    report_tab = new_tab_info.value
    report_tab.wait_for_load_state("domcontentloaded")

    # Report URL carries a ?token=…
    assert "/report" in report_tab.url
    assert "token=" in report_tab.url

    # Report root + at least one section render.
    report_tab.wait_for_selector("[data-report-root]", timeout=30_000)
    report_tab.get_by_text(
        re.compile("BGC Shortlist Report", re.I)
    ).wait_for(timeout=10_000)

    # Download buttons exist (and are hidden in print via data-print-hide).
    save_html = report_tab.get_by_role(
        "button", name=re.compile("Save as HTML", re.I)
    )
    print_btn = report_tab.get_by_role(
        "button", name=re.compile("Print / PDF", re.I)
    )
    assert save_html.is_visible()
    assert print_btn.is_visible()


@pytest.mark.e2e
def test_v2_load_asset_journey(page, e2e_v2_base_url):
    """Upload a TGZ asset, verify it surfaces in the roster + UMAP + can be
    evicted via the chip's X button.

    Skips automatically when the fixture file isn't present (CI without the
    seed data) so the spec can still run on lean environments.
    """
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[4]
        / "input_test_files"
        / "files"
        / "Ga0181741_assembly_upload.tar.gz"
    )
    if not fixture.exists():
        pytest.skip(f"Fixture not present at {fixture}")

    page.set_default_timeout(60_000)
    page.goto(e2e_v2_base_url + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="ibgc-dashboard"]', timeout=30_000)

    # Click "Load Asset" and pick the fixture tarball.
    load_btn = page.locator('[data-testid="load-asset-button"]')
    load_btn.wait_for(timeout=10_000)
    file_input = page.locator('[data-testid="asset-file-input"]')
    file_input.set_input_files(str(fixture))

    # Wait for the SUBMITTED badge in the roster (means the projection ran
    # and the cache row landed in the response).
    page.locator('[data-testid="asset-submitted-badge"]').first.wait_for(
        timeout=60_000,
    )

    # Switch to UMAP — the asset point should be plotted as a "Submitted
    # asset" trace (legend text rendered by Plotly).
    page.locator('[data-testid="results-tab-umap"]').click()
    page.wait_for_timeout(1_000)
    # Plotly may or may not render the legend depending on point count;
    # the SUBMITTED badge confirmation above is the load-bearing assertion.

    # Back to roster — the asset row should still be there.
    page.locator('[data-testid="results-tab-roster"]').click()
    page.locator('[data-testid="asset-submitted-badge"]').first.wait_for(
        timeout=10_000,
    )

    # Click the X on the asset chip to evict.
    page.locator('[data-testid="asset-evict"]').click()
    page.wait_for_timeout(2_000)

    # SUBMITTED badge should disappear (UI reflects the empty cache).
    assert page.locator('[data-testid="asset-submitted-badge"]').count() == 0
