from app.ui.templates import render_shell


def test_render_shell_exposes_disclosure_affordance():
    html = render_shell(
        title="HARRY Fleet",
        active_page="fleet",
        page_title="Fleet",
        page_subtitle="Live status",
        sidebar_sections=[
            {"label": "Fleet", "items": [{"label": "Overview", "href": "/"}]},
            {"label": "Inventory", "items": [{"label": "Summary", "href": "/inventory"}]},
        ],
        actions=[],
        content="",
    )

    assert "details summary::after" in html
    assert "summary:focus-visible" in html
    assert "aria-expanded" in html
    assert "Fleet overview" in html
    assert 'class="topnav-link active"' in html
