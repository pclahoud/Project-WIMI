/**
 * WIMI Source Table Component
 * Displays source comparison data in table format
 * Phase 6 Stage 10
 */

class SourceTable {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.options = options;
    }

    render(data) {
        if (!this.container || !data || !data.sources) return;

        if (data.sources.length === 0) {
            this.container.innerHTML = '<div class="table-empty"><p>No sources found</p></div>';
            return;
        }

        const trendIcons = {
            'improving': { icon: '↓', class: 'trend-improving', label: 'Better' },
            'worsening': { icon: '↑', class: 'trend-worsening', label: 'Worse' },
            'stable': { icon: '→', class: 'trend-stable', label: 'Stable' }
        };

        let html = `
            <table class="source-table">
                <thead>
                    <tr>
                        <th>Source</th>
                        <th>Entries</th>
                        <th>Trend</th>
                        <th>Top Subject</th>
                    </tr>
                </thead>
                <tbody>
        `;

        data.sources.forEach(source => {
            const trend = trendIcons[source.trend] || trendIcons['stable'];
            html += `
                <tr>
                    <td class="source-name">
                        <span class="source-label">${source.source_name}</span>
                    </td>
                    <td class="source-entries">
                        <span class="entry-count">${source.entry_count}</span>
                        <span class="entry-pct">(${source.percentage}%)</span>
                    </td>
                    <td class="source-trend">
                        <span class="trend-badge ${trend.class}">
                            ${trend.icon} ${trend.label}
                        </span>
                    </td>
                    <td class="source-subject">
                        ${source.top_subject || '—'}
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        this.container.innerHTML = html;
    }

    update(data) {
        this.render(data);
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = SourceTable;
}
