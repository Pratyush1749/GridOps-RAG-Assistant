"""Manual end-to-end smoke script for the GridOps API (not a pytest test).

Registers a user, uploads a small generated PDF, and asks two grid-ops
questions about it. Requires the API to be running (`python scripts/serve.py`)
and Postgres/Qdrant reachable.

Generates its own throwaway PDF fixture (via reportlab) instead of pointing
at a hardcoded local file path, so it runs unmodified on any machine.
"""

import tempfile
import time
from pathlib import Path

import requests
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

BASE_URL = "http://localhost:8000"

FIXTURE_TEXT = [
    "Grid Ops Test Fixture — Feeder 12-North",
    "",
    "Feeder 12-North is a 12.47 kV distribution feeder served from the",
    "Riverside substation. It has experienced three sustained outages in the",
    "past year, all classified P2, with an average MTTR of 95 minutes.",
    "",
    "The most recent outage on Feeder 12-North was caused by vegetation",
    "contact and was restored by a crew from Crew Bravo after a 40-minute",
    "response time.",
]


def _build_fixture_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    text = c.beginText(72, 720)
    text.setFont("Helvetica", 12)
    for line in FIXTURE_TEXT:
        text.textLine(line)
    c.drawText(text)
    c.save()


print("Waiting for server to be ready...")
for _ in range(30):
    try:
        if requests.get(f"{BASE_URL}/healthz", timeout=2).status_code == 200:
            break
    except Exception:
        time.sleep(2)
else:
    print("Server not ready.")
    exit(1)

print("\n1. Registering user...")
res = requests.post(
    f"{BASE_URL}/api/v1/auth/register",
    json={"username": "auditor@demo.local", "password": "password123"},
    timeout=60,
)
print(res.status_code, res.text)

print("\n2. Logging in...")
res = requests.post(
    f"{BASE_URL}/api/v1/auth/login",
    json={"username": "auditor@demo.local", "password": "password123"},
    timeout=60,
)
print(res.status_code, res.text)
if res.status_code != 200:
    print("Login failed, aborting.")
    exit(1)

token = res.json().get("token")
headers = {"Authorization": f"Bearer {token}"}

print("\n3. Uploading document...")
with tempfile.TemporaryDirectory() as tmp_dir:
    fixture_path = Path(tmp_dir) / "feeder-12-north-fixture.pdf"
    _build_fixture_pdf(fixture_path)

    with fixture_path.open("rb") as f:
        res = requests.post(
            f"{BASE_URL}/api/v1/documents/upload",
            headers=headers,
            files={"file": ("feeder-12-north-fixture.pdf", f, "application/pdf")},
            timeout=300,
        )
print(res.status_code, res.text)

time.sleep(5)  # wait for embedding

print("\n4. Query 1: which substation serves Feeder 12-North?")
res = requests.post(
    f"{BASE_URL}/api/v1/query",
    headers=headers,
    json={"question": "Which substation serves Feeder 12-North?", "enable_crag": False},
    timeout=120,
)
print(res.status_code, res.text)

print("\n5. Query 2: what was the cause of the most recent outage on Feeder 12-North?")
res = requests.post(
    f"{BASE_URL}/api/v1/query",
    headers=headers,
    json={
        "question": "What was the cause of the most recent outage on Feeder 12-North?",
        "enable_crag": False,
    },
    timeout=120,
)
print(res.status_code, res.text)
