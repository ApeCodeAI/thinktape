"""Playwright E2E tests for the braindump frontend.

Requirements:
  - Backend running on :8080 (uv run python -m braindump web)
  - Frontend dev server on :5173 (cd frontend && npm run dev)
  - Screenshots saved to /tmp/braindump-frontend-screenshots/
"""

import re
import subprocess
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"
SCREENSHOTS_DIR = Path("/tmp/braindump-frontend-screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session", autouse=True)
def servers():
    """Start backend and frontend dev servers for the test session."""
    # Start backend
    backend = subprocess.Popen(
        ["uv", "run", "python", "-m", "braindump", "web"],
        cwd="/tmp/braindump-t0",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Start frontend dev server
    frontend = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd="/tmp/braindump-t0/frontend",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for servers to be ready
    time.sleep(5)

    yield

    frontend.terminate()
    backend.terminate()
    frontend.wait(timeout=5)
    backend.wait(timeout=5)


def screenshot(page: Page, name: str):
    """Take desktop and mobile screenshots."""
    # Desktop
    page.set_viewport_size({"width": 1280, "height": 800})
    time.sleep(0.5)
    page.screenshot(path=str(SCREENSHOTS_DIR / f"{name}-desktop.png"), full_page=True)

    # Mobile
    page.set_viewport_size({"width": 375, "height": 812})
    time.sleep(0.5)
    page.screenshot(path=str(SCREENSHOTS_DIR / f"{name}-mobile.png"), full_page=True)

    # Reset to desktop
    page.set_viewport_size({"width": 1280, "height": 800})


# ── Timeline ──────────────────────────────────────────────────

def test_timeline_loads(page: Page):
    """Timeline page loads and shows notes."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Should have some note cards
    cards = page.locator('[data-slot="card"]')
    expect(cards.first).to_be_visible(timeout=10000)

    screenshot(page, "01-timeline")


def test_timeline_infinite_scroll(page: Page):
    """Infinite scroll loads more notes."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Count initial cards
    initial_count = page.locator('[data-slot="card"]').count()
    assert initial_count > 0

    # Scroll to bottom to trigger load more
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(2000)

    # Should have loaded more
    new_count = page.locator('[data-slot="card"]').count()
    assert new_count >= initial_count

    screenshot(page, "02-timeline-scrolled")


def test_search_and_filter(page: Page):
    """Search input filters notes."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Type in search box
    search = page.locator('input[placeholder="Search notes..."]')
    expect(search).to_be_visible()
    search.fill("投资")
    page.wait_for_timeout(1000)

    # Should show results
    screenshot(page, "03-search-results")

    # Clear search
    search.fill("")
    page.wait_for_timeout(1000)


def test_type_filter(page: Page):
    """Type filter chips work."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Click "Image" filter badge (less ambiguous than "Text")
    page.locator('[data-slot="badge"]', has_text="Image").first.click()
    page.wait_for_timeout(1000)

    screenshot(page, "04-type-filter")


# ── Note Detail ───────────────────────────────────────────────

def test_note_detail_loads(page: Page):
    """Clicking a note card opens detail page with markdown rendered."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Click first note card
    page.locator('[data-slot="card"]').first.click()
    page.wait_for_url(re.compile(r"/note/\d+"))
    page.wait_for_timeout(1000)

    # Should see "Back to timeline" link
    expect(page.locator("text=Back to timeline")).to_be_visible()

    # Should have content rendered
    expect(page.locator('[data-slot="separator"]').first).to_be_visible()

    screenshot(page, "05-note-detail")


def test_note_edit_cancel(page: Page):
    """Edit mode opens and cancel works."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Navigate to a note
    page.locator('[data-slot="card"]').first.click()
    page.wait_for_url(re.compile(r"/note/\d+"))
    page.wait_for_timeout(1000)

    # Click Edit
    edit_btn = page.locator("button", has_text="Edit")
    if edit_btn.is_visible():
        edit_btn.click()
        page.wait_for_timeout(500)

        screenshot(page, "06-note-edit-mode")

        # Click Cancel
        page.locator("button", has_text="Cancel").click()
        page.wait_for_timeout(500)


# ── Dashboard ─────────────────────────────────────────────────

def test_dashboard_loads(page: Page):
    """Dashboard page loads with stats and charts."""
    page.goto(f"{BASE_URL}/dashboard")
    page.wait_for_timeout(2000)

    # Should see stat cards
    cards = page.locator('[data-slot="card"]')
    expect(cards.first).to_be_visible(timeout=10000)

    # Should have multiple cards (at least 4 stat cards)
    assert cards.count() >= 4

    screenshot(page, "07-dashboard")


def test_dashboard_charts_render(page: Page):
    """Dashboard charts are rendered."""
    page.goto(f"{BASE_URL}/dashboard")
    page.wait_for_timeout(3000)

    # Check for recharts SVG elements
    svg_elements = page.locator("svg.recharts-surface")
    assert svg_elements.count() >= 1

    screenshot(page, "08-dashboard-charts")


# ── Calendar ──────────────────────────────────────────────────

def test_calendar_loads(page: Page):
    """Calendar page loads with monthly grid."""
    page.goto(f"{BASE_URL}/calendar")
    page.wait_for_timeout(2000)

    # Should see month name
    expect(page.locator("h2")).to_be_visible()

    # Should see weekday headers (Mon, Tue, ...)
    expect(page.locator("text=Mon")).to_be_visible()

    screenshot(page, "09-calendar")


def test_calendar_date_selection(page: Page):
    """Clicking a date with notes shows day notes."""
    page.goto(f"{BASE_URL}/calendar")
    page.wait_for_timeout(2000)

    # Find a day button that has a count (number below date)
    day_buttons = page.locator("button").filter(has=page.locator("span"))
    # Click the first one that has notes (has two span children — day number + count)
    for i in range(day_buttons.count()):
        btn = day_buttons.nth(i)
        spans = btn.locator("span")
        if spans.count() >= 2:
            btn.click()
            page.wait_for_timeout(2000)
            break

    screenshot(page, "10-calendar-day-selected")


def test_calendar_month_navigation(page: Page):
    """Month navigation works."""
    page.goto(f"{BASE_URL}/calendar")
    page.wait_for_timeout(2000)

    # Get current month name
    month_heading = page.locator("h2").inner_text()

    # Click previous month button (the left arrow near the month heading)
    prev_btn = page.locator("h2").locator("..").locator("button").first
    prev_btn.click()
    page.wait_for_timeout(1000)

    # Month should have changed
    new_heading = page.locator("h2").inner_text()
    assert new_heading != month_heading

    screenshot(page, "11-calendar-prev-month")


# ── Dark Mode ─────────────────────────────────────────────────

def test_dark_mode_toggle(page: Page):
    """Dark mode toggle works across pages."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Click theme toggle (the ghost button with sun/moon icon)
    theme_btn = page.locator('button[aria-label="Toggle dark mode"]')
    expect(theme_btn).to_be_visible()
    theme_btn.click()
    page.wait_for_timeout(500)

    # HTML should have dark class
    has_dark = page.evaluate("document.documentElement.classList.contains('dark')")
    assert has_dark

    screenshot(page, "12-timeline-dark")

    # Navigate to dashboard in dark mode
    page.goto(f"{BASE_URL}/dashboard")
    page.wait_for_timeout(2000)
    screenshot(page, "13-dashboard-dark")

    # Navigate to calendar in dark mode
    page.goto(f"{BASE_URL}/calendar")
    page.wait_for_timeout(2000)
    screenshot(page, "14-calendar-dark")

    # Toggle back to light
    theme_btn = page.locator('button[aria-label="Toggle dark mode"]')
    theme_btn.click()
    page.wait_for_timeout(500)


# ── Mobile Responsive ─────────────────────────────────────────

def test_mobile_layout(page: Page):
    """Mobile layout shows bottom nav instead of header nav."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    screenshot(page, "15-mobile-timeline")

    # Navigate via bottom nav to dashboard using JS click (fixed-position nav)
    page.evaluate("document.querySelector('[data-testid=mobile-nav] a[href=\"/dashboard\"]').click()")
    page.wait_for_timeout(2000)
    expect(page).to_have_url(re.compile(r"/dashboard"))
    screenshot(page, "16-mobile-dashboard")

    # Navigate to calendar
    page.evaluate("document.querySelector('[data-testid=mobile-nav] a[href=\"/calendar\"]').click()")
    page.wait_for_timeout(2000)
    expect(page).to_have_url(re.compile(r"/calendar"))
    screenshot(page, "17-mobile-calendar")

    # Reset viewport
    page.set_viewport_size({"width": 1280, "height": 800})


# ── Create / Edit / Delete ────────────────────────────────────

def test_create_note(page: Page):
    """Create a new note via FAB dialog."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Click FAB (the + button)
    fab = page.locator("button").filter(has=page.locator("svg path[d='M5 12h14']"))
    fab.click()
    page.wait_for_timeout(500)

    # Fill in content
    textarea = page.locator("textarea")
    expect(textarea).to_be_visible()
    textarea.fill("E2E test note — created by Playwright")

    # Fill in tags
    page.locator('input[placeholder="Tags (comma separated)"]').fill("test,e2e")

    screenshot(page, "18-create-note-dialog")

    # Click Create
    page.locator("button", has_text="Create").click()
    page.wait_for_timeout(2000)

    screenshot(page, "19-after-create")


def test_delete_note(page: Page):
    """Delete a note (the one we just created)."""
    page.goto(BASE_URL)
    page.wait_for_timeout(2000)

    # Find the note we created and navigate to it
    test_card = page.locator('[data-slot="card"]', has_text="E2E test note")
    if test_card.count() > 0:
        test_card.first.click()
        page.wait_for_url(re.compile(r"/note/\d+"))
        page.wait_for_timeout(1000)

        # Click Delete
        page.locator("button", has_text="Delete").click()
        page.wait_for_timeout(500)

        screenshot(page, "20-delete-confirm")

        # Confirm
        page.locator('[role="dialog"] button', has_text="Delete").click()
        page.wait_for_timeout(1000)

        # Should be back on timeline
        expect(page).to_have_url(BASE_URL + "/")
