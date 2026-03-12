"""Playwright E2E tests for braindump Web UI.

Starts the web server, tests timeline, search, note detail, and image display
on both desktop and mobile viewports.

Screenshots saved to /tmp/braindump-test-screenshots/
"""

import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

SCREENSHOTS_DIR = Path("/tmp/braindump-test-screenshots")
WEB_BASE = "http://127.0.0.1:8080"


@pytest.fixture(scope="session", autouse=True)
def web_server():
    """Start the braindump web server for the test session."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["BRAINDUMP_DATA_DIR"] = os.path.expanduser("~/braindump-data")

    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "braindump", "web"],
        cwd="/Users/cwd/.openclaw/workspace/braindump",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    # Wait for server to be ready
    import urllib.request
    import urllib.error

    for attempt in range(30):
        try:
            urllib.request.urlopen(WEB_BASE, timeout=2)
            break
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    else:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        pytest.fail(
            f"Web server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield proc

    # Teardown: kill the process group
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Desktop viewport tests
# ---------------------------------------------------------------------------


class TestDesktopTimeline:
    """Tests on desktop viewport (default 1280x720)."""

    def test_timeline_loads(self, page: Page):
        """Timeline page loads and shows notes."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        # Page title should contain braindump
        expect(page).to_have_title(re.compile(r"braindump"))

        # Should have the site header
        header = page.locator(".site-header")
        expect(header).to_be_visible()

        # Should have the logo
        logo = page.locator(".logo")
        expect(logo).to_have_text("braindump")

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_timeline.png"))

    def test_timeline_has_notes(self, page: Page):
        """Timeline should display note cards."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        # Should have at least one date group
        date_groups = page.locator(".date-group")
        count = date_groups.count()
        assert count > 0, "No date groups found — are there notes in the database?"

        # Should have note cards
        note_cards = page.locator(".note-card")
        card_count = note_cards.count()
        assert card_count > 0, f"No note cards found (date groups: {count})"

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_notes.png"))

    def test_search_functionality(self, page: Page):
        """Search should filter notes via FTS."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        search_input = page.locator('input[name="q"]')
        expect(search_input).to_be_visible()

        # Search for a common Chinese character that should exist in Flomo imports
        search_input.fill("的")
        search_input.press("Enter")

        page.wait_for_load_state("networkidle")

        # URL should have q parameter
        assert "q=" in page.url

        # Should show some results (or a message)
        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_search_results.png"))

    def test_type_filter(self, page: Page):
        """Filter by type should work."""
        page.goto(f"{WEB_BASE}/?type=text")
        page.wait_for_load_state("networkidle")

        # Should load without error
        expect(page.locator(".site-header")).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_filter_text.png"))

    def test_note_detail_page(self, page: Page):
        """Navigate to a note detail page directly, then verify it works."""
        # Go to detail page for note 1 directly (clicking cards may follow
        # external links rendered in note content)
        page.goto(f"{WEB_BASE}/note/1")
        page.wait_for_load_state("networkidle")

        # Should be on a note detail page
        assert "/note/" in page.url

        # Should have note content
        detail = page.locator(".note-detail")
        expect(detail).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_note_detail.png"))

    def test_note_detail_has_back_link(self, page: Page):
        """Note detail page should have a back link."""
        page.goto(f"{WEB_BASE}/note/1")
        page.wait_for_load_state("networkidle")

        back_link = page.locator("a.back-link, a[href='/']").first
        expect(back_link).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_detail_back.png"))

    def test_images_display(self, page: Page):
        """Check that images (from Flomo import) are displayed correctly."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        # Look for any images in note cards or attachments
        images = page.locator(".note-card img, .note-images img, .attachment-image")
        if images.count() > 0:
            # First visible image should have loaded (natural width > 0)
            first_img = images.first
            expect(first_img).to_be_visible()

            # Verify it loaded (not broken)
            loaded = first_img.evaluate(
                "img => img.complete && img.naturalWidth > 0"
            )
            assert loaded, "Image is broken (did not load)"

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_images.png"))

    def test_pagination(self, page: Page):
        """Pagination should work if there are enough notes."""
        page.goto(f"{WEB_BASE}/?size=5")
        page.wait_for_load_state("networkidle")

        # Check if pagination exists (may not if < 5 notes total)
        pagination = page.locator(".pagination")
        if pagination.count() > 0:
            # Should have page info
            page_info = page.locator(".page-info")
            if page_info.count() > 0:
                text = page_info.text_content()
                assert text, "Page info should have text"

            # Try navigating to page 2
            next_link = page.locator('a[href*="page=2"]')
            if next_link.count() > 0:
                next_link.click()
                page.wait_for_load_state("networkidle")
                assert "page=2" in page.url

        page.screenshot(path=str(SCREENSHOTS_DIR / "desktop_pagination.png"))

    def test_static_css_loads(self, page: Page):
        """Verify CSS is loaded (page should have styled elements)."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        # Check that CSS is applied — header should have a background color
        header = page.locator(".site-header")
        bg = header.evaluate("el => getComputedStyle(el).backgroundColor")
        assert bg != "rgba(0, 0, 0, 0)", f"Header has no background color: {bg}"


# ---------------------------------------------------------------------------
# Mobile viewport tests
# ---------------------------------------------------------------------------


class TestMobileTimeline:
    """Tests on mobile viewport (iPhone-like 375x812)."""

    @pytest.fixture(autouse=True)
    def mobile_viewport(self, page: Page):
        page.set_viewport_size({"width": 375, "height": 812})

    def test_mobile_timeline_loads(self, page: Page):
        """Timeline loads on mobile viewport."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        expect(page).to_have_title(re.compile(r"braindump"))
        expect(page.locator(".site-header")).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "mobile_timeline.png"))

    def test_mobile_search(self, page: Page):
        """Search is usable on mobile."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        search_input = page.locator('input[name="q"]')
        expect(search_input).to_be_visible()

        # Verify the search input is accessible (not overflowing)
        box = search_input.bounding_box()
        assert box is not None, "Search input not rendered"
        assert box["width"] > 50, "Search input too narrow on mobile"

        page.screenshot(path=str(SCREENSHOTS_DIR / "mobile_search.png"))

    def test_mobile_note_detail(self, page: Page):
        """Note detail page works on mobile."""
        page.goto(f"{WEB_BASE}/note/1")
        page.wait_for_load_state("networkidle")

        detail = page.locator(".note-detail")
        expect(detail).to_be_visible()

        # Content should not overflow viewport
        body_width = page.evaluate("document.body.scrollWidth")
        assert body_width <= 376, f"Content overflows on mobile: body width = {body_width}px"

        page.screenshot(path=str(SCREENSHOTS_DIR / "mobile_note_detail.png"))

    def test_mobile_images(self, page: Page):
        """Images should be responsive on mobile."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        images = page.locator(".note-card img")
        if images.count() > 0:
            first_img = images.first
            box = first_img.bounding_box()
            if box:
                assert box["width"] <= 375, "Image wider than mobile viewport"

        page.screenshot(path=str(SCREENSHOTS_DIR / "mobile_images.png"))


# ---------------------------------------------------------------------------
# Tablet viewport tests
# ---------------------------------------------------------------------------


class TestTabletTimeline:
    """Tests on tablet viewport (768x1024)."""

    @pytest.fixture(autouse=True)
    def tablet_viewport(self, page: Page):
        page.set_viewport_size({"width": 768, "height": 1024})

    def test_tablet_timeline(self, page: Page):
        """Timeline loads and looks reasonable on tablet."""
        page.goto(WEB_BASE)
        page.wait_for_load_state("networkidle")

        expect(page.locator(".site-header")).to_be_visible()

        page.screenshot(path=str(SCREENSHOTS_DIR / "tablet_timeline.png"))


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestAPI:
    """Test the JSON API endpoints."""

    def test_api_notes(self, page: Page):
        """GET /api/notes returns JSON."""
        resp = page.request.get(f"{WEB_BASE}/api/notes")
        assert resp.ok, f"API returned {resp.status}"
        data = resp.json()
        assert "notes" in data
        assert "total" in data
        assert isinstance(data["notes"], list)

    def test_api_notes_with_filters(self, page: Page):
        """GET /api/notes with filters."""
        resp = page.request.get(f"{WEB_BASE}/api/notes?type=text&size=5")
        assert resp.ok
        data = resp.json()
        assert data["size"] == 5
        for note in data["notes"]:
            assert note["media_type"] == "text"

    def test_api_notes_search(self, page: Page):
        """GET /api/notes with search query."""
        resp = page.request.get(f"{WEB_BASE}/api/notes?q=的")
        assert resp.ok
        data = resp.json()
        assert isinstance(data["notes"], list)
