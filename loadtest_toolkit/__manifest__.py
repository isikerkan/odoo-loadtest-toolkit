# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Load Test Toolkit",
    "summary": "Generate load-test data, define scenarios and run Locust from Odoo",
    "version": "18.0.4.1.0",
    "category": "Extra Tools",
    "website": "https://github.com/sverkanisik/odoo-loadtest-toolkit",
    "author": "isikerkan, sverkanisik",
    "license": "AGPL-3",
    "application": True,
    "installable": True,
    "depends": ["sale"],
    "external_dependencies": {"python": ["locust", "requests", "websocket-client"]},
    "data": [
        "security/ir.model.access.csv",
        "data/loadtest_journey_data.xml",
        "data/ir_cron_data.xml",
        "views/loadtest_batch_views.xml",
        "views/loadtest_scenario_views.xml",
        "views/loadtest_run_views.xml",
        "views/loadtest_menus.xml",
    ],
}
