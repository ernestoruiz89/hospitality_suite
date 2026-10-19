from hospitality_suite.schema import SCOPED, ROLES

app_name = "hospitality_suite"
app_title = "Hospitality Suite"
app_publisher = "Hospitality Suite Contributors"
app_description = "Administración de hoteles y moteles"
app_email = ""
app_license = "MIT"
required_apps = ["erpnext"]
app_include_js = ["/assets/hospitality_suite/js/hospitality.js"]
app_include_css = ["/assets/hospitality_suite/css/hospitality.css"]
after_install = "hospitality_suite.install.after_install"
after_migrate = "hospitality_suite.install.after_migrate"
permission_query_conditions = {
    dt: "hospitality_suite.security.query_" + dt.lower().replace(" ", "_") for dt in SCOPED
}
has_permission = {dt: "hospitality_suite.security.has_scope_permission" for dt in SCOPED}
doc_events = {
    "Sales Invoice": {"on_submit": "hospitality_suite.accounting.sync_document", "on_cancel": "hospitality_suite.accounting.sync_document"},
    "Payment Entry": {"on_submit": "hospitality_suite.accounting.sync_document", "on_cancel": "hospitality_suite.accounting.sync_document"},
    "File": {"validate": "hospitality_suite.security.validate_file"},
}
scheduler_events = {"cron": {"*/5 * * * *": ["hospitality_suite.jobs.expire_holds"]}}
