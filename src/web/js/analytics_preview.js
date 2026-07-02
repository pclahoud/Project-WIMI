/**
 * WIMI Analytics Preview Component
 * Phase 6 Stage 14 - Landing page analytics widget
 * 
 * Displays a compact analytics summary on the landing page with:
 * - Exam filter dropdown
 * - Quick stats (this week, top subject, top mistake, streak)
 * - Goal progress bar
 * - Top insight
 * - Link to full analytics dashboard (filtered by selected exam)
 */

class AnalyticsPreview {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.data = null;
        this.exams = [];
        this.selectedExamId = null; // null = "All Exams"
        this.isDropdownOpen = false;
    }
    
    /**
     * Initialize the component - load exams first, then analytics
     */
    async load() {
        if (!this.container) return;
        
        this.renderLoading();
        
        try {
            // First load available exams
            await this.loadExams();
            
            // Then load analytics data
            await this.loadAnalyticsData();
            
        } catch (error) {
            console.error('Error loading analytics preview:', error);
            this.renderError();
        }
    }
    
    /**
     * Load available exam contexts
     */
    async loadExams() {
        try {
            const exams = await api.getAllExamContexts(true); // active only
            this.exams = exams || [];
        } catch (error) {
            console.warn('Failed to load exams:', error);
            this.exams = [];
        }
    }
    
    /**
     * Load analytics data for the selected exam
     */
    async loadAnalyticsData() {
        try {
            const examId = this.selectedExamId;
            
            // Load all data in parallel
            const [overview, subjects, tags, goals, streak, insights] = await Promise.all([
                this.safeApiCall(() => api.getAnalyticsOverview(examId)),
                this.safeApiCall(() => api.getSubjectAnalytics({ examContextId: examId, limit: 5 })),
                this.safeApiCall(() => api.getTagAnalytics({ examContextId: examId })),
                this.safeApiCall(() => api.getUserGoals({ examContextId: examId })),
                this.safeApiCall(() => api.getStreakInfo({ examContextId: examId })),
                this.safeApiCall(() => api.getPatternsAndInsights({ examContextId: examId, limit: 1 }))
            ]);
            
            // Debug logging
            console.log('[AnalyticsPreview] Loaded data:', {
                examId,
                overview,
                subjects,
                tags,
                goals,
                streak,
                insights
            });
            
            // Aggregate goals when viewing "All Exams"
            let aggregatedGoal = this.aggregateGoals(goals, examId);
            
            // Extract top subject - handle different response structures
            let topSubject = null;
            if (subjects) {
                const subjectArray = subjects.subjects || subjects;
                if (Array.isArray(subjectArray) && subjectArray.length > 0) {
                    topSubject = subjectArray[0];
                }
            }
            
            // Extract top tag - handle different response structures
            let topTag = null;
            if (tags) {
                const tagArray = tags.top_tags || tags;
                if (Array.isArray(tagArray) && tagArray.length > 0) {
                    topTag = tagArray[0];
                }
            }
            
            // Extract top insight - handle array or single object
            let topInsight = null;
            if (insights) {
                if (Array.isArray(insights) && insights.length > 0) {
                    topInsight = insights[0];
                } else if (insights.message) {
                    topInsight = insights;
                }
            }
            
            this.data = {
                overview: overview || {},
                topSubject: topSubject,
                topTag: topTag,
                goal: aggregatedGoal,
                streak: streak || {},
                insight: topInsight
            };
            
            this.render();
        } catch (error) {
            console.error('Error loading analytics data:', error);
            this.renderError();
        }
    }
    
    /**
     * Safely call an API method, returning null on error
     */
    async safeApiCall(apiCall) {
        try {
            return await apiCall();
        } catch (error) {
            console.warn('Analytics preview API call failed:', error);
            return null;
        }
    }
    
    /**
     * Aggregate goals for "All Exams" view.
     * When viewing all exams, sum up current_value and target_value across all goals.
     * When viewing a specific exam, return just that exam's goal.
     * 
     * @param {Array|null} goals - Array of goal objects from API
     * @param {number|null} examId - Currently selected exam ID (null for "All Exams")
     * @returns {object|null} Aggregated goal object or null if no goals
     */
    aggregateGoals(goals, examId) {
        // Handle null/empty cases
        if (!goals) return null;
        
        const goalsArray = Array.isArray(goals) ? goals : [goals];
        if (goalsArray.length === 0) return null;
        
        // If viewing a specific exam, return just that exam's goal
        if (examId !== null) {
            // Find the goal for this specific exam
            const examGoal = goalsArray.find(g => g.exam_context_id === examId);
            return examGoal || null;
        }
        
        // Viewing "All Exams" - aggregate all goals
        let totalCurrent = 0;
        let totalTarget = 0;
        let allComplete = true;
        
        for (const goal of goalsArray) {
            const current = goal.current_value || goal.achieved || 0;
            const target = goal.target_value || goal.target || 0;
            
            totalCurrent += current;
            totalTarget += target;
            
            // Track if all individual goals are complete
            if (current < target) {
                allComplete = false;
            }
        }
        
        // If no targets set, return null
        if (totalTarget === 0) return null;
        
        // Calculate aggregated progress
        const progressPct = (totalCurrent / totalTarget) * 100;
        const isComplete = totalCurrent >= totalTarget;
        
        console.log('[AnalyticsPreview] Aggregated goals:', {
            goalsCount: goalsArray.length,
            totalCurrent,
            totalTarget,
            progressPct: progressPct.toFixed(1),
            isComplete
        });
        
        return {
            current_value: totalCurrent,
            target_value: totalTarget,
            progress_pct: progressPct,
            is_complete: isComplete,
            is_aggregated: true,  // Flag to indicate this is an aggregated goal
            goal_count: goalsArray.length
        };
    }
    
    /**
     * Handle exam selection change
     */
    async onExamChange(examId) {
        this.selectedExamId = examId ? parseInt(examId) : null;
        this.isDropdownOpen = false;
        
        // Show loading in stats area while keeping header
        const statsContainer = this.container.querySelector('.analytics-preview-stats');
        if (statsContainer) {
            statsContainer.innerHTML = `
                ${this.renderSkeletonStat()}
                ${this.renderSkeletonStat()}
                ${this.renderSkeletonStat()}
                ${this.renderSkeletonStat()}
            `;
        }
        
        await this.loadAnalyticsData();
    }
    
    /**
     * Toggle dropdown open/close
     */
    toggleDropdown() {
        this.isDropdownOpen = !this.isDropdownOpen;
        const dropdown = this.container.querySelector('.custom-select');
        if (dropdown) {
            dropdown.classList.toggle('open', this.isDropdownOpen);
        }
    }
    
    /**
     * Close dropdown when clicking outside
     */
    setupClickOutside() {
        document.addEventListener('click', (e) => {
            const dropdown = this.container.querySelector('.custom-select');
            if (dropdown && !dropdown.contains(e.target)) {
                this.isDropdownOpen = false;
                dropdown.classList.remove('open');
            }
        });
    }
    
    /**
     * Navigate to full analytics report
     */
    viewFullReport() {
        let url = 'analytics_dashboard.html';
        if (this.selectedExamId) {
            url += `?exam=${this.selectedExamId}`;
        }
        window.location.href = url;
    }
    
    /**
     * Render loading state
     */
    renderLoading() {
        this.container.innerHTML = `
            <div class="analytics-preview analytics-preview--loading">
                <div class="analytics-preview-header">
                    <h3 class="analytics-preview-title">
                        <span class="analytics-preview-icon">📊</span>
                        Quick Analytics
                    </h3>
                </div>
                <div class="analytics-preview-content">
                    <div class="analytics-preview-stats">
                        ${this.renderSkeletonStat()}
                        ${this.renderSkeletonStat()}
                        ${this.renderSkeletonStat()}
                        ${this.renderSkeletonStat()}
                    </div>
                </div>
            </div>
        `;
    }
    
    /**
     * Render skeleton stat card for loading
     */
    renderSkeletonStat() {
        return `
            <div class="preview-stat preview-stat--skeleton">
                <div class="skeleton skeleton-label"></div>
                <div class="skeleton skeleton-value"></div>
            </div>
        `;
    }
    
    /**
     * Render error state
     */
    renderError() {
        this.container.innerHTML = `
            <div class="analytics-preview analytics-preview--error">
                <div class="analytics-preview-header">
                    <h3 class="analytics-preview-title">
                        <span class="analytics-preview-icon">📊</span>
                        Quick Analytics
                    </h3>
                </div>
                <div class="analytics-preview-content">
                    <p class="analytics-preview-error-text">Unable to load analytics data</p>
                    <button class="btn btn-secondary btn-sm" onclick="window.analyticsPreview?.load()">
                        Retry
                    </button>
                </div>
            </div>
        `;
    }
    
    /**
     * Render empty state when no data exists
     */
    renderEmpty() {
        const selectedExamName = this.getSelectedExamName();
        
        this.container.innerHTML = `
            <div class="analytics-preview analytics-preview--empty">
                <div class="analytics-preview-header">
                    <h3 class="analytics-preview-title">
                        <span class="analytics-preview-icon">📊</span>
                        Quick Analytics
                    </h3>
                    <div class="analytics-preview-actions">
                        ${this.renderExamDropdown()}
                        <button class="btn btn-primary btn-sm analytics-preview-report-btn" onclick="window.analyticsPreview?.viewFullReport()" data-testid="dashboard-analytics-report-link">
                            View Full Report →
                        </button>
                    </div>
                </div>
                <div class="analytics-preview-content">
                    <div class="analytics-preview-empty-state">
                        <span class="analytics-preview-empty-icon">📝</span>
                        <p>No entries logged yet${selectedExamName ? ` for ${selectedExamName}` : ''}</p>
                        <p class="analytics-preview-empty-hint">
                            Create a review session to start tracking your mistakes
                        </p>
                    </div>
                </div>
            </div>
        `;
        
        this.setupDropdownListeners();
    }
    
    /**
     * Get the name of the currently selected exam
     */
    getSelectedExamName() {
        if (!this.selectedExamId) return null;
        const exam = this.exams.find(e => e.id === this.selectedExamId);
        return exam ? exam.exam_name : null;
    }
    
    /**
     * Render the exam filter dropdown
     */
    renderExamDropdown() {
        const selectedExam = this.exams.find(e => e.id === this.selectedExamId);
        const displayText = selectedExam ? selectedExam.exam_name : 'All Exams';
        
        let optionsHtml = `
            <div class="custom-select-option ${!this.selectedExamId ? 'selected' : ''}" 
                 data-value="" 
                 tabindex="0"
                 role="option">
                All Exams
            </div>
        `;
        
        this.exams.forEach(exam => {
            const isSelected = exam.id === this.selectedExamId;
            optionsHtml += `
                <div class="custom-select-option ${isSelected ? 'selected' : ''}" 
                     data-value="${exam.id}" 
                     tabindex="0"
                     role="option">
                    ${this.escapeHtml(exam.exam_name)}
                </div>
            `;
        });
        
        return `
            <div class="custom-select analytics-exam-select ${this.isDropdownOpen ? 'open' : ''}" data-select="exam-filter" data-testid="dashboard-analytics-exam-filter">
                <div class="custom-select-trigger" tabindex="0" role="combobox" aria-expanded="${this.isDropdownOpen}" data-testid="dashboard-analytics-exam-filter-trigger">
                    <span class="custom-select-value">${this.escapeHtml(displayText)}</span>
                    <span class="custom-select-arrow">▼</span>
                </div>
                <div class="custom-select-options" role="listbox">
                    ${optionsHtml}
                </div>
            </div>
        `;
    }
    
    /**
     * Setup dropdown event listeners
     */
    setupDropdownListeners() {
        const dropdown = this.container.querySelector('.custom-select');
        if (!dropdown) return;
        
        const trigger = dropdown.querySelector('.custom-select-trigger');
        const options = dropdown.querySelectorAll('.custom-select-option');
        
        // Toggle on trigger click
        trigger?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleDropdown();
        });
        
        // Handle keyboard on trigger
        trigger?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.toggleDropdown();
            }
        });
        
        // Option selection
        options.forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                const value = option.dataset.value;
                this.onExamChange(value);
            });
            
            option.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    const value = option.dataset.value;
                    this.onExamChange(value);
                }
            });
        });
        
        // Close on outside click
        this.setupClickOutside();
    }
    
    /**
     * Main render method
     */
    render() {
        const { overview, topSubject, topTag, goal, streak, insight } = this.data;
        
        // Check if there's any data to show
        const totalEntries = overview?.total_entries || overview?.completed_entries || 0;
        const hasData = totalEntries > 0;
        
        if (!hasData) {
            this.renderEmpty();
            return;
        }
        
        this.container.innerHTML = `
            <div class="analytics-preview">
                <div class="analytics-preview-header">
                    <h3 class="analytics-preview-title">
                        <span class="analytics-preview-icon">📊</span>
                        Quick Analytics
                    </h3>
                    <div class="analytics-preview-actions">
                        ${this.renderExamDropdown()}
                        <button class="btn btn-primary btn-sm analytics-preview-report-btn" onclick="window.analyticsPreview?.viewFullReport()" data-testid="dashboard-analytics-report-link">
                            View Full Report →
                        </button>
                    </div>
                </div>
                
                <div class="analytics-preview-content">
                    <!-- Stats Row -->
                    <div class="analytics-preview-stats">
                        ${this.renderThisWeekStat(overview)}
                        ${this.renderTopSubjectStat(topSubject)}
                        ${this.renderTopTagStat(topTag)}
                        ${this.renderStreakStat(streak)}
                    </div>
                    
                    <!-- Goal Progress -->
                    ${this.renderGoalProgress(goal)}
                    
                    <!-- Top Insight -->
                    ${this.renderTopInsight(insight)}
                </div>
            </div>
        `;
        
        this.setupDropdownListeners();
    }
    
    /**
     * Render "This Week" stat card
     */
    renderThisWeekStat(overview) {
        const thisWeek = overview?.this_week || 0;
        const lastWeek = overview?.last_week || 0;
        const change = thisWeek - lastWeek;
        
        let trendHtml = '';
        if (change !== 0) {
            const trendClass = change > 0 ? 'positive' : 'negative';
            const trendSign = change > 0 ? '+' : '';
            trendHtml = `<span class="preview-stat-trend ${trendClass}">${trendSign}${change} vs last</span>`;
        }
        
        return `
            <div class="preview-stat">
                <span class="preview-stat-label">THIS WEEK</span>
                <span class="preview-stat-value">${thisWeek}</span>
                <span class="preview-stat-subtitle">entries</span>
                ${trendHtml}
            </div>
        `;
    }
    
    /**
     * Render "Top Subject" stat card
     */
    renderTopSubjectStat(topSubject) {
        if (!topSubject) {
            return `
                <div class="preview-stat">
                    <span class="preview-stat-label">TOP SUBJECT</span>
                    <span class="preview-stat-value preview-stat-value--text preview-stat-value--empty">—</span>
                    <span class="preview-stat-subtitle">no data</span>
                </div>
            `;
        }
        
        // Handle different possible field names
        const rawName = topSubject.subject_name || topSubject.name || topSubject.full_path || '—';
        const count = topSubject.mistake_count || topSubject.count || topSubject.entry_count || 0;
        
        return `
            <div class="preview-stat">
                <span class="preview-stat-label">TOP SUBJECT</span>
                <span class="preview-stat-value preview-stat-value--text" title="${this.escapeHtml(rawName)}">
                    ${this.escapeHtml(rawName)}
                </span>
                <span class="preview-stat-subtitle">(${count} entries)</span>
            </div>
        `;
    }
    
    /**
     * Render "Top Mistake" stat card
     */
    renderTopTagStat(topTag) {
        if (!topTag) {
            return `
                <div class="preview-stat">
                    <span class="preview-stat-label">TOP MISTAKE</span>
                    <span class="preview-stat-value preview-stat-value--text preview-stat-value--empty">—</span>
                    <span class="preview-stat-subtitle">no data</span>
                </div>
            `;
        }
        
        // Handle different possible field names
        const rawName = topTag.tag_name || topTag.name || '—';
        const count = topTag.count || topTag.entry_count || 0;
        
        return `
            <div class="preview-stat">
                <span class="preview-stat-label">TOP MISTAKE</span>
                <span class="preview-stat-value preview-stat-value--text" title="${this.escapeHtml(rawName)}">
                    ${this.escapeHtml(rawName)}
                </span>
                <span class="preview-stat-subtitle">(${count} entries)</span>
            </div>
        `;
    }
    
    /**
     * Render "Streak" stat card
     */
    renderStreakStat(streak) {
        const currentStreak = streak?.current_streak || 0;
        const atRisk = streak?.streak_at_risk || false;
        
        return `
            <div class="preview-stat ${atRisk ? 'preview-stat--warning' : ''}">
                <span class="preview-stat-label">STREAK</span>
                <span class="preview-stat-value">
                    <span class="preview-stat-streak-icon">🔥</span>
                    ${currentStreak}
                </span>
                <span class="preview-stat-subtitle">day${currentStreak !== 1 ? 's' : ''}</span>
                ${atRisk ? '<span class="preview-stat-warning">At risk!</span>' : ''}
            </div>
        `;
    }
    
    /**
     * Render goal progress bar
     */
    renderGoalProgress(goal) {
        if (!goal) {
            return `
                <div class="analytics-preview-goal analytics-preview-goal--empty">
                    <span class="goal-icon">🎯</span>
                    <span class="goal-text">No weekly goal set</span>
                    <a href="analytics_dashboard.html#goals" class="goal-set-link">Set a goal →</a>
                </div>
            `;
        }
        
        const current = goal.current_value || goal.achieved || 0;
        const target = goal.target_value || goal.target || 20;
        const progress = Math.min(100, goal.progress_pct || (current / target * 100));
        const isComplete = goal.is_complete || current >= target;
        
        // Show "Combined" label when viewing aggregated goals from multiple exams
        const isAggregated = goal.is_aggregated && goal.goal_count > 1;
        const goalLabel = isAggregated 
            ? `Weekly Goals (${goal.goal_count} exams):` 
            : 'Weekly Goal:';
        
        return `
            <div class="analytics-preview-goal ${isAggregated ? 'analytics-preview-goal--aggregated' : ''}">
                <div class="goal-header">
                    <span class="goal-icon">🎯</span>
                    <span class="goal-label">${goalLabel}</span>
                    <span class="goal-progress-text">${current}/${target}</span>
                    <span class="goal-percent">(${Math.round(progress)}%)</span>
                    ${isComplete ? '<span class="goal-complete-badge">✓</span>' : ''}
                </div>
                <div class="goal-progress-bar">
                    <div class="goal-progress-fill ${isComplete ? 'complete' : ''}" style="width: ${progress}%"></div>
                </div>
            </div>
        `;
    }
    
    /**
     * Render top insight
     */
    renderTopInsight(insight) {
        if (!insight) {
            return '';
        }
        
        const typeClass = insight.type || 'info';
        const icon = insight.icon || '💡';
        const message = insight.message || insight.detail || '';
        
        // Don't render if no message
        if (!message) {
            return '';
        }
        
        return `
            <div class="analytics-preview-insight insight-card--${typeClass}">
                <span class="insight-icon">${icon}</span>
                <span class="insight-message">${this.escapeHtml(message)}</span>
            </div>
        `;
    }
    
    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Export for use in landing page
window.AnalyticsPreview = AnalyticsPreview;
