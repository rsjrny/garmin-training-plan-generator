"""Navigation helpers for the yearly planning browser regressions."""

def advanced_schedule(page):
    button = page.get_by_role("button", name="Advanced schedule options", exact=True)
    page.get_by_role("dialog").wait_for(state="hidden")
    if not button.is_visible():
        more_options(page)
    button.click()


def more_options(page):
    expansion = page.get_by_text("More plan options", exact=True)
    parent = expansion.locator("xpath=ancestor::div[contains(@class,'q-expansion-item')][1]")
    if not parent.locator(".q-expansion-item__content").is_visible():
        expansion.click()
