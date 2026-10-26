"""Exercise Suite commands across real Frappe WSGI request boundaries on a disposable PMS site."""

from threading import Thread
from unittest.mock import patch
from uuid import uuid4

import frappe
import requests
from frappe.auth import CookieManager, LoginManager
from frappe.utils import get_test_client, set_request


def _wsgi_request(site, sid, path, body=None):
    result = {}

    def work():
        try:
            with patch("frappe.app.get_site_name", return_value=site):
                client = get_test_client()
                client.set_cookie("sid", sid, domain=site)
                if body is None:
                    result["response"] = client.get(path, base_url=f"http://{site}")
                else:
                    result["response"] = client.post(path, json=body, base_url=f"http://{site}")
        except BaseException as exc:
            result["error"] = exc

    thread = Thread(target=work)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    response = result["response"]
    return response.status_code, response.json, response.get_data(as_text=True)


def _tcp_request(site, sid, csrf, path, body=None):
    headers = {"Host": site, "X-Frappe-Site-Name": site, "Cookie": f"sid={sid}",
        "X-Frappe-CSRF-Token": csrf}
    url = "http://127.0.0.1:8087" + path
    response = requests.post(url, json=body, headers=headers, timeout=20) if body is not None \
        else requests.get(url, headers=headers, timeout=20)
    return response.status_code, response.json(), response.text


def _run(tcp=False):
    site = frappe.local.site
    if not site.startswith("hs-pms-smoke") or "erpnext" in frappe.get_installed_apps():
        frappe.throw("Use únicamente un sitio temporal Frappe sin ERPNext")
    set_request(path="/")
    frappe.local.cookie_manager = CookieManager()
    frappe.local.login_manager = LoginManager()
    frappe.local.login_manager.login_as("Administrator")
    sid = frappe.session.sid
    csrf = frappe.session.csrf_token
    frappe.db.commit()
    request = (lambda path, body=None: _tcp_request(site, sid, csrf, path, body)) if tcp else \
        (lambda path, body=None: _wsgi_request(site, sid, path, body))
    suffix = uuid4().hex[:12]
    property_name = None
    try:
        status, payload, detail = request("/api/method/hospitality_suite.api.create_property", {
            "data": {"property_name": "HTTP Retry " + suffix,
                "new_organization": {"legal_name": "HTTP Retry Legal " + suffix},
                "currency": "USD", "mode": "Hotel"},
            "request_key": "http-property-" + suffix,
        })
        assert status == 200, detail[:500]
        property_name = payload["message"]["property"]
        body = {"property_name": property_name, "action": "pms_customer",
            "request_key": "http-customer-" + suffix,
            "data": {"party_name": "HTTP Guest " + suffix}}
        first_status, first_body, first_detail = request("/api/method/hospitality_suite.api.execute", body)
        assert first_status == 200, first_detail[:500]
        # Treat the first response as lost. A fresh request must replay its committed result.
        second_status, second_body, second_detail = request("/api/method/hospitality_suite.api.execute", body)
        assert second_status == 200, second_detail[:500]
        assert first_body["message"] == second_body["message"]
        assert frappe.db.count("HS Party", {"property": property_name}) == 1
        assert frappe.db.count("HS Request", {"property": property_name,
            "operation": "pms_customer"}) == 1
        outcome = {"provider": "pms", "transport": "tcp" if tcp else "wsgi",
            "http_status": second_status, "party": second_body["message"]["party"],
            "parties_created": 1}
    finally:
        if property_name:
            organization = frappe.db.get_value("HS Property", property_name, "organization")
            for doctype in ("HS Party", "HS Audit Event", "HS Request"):
                frappe.db.delete(doctype, {"property": property_name})
            frappe.db.delete("HS Property", {"name": property_name})
            if organization:
                frappe.db.delete("HS Organization", {"name": organization})
            frappe.db.commit()
    assert frappe.db.count("HS Property", {"name": property_name}) == 0
    assert frappe.db.count("HS Party", {"property": property_name}) == 0
    outcome["fixture_removed"] = True
    return outcome


def run():
    return _run()


def run_tcp():
    return _run(tcp=True)
