"""Check public React delivery through Frappe's real website router."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import get_test_client

def run():
    site = frappe.local.site
    folder = Path(frappe.get_app_path("hospitality_suite", "public", "frontend"))
    client = get_test_client()
    base_url = f"http://{site}"
    launch = client.get("/hospitality-launch", base_url=base_url)
    assert launch.status_code == 301 and launch.headers["Location"] == "/hospitality/app"

    old_public = client.get("/hospitality", base_url=base_url)
    assert old_public.status_code == 301 and old_public.headers["Location"] == "/hospitality-book"
    for path, asset in (("/hospitality-book", "portal-"),
                        ("/hospitality/app/rooms", "index-"),
                        ("/hospitality/app/availability", "index-"),
                        ("/hospitality/app/rates", "index-"),
                        ("/hospitality/app/room-calendar", "index-"),
                        ("/hospitality/app/reservations", "index-"),
                        ("/hospitality/app/stays", "index-"),
                        ("/hospitality/app/reservations/draft/new", "index-"),
                        ("/hospitality/app/retention", "index-")):
        response = client.get(path, base_url=base_url)
        html = response.get_data(as_text=True)
        assert response.status_code == 200 and asset in html and "window.csrf_token" in html

    sample = {"property_name": "Hotel </script><script>alert(1)</script>",
        "status": "Hold", "starts_at": datetime(2026, 10, 24, 10),
        "ends_at": datetime(2026, 10, 24, 18),
        "hold_until": datetime(2026, 10, 24, 10, 15), "request_until": None,
        "currency": "NIO", "amount": "100.00", "time_zone": "America/Managua",
        "experiences_total": "0.00", "estimated_total": "100.00"}
    with patch("hospitality_suite.www.hospitality_confirmation.confirmation", return_value=sample):
        response = client.get("/hospitality-confirmation?token=synthetic", base_url=base_url)
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and "confirmation-" in html
    assert "window.hs_confirmation" in html and "2026-10-24 10:00:00" in html
    assert "</script><script>alert(1)</script>" not in html and "\\u003c/script" in html

    for name in ("index.html", "portal.html", "confirmation.html"):
        assert (folder / name).is_file()
    return {"public_react_routes": 10}
