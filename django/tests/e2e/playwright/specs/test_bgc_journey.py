import re
import pytest

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except Exception:  # fallback for static analysis or missing types
    PlaywrightTimeoutError = Exception  # type: ignore


@pytest.mark.e2e
def test_user_journey_landing_to_download(page, e2e_base_url):
    """
    Light smoke E2E covering:
      landing_page -> search (BGC Class Name='Polyketide') -> results_view (first row)
      -> bgc_page -> download_bgc (gbk)
    Runs against staging; resilient to async search by waiting for the results table.
    """

    # Use generous timeouts to account for async background processing on staging
    page.set_default_timeout(120_000)  # 120s

    # 1) Landing page
    page.goto(e2e_base_url + "/", wait_until="domcontentloaded")

    # Click the prominent card link: Explore BGCs → goes to search
    page.get_by_role("link", name=re.compile("^Explore BGCs$", re.I)).click()

    # Best-effort: dismiss cookie banner if present (e.g., OneTrust)
    try:
        page.wait_for_timeout(500)  # small settle delay
        if page.locator("#onetrust-accept-btn-handler").is_visible(timeout=1000):
            page.locator("#onetrust-accept-btn-handler").click()
        else:
            # fallback by button text
            page.get_by_role(
                "button", name=re.compile("accept( all)? cookies|accept all", re.I)
            ).click(timeout=1000)
    except Exception:
        pass

    # 2) Search page (Advanced tab is default). Wait for form and fill BGC Class Name; use field id to be robust.
    page.wait_for_selector("#search-form", timeout=30_000)
    page.locator("#id_bgc_class_name").fill("Polyketide")

    page.locator("#pag_button_as").click()

    # 3) Results view — page may first show a spinner and poll until ready.
    # Wait until the results table and at least one row appear.
    page.wait_for_selector("#explore-table", timeout=180_000)
    page.wait_for_selector("tbody .js-bgc-row", timeout=60_000)

    # Click the first result row. It should open BGC details in a new tab via window.open.
    # However, in some environments popups may be blocked or the app may navigate in the same tab.
    first_row = page.locator("tbody .js-bgc-row").first
    bgc_id = first_row.get_attribute("data-bgc-id")
    assert bgc_id, "Expected a data-bgc-id on the first results row"

    try:
        with page.expect_popup(timeout=5_000) as popup_info:
            first_row.click()
        bgc_page = popup_info.value
        bgc_page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeoutError:
        # Fallback: Navigate current page directly to the BGC page
        page.goto(f"{e2e_base_url}/bgc/?bgc_id={bgc_id}", wait_until="domcontentloaded")
        bgc_page = page

    # Sanity check: we navigated to the BGC details page
    assert "/bgc" in bgc_page.url

    # Wait until BGC data is prepared (the download endpoint requires a cached record)
    # Instead of a manual evaluate/poll loop, use Playwright's wait_for_response to
    # observe the server's /search/status/ response indicating SUCCESS. This keeps
    # the waiting logic simpler and relies on the browser's network activity.
    url_qs = bgc_page.url.split("?", 1)[1] if "?" in bgc_page.url else ""
    if url_qs:
        status_path = f"/search/status/?{url_qs}"
        try:
            # Wait up to 90s for a network response whose JSON has status === 'SUCCESS'
            def _predicate(response):
                try:
                    return (
                        response.request.url.endswith(status_path)
                        and response.status == 200
                        and response.json()
                        and response.json().get("status") == "SUCCESS"
                    )
                except Exception:
                    return False

            bgc_page.wait_for_response(lambda resp: _predicate(resp), timeout=90_000)
        except Exception:
            # Fallback: some environments may not issue a network response we can
            # observe (e.g. if the page itself navigates). Wait for a known DOM
            # marker that indicates the plot/data is present (or spinner removed).
            try:
                bgc_page.wait_for_selector("#bgc-plot", timeout=30_000)
            except Exception:
                # As a last resort, ensure the download form is present
                bgc_page.wait_for_selector("form.download-form", timeout=30_000)

    # 4) Download GBK from BGC details page
    # Select 'GenBank' in the format dropdown (value='gbk') and click Download.
    bgc_page.locator("#output_type").select_option("gbk")

    with bgc_page.expect_download() as dl_info:
        bgc_page.get_by_role("button", name=re.compile("^Download$", re.I)).click()
    download = dl_info.value

    # Assert the suggested filename looks like a GBK file
    suggested = download.suggested_filename
    assert suggested.lower().endswith(".gbk"), f"Expected .gbk file, got: {suggested}"
