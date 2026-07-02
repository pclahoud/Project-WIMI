/**
 * WIMI Goal Widget Component
 * Displays weekly goal progress and allows goal setting
 * Phase 6 Stage 8
 */

class GoalWidget {
    /**
     * Create a goal widget
     * @param {string} containerId - ID of container element
     * @param {object} options - Configuration options
     */
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        
        if (!this.container) {
            console.error(`Goal widget container #${containerId} not found`);
            return;
        }

        this.options = {
            showHistory: options.showHistory !== false,
            historyWeeks: options.historyWeeks || 8,
            compact: options.compact || false,
            onGoalChange: options.onGoalChange || null,
            ...options
        };

        this.currentGoal = null;
        this.goalHistory = [];
        this.examContextId = null;
    }

    /**
     * Load and render goal data
     * @param {number|null} examContextId - Optional exam context filter
     */
    async load(examContextId = null) {
        this.examContextId = examContextId;
        
        try {
            // Load current goals
            const goals = await api.getUserGoals({ examContextId });
            console.log('Goals response:', goals);
            
            // Find weekly goal (support both new and legacy types)
            this.currentGoal = goals?.find(g => 
                g.goal_type === 'weekly_questions' || g.goal_type === 'weekly_entries'
            ) || null;
            
            // Load history if showing
            if (this.options.showHistory && this.currentGoal) {
                this.goalHistory = await api.getGoalHistory({ 
                    examContextId, 
                    weeks: this.options.historyWeeks 
                }) || [];
            }
            
            this.render();
        } catch (error) {
            console.error('Error loading goals:', error);
            this.renderError();
        }
    }

    /**
     * Render the goal widget
     */
    render() {
        if (!this.container) return;

        if (this.options.compact) {
            this._renderCompact();
        } else {
            this._renderFull();
        }
    }

    /**
     * Render full goal widget with history
     */
    _renderFull() {
        if (!this.currentGoal) {
            this._renderNoGoal();
            return;
        }

        const goal = this.currentGoal;
        const progressPct = Math.min(100, goal.progress_pct);
        const remaining = Math.max(0, goal.target_value - goal.current_value);
        const daysLeft = this._getDaysUntilWeekEnd();

        let html = `
            <div class="goal-widget-full">
                <div class="goal-header">
                    <h3 class="goal-title">Weekly Goal</h3>
                    <button class="goal-edit-btn" id="editGoalBtn">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                            <path d="M11.5 2.5l2 2-8 8H3.5v-2l8-8z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        Edit
                    </button>
                </div>
                
                <div class="goal-current">
                    <p class="goal-target-text">Target: <strong>${goal.target_value}</strong> questions this week</p>
                    
                    <div class="goal-progress-container">
                        <div class="goal-progress-bar">
                            <div class="goal-progress-fill ${goal.is_complete ? 'complete' : ''}" 
                                 style="width: ${progressPct}%"></div>
                        </div>
                        <span class="goal-progress-text">${goal.current_value}/${goal.target_value} (${progressPct.toFixed(0)}%)</span>
                    </div>
                    
                    ${goal.is_complete 
                        ? '<p class="goal-message success">🎉 Goal achieved!</p>'
                        : `<p class="goal-message">${remaining} more ${remaining === 1 ? 'question' : 'questions'} to reach your goal!</p>`
                    }
                    <p class="goal-deadline">📅 Week ends in ${daysLeft} ${daysLeft === 1 ? 'day' : 'days'}</p>
                </div>
        `;

        // Add history section
        if (this.options.showHistory && this.goalHistory.length > 0) {
            html += this._renderHistory();
        }

        html += '</div>';
        
        this.container.innerHTML = html;
        
        // Add event listener for edit button
        const editBtn = document.getElementById('editGoalBtn');
        if (editBtn) {
            editBtn.addEventListener('click', () => this.openEditModal());
        }
    }

    /**
     * Render goal history section
     */
    _renderHistory() {
        // Skip current week (index 0) and show past weeks
        const pastWeeks = this.goalHistory.slice(1, 5);
        
        if (pastWeeks.length === 0) return '';

        let historyHtml = `
            <div class="goal-history">
                <h4 class="goal-history-title">Recent History</h4>
                <div class="goal-history-bars">
        `;

        pastWeeks.forEach(week => {
            const pct = Math.min(100, week.completion_pct);
            const weekDate = new Date(week.week_start);
            const label = weekDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            
            historyHtml += `
                <div class="history-bar-item">
                    <div class="history-bar-wrapper">
                        <div class="history-bar-fill ${week.completed ? 'complete' : ''}" 
                             style="width: ${pct}%"></div>
                    </div>
                    <div class="history-bar-label">
                        <span class="history-date">${label}</span>
                        <span class="history-value">${week.achieved}/${week.target} ${week.completed ? '✓' : ''}</span>
                    </div>
                </div>
            `;
        });

        historyHtml += '</div></div>';
        return historyHtml;
    }

    /**
     * Render no goal state
     */
    _renderNoGoal() {
        this.container.innerHTML = `
            <div class="goal-widget-empty">
                <div class="goal-empty-icon">🎯</div>
                <h3 class="goal-empty-title">Set a Weekly Goal</h3>
                <p class="goal-empty-text">Track your progress by setting a target for questions per week.</p>
                <button class="btn btn-primary" id="setGoalBtn">Set Goal</button>
            </div>
        `;

        // Add event listener
        const setBtn = document.getElementById('setGoalBtn');
        if (setBtn) {
            setBtn.addEventListener('click', () => this.openEditModal());
        }
    }

    /**
     * Render compact version (for landing page)
     */
    _renderCompact() {
        if (!this.currentGoal) {
            this.container.innerHTML = `
                <div class="goal-compact no-goal">
                    <span class="goal-compact-icon">🎯</span>
                    <span class="goal-compact-text">No goal set</span>
                    <button class="btn btn-primary btn-sm" onclick="window.goalWidget?.openEditModal()">Set</button>
                </div>
            `;
            return;
        }

        const goal = this.currentGoal;
        const progressPct = Math.min(100, goal.progress_pct);

        this.container.innerHTML = `
            <div class="goal-compact ${goal.is_complete ? 'complete' : ''}">
                <span class="goal-compact-icon">${goal.is_complete ? '🎉' : '🎯'}</span>
                <span class="goal-compact-label">Weekly Goal:</span>
                <span class="goal-compact-progress">${goal.current_value}/${goal.target_value}</span>
                <div class="goal-compact-bar">
                    <div class="goal-compact-fill ${goal.is_complete ? 'complete' : ''}" 
                         style="width: ${progressPct}%"></div>
                </div>
            </div>
        `;
    }

    /**
     * Render error state
     */
    renderError() {
        this.container.innerHTML = `
            <div class="goal-widget-error">
                <p>Unable to load goal data</p>
                <button class="btn btn-secondary btn-sm" onclick="window.goalWidget?.load()">Retry</button>
            </div>
        `;
    }

    /**
     * Get days until end of week (Sunday)
     */
    _getDaysUntilWeekEnd() {
        const now = new Date();
        const dayOfWeek = now.getDay();
        // Week ends on Sunday (day 0 from next week's perspective)
        // If today is Monday (1), there are 6 days until Sunday
        // If today is Sunday (0), there are 0 days until Sunday
        return dayOfWeek === 0 ? 0 : 7 - dayOfWeek;
    }

    /**
     * Open goal edit modal
     */
    openEditModal() {
        // Create modal if it doesn't exist
        let modal = document.getElementById('goalEditModal');
        if (!modal) {
            modal = this._createModal();
            document.body.appendChild(modal);
        }

        // Set current value (default to 100 for questions, higher than old entry default)
        const input = document.getElementById('goalTargetInput');
        if (input) {
            input.value = this.currentGoal?.target_value || 100;
        }

        // Show modal
        modal.classList.add('active');
    }

    /**
     * Create goal edit modal
     */
    _createModal() {
        const currentValue = this.currentGoal?.target_value || 100;
        
        const modal = document.createElement('div');
        modal.id = 'goalEditModal';
        modal.className = 'modal goal-modal';
        modal.innerHTML = `
            <div class="modal-backdrop" onclick="window.goalWidget?.closeModal()"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Set Weekly Goal</h3>
                    <button class="modal-close" onclick="window.goalWidget?.closeModal()">×</button>
                </div>
                <div class="modal-body">
                    <p class="goal-modal-description">How many questions do you want to answer each week?</p>
                    
                    <div class="goal-input-group">
                        <button class="goal-adjust-btn" onclick="window.goalWidget?.adjustGoal(-50)">-50</button>
                        <button class="goal-adjust-btn" onclick="window.goalWidget?.adjustGoal(-10)">-10</button>
                        <input type="number" id="goalTargetInput" class="goal-target-input" 
                               value="${currentValue}" min="1" max="1000">
                        <button class="goal-adjust-btn" onclick="window.goalWidget?.adjustGoal(10)">+10</button>
                        <button class="goal-adjust-btn" onclick="window.goalWidget?.adjustGoal(50)">+50</button>
                    </div>
                    
                    <p class="goal-modal-hint">Recommended: Start with a realistic goal you can consistently achieve.</p>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="window.goalWidget?.closeModal()">Cancel</button>
                    <button class="btn btn-primary" onclick="window.goalWidget?.saveGoal()">Save Goal</button>
                </div>
            </div>
        `;

        return modal;
    }

    /**
     * Adjust goal value
     */
    adjustGoal(delta) {
        const input = document.getElementById('goalTargetInput');
        if (input) {
            const current = parseInt(input.value) || 0;
            const newValue = Math.max(1, Math.min(1000, current + delta));
            input.value = newValue;
        }
    }

    /**
     * Save goal
     */
    async saveGoal() {
        const input = document.getElementById('goalTargetInput');
        const target = parseInt(input?.value);

        if (isNaN(target) || target < 1 || target > 1000) {
            alert('Please enter a goal between 1 and 1000');
            return;
        }

        try {
            const result = await api.setWeeklyGoal(target, { 
                examContextId: this.examContextId 
            });
            
            console.log('Goal saved:', result);
            
            this.closeModal();
            
            // Reload goal data
            await this.load(this.examContextId);
            
            // Callback
            if (this.options.onGoalChange) {
                this.options.onGoalChange(result);
            }
        } catch (error) {
            console.error('Error saving goal:', error);
            alert('Failed to save goal. Please try again.');
        }
    }

    /**
     * Close modal
     */
    closeModal() {
        const modal = document.getElementById('goalEditModal');
        if (modal) {
            modal.classList.remove('active');
        }
    }
}

// Global instance for modal callbacks
window.goalWidget = null;

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = GoalWidget;
}
