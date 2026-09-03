/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";

/* global Chart */

const PALETTE = {
    users: "#714B67", // Odoo purple
    current_rps: "#017E84",
    p50: "#00A09D",
    p95: "#E4A11B",
    fail_ratio: "#D9534F",
    cpu: "#6C757D",
    mem: "#0D6EFD",
    pg_active: "#F06050",
    pg_total: "#ADB5BD",
};

/**
 * Three timeline charts fed by the run's poll samples (chart_data JSON):
 * throughput (users, current req/s), latency (p50, p95, failure ratio)
 * and host/database load (CPU %, RAM %, PG connections). Pure rendering,
 * no polling: the data is whatever the record holds.
 */
export class LoadtestRunChartsField extends Component {
    static template = "loadtest_toolkit.RunChartsField";
    static props = { ...standardFieldProps };

    setup() {
        this.charts = [];
        this.refs = {
            throughput: useRef("throughput"),
            latency: useRef("latency"),
            system: useRef("system"),
        };
        onWillStart(async () => await loadBundle("web.chartjs_lib"));
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [JSON.stringify(this.props.record.data[this.props.name] || null)]
        );
    }

    get data() {
        const value = this.props.record.data[this.props.name];
        return value && value.labels ? value : { labels: [], series: {} };
    }

    get isEmpty() {
        return !this.data.labels.length;
    }

    destroyCharts() {
        for (const chart of this.charts) {
            chart.destroy();
        }
        this.charts = [];
    }

    labels() {
        // samples are minutes apart: show hh:mm in the user's timezone
        return this.data.labels.map((iso) =>
            luxon.DateTime.fromSQL(iso, { zone: "utc" }).toLocal().toFormat("HH:mm")
        );
    }

    dataset(key, label, axis, extra = {}) {
        return {
            label,
            data: this.data.series[key] || [],
            borderColor: PALETTE[key],
            backgroundColor: PALETTE[key],
            yAxisID: axis,
            tension: 0.25,
            pointRadius: 2,
            borderWidth: 2,
            ...extra,
        };
    }

    options(leftTitle, rightTitle, rightOptions = {}) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { position: "bottom" } },
            scales: {
                x: { ticks: { maxTicksLimit: 12 } },
                left: {
                    type: "linear",
                    position: "left",
                    beginAtZero: true,
                    title: { display: true, text: leftTitle },
                },
                right: {
                    type: "linear",
                    position: "right",
                    beginAtZero: true,
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: rightTitle },
                    ...rightOptions,
                },
            },
        };
    }

    renderCharts() {
        this.destroyCharts();
        if (this.isEmpty || typeof Chart === "undefined") {
            return;
        }
        const labels = this.labels();
        const make = (ref, datasets, options) => {
            if (ref.el) {
                this.charts.push(new Chart(ref.el, { type: "line", data: { labels, datasets }, options }));
            }
        };
        make(
            this.refs.throughput,
            [
                this.dataset("users", _t("Users"), "left", { stepped: true }),
                this.dataset("current_rps", _t("Requests/s"), "right"),
            ],
            this.options(_t("Users"), _t("Requests/s"))
        );
        make(
            this.refs.latency,
            [
                this.dataset("p50", _t("p50 (ms)"), "left"),
                this.dataset("p95", _t("p95 (ms)"), "left"),
                this.dataset("fail_ratio", _t("Failure ratio"), "right", {
                    borderDash: [4, 4],
                    fill: false,
                }),
            ],
            this.options(_t("Response time (ms)"), _t("Failure ratio"), {
                max: 1,
                ticks: { callback: (v) => `${Math.round(v * 100)}%` },
            })
        );
        make(
            this.refs.system,
            [
                this.dataset("cpu", _t("CPU %"), "left"),
                this.dataset("mem", _t("RAM %"), "left"),
                this.dataset("pg_active", _t("PG active"), "right", { stepped: true }),
                this.dataset("pg_total", _t("PG connections"), "right", {
                    stepped: true,
                    borderDash: [4, 4],
                }),
            ],
            this.options(_t("Percent"), _t("PostgreSQL connections"), { max: undefined })
        );
    }
}

export const loadtestRunChartsField = {
    component: LoadtestRunChartsField,
    displayName: _t("Load test run charts"),
    supportedTypes: ["json"],
};

registry.category("fields").add("loadtest_run_charts", loadtestRunChartsField);
