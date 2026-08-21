"""Every data table must sit inside .table-wrap so narrow (mobile) viewports
scroll the table horizontally instead of overflowing the page."""

from pathlib import Path

TEMPLATES = Path("app/templates")


def test_all_tables_are_wrapped_in_table_wrap():
    violations = []
    for tmpl in sorted(TEMPLATES.rglob("*.html")):
        lines = tmpl.read_text().splitlines()
        for i, line in enumerate(lines):
            if "<table" not in line:
                continue
            prior = "\n".join(lines[max(0, i - 3) : i])
            if '<div class="table-wrap">' not in prior:
                violations.append(f"{tmpl}:{i + 1} <table> has no table-wrap wrapper")
    assert not violations, "\n".join(violations)


def test_mobile_css_caps_widget_min_width(client, login):
    login()
    css = client.get("/static/style.css").text
    assert ".widget, .widget-grid > * { min-width: 0; }" in css
