from pathlib import Path

from fastapi.testclient import TestClient

from colony.app import app

client = TestClient(app)


def test_index_links_the_split_assets_and_they_are_served():
    html = client.get("/").text
    assert "/static/app.css" in html and "/static/js/main.js" in html
    assert "<script>" not in html and "<style>" not in html  # no inline code left
    for url in ("/static/app.css", "/static/js/main.js"):
        assert client.get(url).status_code == 200, url


def test_every_module_main_imports_is_served():
    web = Path(__file__).resolve().parent.parent / "colony" / "web" / "js"
    for name in sorted(p.name for p in web.glob("*.js")):
        assert client.get(f"/static/js/{name}").status_code == 200, name


def test_web_dir_has_no_regex_literals_in_the_markdown_renderer():
    source = (Path(__file__).resolve().parent.parent / "colony" / "web" / "js" / "markdown.js").read_text()
    assert ".replace(/" not in source and ".match(" not in source and "new RegExp" not in source


def test_pages_and_scripts_are_revalidated_so_a_stale_ui_never_runs_against_a_newer_server():
    for url in ("/", "/static/app.css", "/static/js/main.js"):
        assert client.get(url).headers["cache-control"] == "no-cache", url


def test_every_element_the_scripts_look_up_exists_in_the_page():
    """A typo'd or removed id would only fail in the browser ($('x') is null); catch it here."""
    web = Path(__file__).resolve().parent.parent / "colony" / "web"
    html = (web / "index.html").read_text()
    looked_up = set()
    for script in (web / "js").glob("*.js"):
        for piece in script.read_text().split("$('")[1:]:
            looked_up.add(piece.split("'")[0])
    missing = sorted(i for i in looked_up if f'id="{i}"' not in html and i not in ("typing",))  # #typing is created by feed.js
    assert not missing, missing
    for tool_switch in ("fPermRead", "fPermWrite", "fPermBash", "fPermAsk"):   # looked up through a list in agent-editor.js
        assert f'id="{tool_switch}"' in html


def test_every_script_is_valid_javascript(tmp_path):
    """A single typo (an unescaped quote) blanks the whole page in the browser; `node --check` catches it."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node is not installed")
    web = Path(__file__).resolve().parent.parent / "colony" / "web" / "js"
    for script in sorted(web.glob("*.js")):
        copy = tmp_path / (script.stem + ".mjs")     # .mjs so node parses it as an ES module
        copy.write_text(script.read_text())
        result = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {result.stderr[:300]}"
