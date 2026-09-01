# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    """Convert stored duration seconds into value + unit."""
    cr.execute("SELECT id, duration FROM loadtest_scenario")
    for scenario_id, duration in cr.fetchall():
        if not duration:
            value, unit = 0, "infinite"
        elif duration % 86400 == 0:
            value, unit = duration // 86400, "days"
        elif duration % 3600 == 0:
            value, unit = duration // 3600, "hours"
        elif duration % 60 == 0:
            value, unit = duration // 60, "minutes"
        else:
            value, unit = duration, "seconds"
        cr.execute(
            "UPDATE loadtest_scenario SET duration_value = %s, duration_unit = %s WHERE id = %s",
            (value, unit, scenario_id),
        )
