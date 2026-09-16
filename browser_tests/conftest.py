import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        channel = os.getenv("NEXUS_HIVE_BROWSER_CHANNEL") or None
        browser = playwright.chromium.launch(channel=channel)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.set_default_timeout(10000)
    yield page
    context.close()


@pytest.fixture(scope="session")
def static_url():
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT / "frontend"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture(scope="session")
def live_url(tmp_path_factory):
    directory = tmp_path_factory.mktemp("browser-runtime")
    database = directory / "synthetic.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE products (product_id INTEGER, product_name TEXT, category TEXT,
                unit_price REAL, margin_percentage REAL);
            CREATE TABLE regions (region_id INTEGER, region_name TEXT, manager TEXT);
            CREATE TABLE sales (transaction_id TEXT, date TEXT, product_id INTEGER,
                region_id INTEGER, quantity INTEGER, discount_applied REAL,
                gross_revenue REAL, net_revenue REAL, profit REAL);
            INSERT INTO products VALUES (1, 'Synthetic product', 'Software', 25, 0.2);
            INSERT INTO regions VALUES (1, 'North', 'Synthetic manager'),
                (2, 'South', 'Synthetic manager');
            INSERT INTO sales VALUES
                ('SYN-1', '2026-01-01', 1, 1, 6, 0, 150, 150, 30),
                ('SYN-2', '2026-01-02', 1, 2, 3, 0, 75, 75, 15);
        """)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "NEXUS_HIVE_DB_PATH": str(database),
        "NEXUS_HIVE_AUDIT_PATH": str(directory / "audit.jsonl"),
        "NEXUS_HIVE_RUNTIME_STORE_PATH": str(directory / "runtime-events.db"),
        "NEXUS_HIVE_WAREHOUSE_ADAPTER": "sqlite-demo",
        "NEXUS_HIVE_OLLAMA_URL": "http://127.0.0.1:1/api/generate",
        "NEXUS_HIVE_ALLOW_HEURISTIC_FALLBACK": "1",
        "OPENAI_KILL_SWITCH": "1",
    }
    url = f"http://127.0.0.1:{port}"
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    pytest.fail((directory / "server.log").read_text())
                try:
                    with urllib.request.urlopen(f"{url}/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except urllib.error.URLError:
                    if time.monotonic() >= deadline:
                        pytest.fail("Synthetic local runtime did not become healthy")
                    threading.Event().wait(0.05)
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def capture(tmp_path):
    directory = Path(os.getenv("NEXUS_HIVE_BROWSER_ARTIFACTS", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    phase = os.getenv("NEXUS_HIVE_BROWSER_PHASE", "check")

    def save(page, name):
        page.screenshot(path=str(directory / f"Nexus-Hive-{phase}-{name}.png"))

    return save
