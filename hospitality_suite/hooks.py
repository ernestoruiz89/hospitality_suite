from hospitality_suite.schema import SCOPED, ROLES,STANDARD_SCOPED

app_name = "hospitality_suite"
app_title = "Hospitality Suite"
app_publisher = "Hospitality Suite Contributors"
app_description = "Administración de hoteles y moteles"
app_email = ""
app_license = "MIT"
required_apps = ["erpnext"]
app_include_js = ["hospitality.bundle.js"]
app_include_css = ["hospitality.bundle.css"]
after_install = "hospitality_suite.install.after_install"
after_migrate = "hospitality_suite.install.after_migrate"
before_tests="hospitality_suite.tests.setup.before_tests"
jinja={"methods":["hospitality_suite.printing"]}
permission_query_conditions = {
    dt: "hospitality_suite.security.query_" + dt.lower().replace(" ", "_") for dt in SCOPED
}
has_permission = {dt: "hospitality_suite.security.has_scope_permission" for dt in SCOPED}
for dt in STANDARD_SCOPED:
    permission_query_conditions[dt] = "hospitality_suite.security.query_" + dt.lower().replace(" ", "_")
    has_permission[dt] = "hospitality_suite.security.standard_permission"
doc_events = {
    dt: {"validate": "hospitality_suite.security.validate_standard", "before_cancel":"hospitality_suite.security.guard_cancel", "on_submit": "hospitality_suite.accounting.sync_document", "on_cancel": "hospitality_suite.accounting.sync_document","on_update_after_submit":"hospitality_suite.accounting.sync_document"}
    for dt in STANDARD_SCOPED
}
extend_doctype_class={dt:["hospitality_suite.controllers.ScopedERPNotifications"] for dt in STANDARD_SCOPED}
permission_query_conditions["GL Entry"]="hospitality_suite.security.query_gl_entry"
has_permission["GL Entry"]="hospitality_suite.security.gl_permission"
for dt in ("Account","Company","Cost Center","Warehouse","Sales Taxes and Charges Template"):
    permission_query_conditions[dt]="hospitality_suite.security.query_master_"+dt.lower().replace(" ","_")
    has_permission[dt]="hospitality_suite.security.master_permission"
override_whitelisted_methods={"frappe.desk.query_report.run":"hospitality_suite.security.run_scoped_report",
                              "frappe.desk.query_report.export_query":"hospitality_suite.security.export_scoped_report"}
doc_events.update({
    "File": {"validate": "hospitality_suite.security.validate_file"},
})
scheduler_events = {"cron": {"*/5 * * * *": ["hospitality_suite.jobs.expire_holds"]}}
