/**
 * WIMI Streak Display Component
 * Shows current streak, longest streak, and active days
 * Phase 6 Stage 7
 */

class StreakDisplay {
    /**
     * Create a streak display
     * @param {string} containerId - ID of container element
     * @param {object} options - Configuration options
     */
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        
        if (!this.container) {
            console.error(`Streak container #${containerId} not found`);
            return;
        }

        this.options = {
            showCurrentStreak: options.showCurrentStreak !== false,
            showLongestStreak: options.showLongestStreak !== false,
            showActiveDays: options.showActiveDays !== false,
            totalDays: options.totalDays || 90,
            compact: options.compact || false,
            ...options
        };

        this.data = null;
    }

    /**
     * Render the streak display with data
     * @param {object} data - Streak data from API
     * @param {number} totalDays - Total days for active days calculation
     */
    render(data, totalDays = null) {
        if (!this.container) return;
        
        this.data = data;
        
        if (totalDays !== null) {
            this.options.totalDays = totalDays;
        }

        if (!data) {
            this._renderEmptyState();
            return;
        }

        if (this.options.compact) {
            this._renderCompact(data);
        } else {
            this._renderFull(data);
        }
    }

    /**
     * Render full streak display with cards
     */
    _renderFull(data) {
        const { showCurrentStreak, showLongestStreak, showActiveDays, totalDays } = this.options;
        
        let html = '<div class="streak-cards">';

        if (showCurrentStreak) {
            const streakClass = data.streak_at_risk ? 'at-risk' : (data.current_streak > 0 ? 'active' : '');
            html += `
                <div class="streak-card current ${streakClass}">
                    <div class="streak-icon">🔥</div>
                    <div class="streak-content">
                        <div class="streak-label">Current Streak</div>
                        <div class="streak-value">${data.current_streak} <span class="streak-unit">days</span></div>
                        ${data.streak_at_risk ? '<div class="streak-warning">At risk! Log an entry today</div>' : ''}
                        ${data.is_active_today ? '<div class="streak-status active">✓ Active today</div>' : ''}
                    </div>
                </div>
            `;
        }

        if (showLongestStreak) {
            html += `
                <div class="streak-card longest">
                    <div class="streak-icon">🏆</div>
                    <div class="streak-content">
                        <div class="streak-label">Longest Streak</div>
                        <div class="streak-value">${data.longest_streak} <span class="streak-unit">days</span></div>
                        ${data.current_streak === data.longest_streak && data.current_streak > 0 
                            ? '<div class="streak-status best">Personal best!</div>' 
                            : ''}
                    </div>
                </div>
            `;
        }

        if (showActiveDays && data.total_active_days !== undefined) {
            const percentage = totalDays > 0 ? Math.round((data.total_active_days / totalDays) * 100) : 0;
            html += `
                <div class="streak-card active-days">
                    <div class="streak-icon">📅</div>
                    <div class="streak-content">
                        <div class="streak-label">Active Days</div>
                        <div class="streak-value">${data.total_active_days} <span class="streak-unit">of ${totalDays}</span></div>
                        <div class="streak-progress">
                            <div class="streak-progress-bar" style="width: ${percentage}%"></div>
                        </div>
                    </div>
                </div>
            `;
        }

        html += '</div>';
        this.container.innerHTML = html;
    }

    /**
     * Render compact streak display (for landing page widget)
     */
    _renderCompact(data) {
        const streakClass = data.streak_at_risk ? 'at-risk' : (data.current_streak > 0 ? 'active' : 'inactive');
        
        this.container.innerHTML = `
            <div class="streak-compact ${streakClass}">
                <span class="streak-icon">🔥</span>
                <span class="streak-text">
                    <strong>${data.current_streak}</strong> day${data.current_streak !== 1 ? 's' : ''} streak
                </span>
                ${data.streak_at_risk ? '<span class="streak-risk-badge">!</span>' : ''}
            </div>
        `;
    }

    /**
     * Render empty state
     */
    _renderEmptyState() {
        this.container.innerHTML = `
            <div class="streak-empty">
                <p>No streak data available</p>
                <p class="streak-empty-hint">Start logging entries to build your streak!</p>
            </div>
        `;
    }

    /**
     * Update streak display with new data
     * @param {object} data - New streak data
     * @param {number} totalDays - Optional total days override
     */
    update(data, totalDays = null) {
        this.render(data, totalDays);
    }

    /**
     * Get motivational message based on streak
     * @param {object} data - Streak data
     * @returns {string} Motivational message
     */
    getMotivationalMessage(data) {
        if (!data) return '';

        if (data.streak_at_risk) {
            return "Don't break your streak! Log an entry today.";
        }

        if (data.current_streak === 0) {
            return "Start a new streak today!";
        }

        if (data.current_streak === data.longest_streak && data.current_streak > 1) {
            return "You're at your personal best! Keep going!";
        }

        if (data.current_streak >= 30) {
            return "Amazing! A whole month of consistency!";
        }

        if (data.current_streak >= 14) {
            return "Two weeks strong! Great dedication!";
        }

        if (data.current_streak >= 7) {
            return "One week streak! You're building a habit!";
        }

        if (data.current_streak >= 3) {
            return "Great start! Keep the momentum going!";
        }

        return "Every day counts. Keep it up!";
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = StreakDisplay;
}
