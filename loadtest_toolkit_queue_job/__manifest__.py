# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Load Test Toolkit - Queue Job",
    "summary": "Generate and clean up load-test data batches in background jobs "
    "(parent/child job graph, configurable chunk size)",
    "version": "18.0.1.0.0",
    "category": "Extra Tools",
    "website": "https://github.com/isikerkan/odoo-loadtest-toolkit",
    "author": "Erkan Isik",
    "maintainers": ["isikerkan"],
    "development_status": "Beta",
    "license": "AGPL-3",
    "depends": ["loadtest_toolkit", "queue_job"],
    "data": [
        "data/queue_job_data.xml",
        "views/loadtest_batch_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
