/**
 * WIMI Landing Page JavaScript
 * Phase 3 - Exam management and navigation
 */

// =========================================================================
// Analytics Preview
// =========================================================================

let analyticsPreview = null;

async function loadAnalyticsPreview() {
    try {
        analyticsPreview = new AnalyticsPreview('analytics-preview-container');
        window.analyticsPreview = analyticsPreview; // For retry button
        await analyticsPreview.load();
    } catch (error) {
        console.error('Error loading analytics preview:', error);
    }
}

// =========================================================================
// State Management
// =========================================================================

const LandingState = {
    exams: [],
    isLoading: true,
    selectedExamId: null,
    deleteModalExam: null,
    suspendModalExam: null
};

// =========================================================================
// Toast Notification System
// =========================================================================

const Toast = {
    container: null,
    
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    },
    
    show(type, title, message, duration = 4000) {
        this.init();
        
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };
        
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || 'ℹ'}</span>
            <div class="toast-content">
                <p class="toast-title">${title}</p>
                ${message ? `<p class="toast-message">${message}</p>` : ''}
            </div>
            <button class="toast-close" aria-label="Close">×</button>
        `;
        
        this.container.appendChild(toast);
        
        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });
        
        // Close button
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this.dismiss(toast);
        });
        
        // Auto dismiss
        if (duration > 0) {
            setTimeout(() => this.dismiss(toast), duration);
        }
        
        return toast;
    },
    
    dismiss(toast) {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    },
    
    success(title, message) { return this.show('success', title, message); },
    error(title, message) { return this.show('error', title, message); },
    warning(title, message) { return this.show('warning', title, message); },
    info(title, message) { return this.show('info', title, message); }
};

// =========================================================================
// Suspend Modal
// =========================================================================

const SuspendModal = {
    backdrop: null,

    init() {
        this.backdrop = document.getElementById('delete-modal');
        if (!this.backdrop) return;

        // Close on backdrop click
        this.backdrop.addEventListener('click', (e) => {
            if (e.target === this.backdrop) {
                this.close();
            }
        });

        // Close button
        document.getElementById('delete-cancel')?.addEventListener('click', () => this.close());

        // Confirm button
        document.getElementById('delete-confirm')?.addEventListener('click', () => this.confirm());

        // ESC key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.backdrop?.classList.contains('active')) {
                this.close();
            }
        });
    },

    open(exam) {
        if (!this.backdrop) return;

        LandingState.suspendModalExam = exam;

        // Update modal content
        const nameEl = document.getElementById('delete-exam-name');
        if (nameEl) {
            nameEl.textContent = exam.exam_name;
        }

        this.backdrop.classList.add('active');
        document.body.style.overflow = 'hidden';
    },

    close() {
        if (!this.backdrop) return;

        this.backdrop.classList.remove('active');
        document.body.style.overflow = '';
        LandingState.suspendModalExam = null;
    },

    async confirm() {
        const exam = LandingState.suspendModalExam;
        if (!exam) return;

        const confirmBtn = document.getElementById('delete-confirm');
        const originalText = confirmBtn?.textContent;

        try {
            // Show loading state
            if (confirmBtn) {
                confirmBtn.disabled = true;
                confirmBtn.innerHTML = '<span class="spinner spinner-sm"></span> Suspending...';
            }

            await api.deleteExamContext(exam.id);

            this.close();
            Toast.success('Exam Suspended', `"${exam.exam_name}" has been suspended.`);

            // Refresh the exam list
            await loadExams();

        } catch (error) {
            console.error('Error suspending exam:', error);
            Toast.error('Suspend Failed', error.message || 'Could not suspend the exam.');
        } finally {
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.textContent = originalText;
            }
        }
    }
};

// =========================================================================
// Exam Card Rendering
// =========================================================================

function formatDate(dateStr) {
    if (!dateStr) return 'Not set';

    try {
        const [y, m, d] = dateStr.slice(0, 10).split('-').map(Number);
        if (!y || !m || !d) return dateStr;
        const date = new Date(y, m - 1, d);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    } catch {
        return dateStr;
    }
}

function getDaysUntil(dateStr) {
    if (!dateStr) return null;
    
    try {
        const [year, month, day] = dateStr.split('-').map(Number);
        const examDate = new Date(year, month - 1, day);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        
        const diffTime = examDate - today;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        
        return diffDays;
    } catch {
        return null;
    }
}

function getExamDateBadge(dateStr) {
    const days = getDaysUntil(dateStr);
    if (days === null) return '';
    
    if (days < 0) {
        return `<span class="badge badge-gray">Passed</span>`;
    } else if (days === 0) {
        return `<span class="badge badge-error">Today!</span>`;
    } else if (days <= 7) {
        return `<span class="badge badge-warning">${days} day${days === 1 ? '' : 's'}</span>`;
    } else if (days <= 30) {
        return `<span class="badge badge-primary">${days} days</span>`;
    }
    return '';
}

function renderExamCard(exam) {
    const stats = exam.stats || { subject_count: 0, question_count: 0 };
    const dateBadge = getExamDateBadge(exam.exam_date);
    const isSuspended = !exam.is_active;
    const suspendedStyle = isSuspended ? ' style="opacity: 0.6; filter: grayscale(0.5);"' : '';

    // Build utility actions based on active/suspended state
    let utilityActions = '';
    if (isSuspended) {
        utilityActions = `
                <div class="exam-card-actions-utility">
                    <button class="btn btn-ghost btn-sm" onclick="reactivateExam(${exam.id})" title="Reactivate Exam" data-testid="dashboard-exam-${exam.id}-reactivate-btn">
                        ▶️ Reactivate
                    </button>
                    <button class="btn btn-ghost btn-sm btn-danger-text" onclick="confirmHardDeleteExam(${exam.id}, '${escapeHtml(exam.exam_name).replace(/'/g, "\\'")}')\" title="Permanently Delete Exam" data-testid="dashboard-exam-${exam.id}-delete-btn">
                        🗑️ Delete Permanently
                    </button>
                </div>`;
    } else {
        utilityActions = `
                <div class="exam-card-actions-utility">
                    <button class="btn btn-ghost btn-sm" onclick="editExam(${exam.id})" title="Edit Exam Settings" data-testid="dashboard-exam-${exam.id}-edit-btn">
                        ✏️ Edit
                    </button>
                    <button class="btn btn-ghost btn-sm btn-danger-text" onclick="confirmSuspendExam(${exam.id})" title="Suspend Exam" data-testid="dashboard-exam-${exam.id}-suspend-btn">
                        ⏸️ Suspend
                    </button>
                </div>`;
    }

    return `
        <div class="exam-card" data-exam-id="${exam.id}"${suspendedStyle} data-testid="dashboard-exam-card-${exam.id}">
            <div class="exam-card-header">
                <div class="exam-card-icon">📚</div>
                <div class="exam-card-status">
                    ${exam.is_active
                        ? '<span class="badge badge-success">Active</span>'
                        : '<span class="badge badge-gray">Suspended</span>'}
                    ${dateBadge}
                </div>
            </div>

            <h3 class="exam-card-title">${escapeHtml(exam.exam_name)}</h3>
            <p class="exam-card-description">
                ${exam.exam_description ? escapeHtml(exam.exam_description) : 'No description provided'}
            </p>

            <div class="exam-card-stats">
                <div class="exam-stat">
                    <span class="exam-stat-icon">📅</span>
                    <div>
                        <div class="exam-stat-label">Exam Date</div>
                        <div class="exam-stat-value">${formatDate(exam.exam_date)}</div>
                    </div>
                </div>
                <div class="exam-stat">
                    <span class="exam-stat-icon">📊</span>
                    <div>
                        <div class="exam-stat-label">Subjects</div>
                        <div class="exam-stat-value">${stats.subject_count} topics</div>
                    </div>
                </div>
                <div class="exam-stat">
                    <span class="exam-stat-icon">❓</span>
                    <div>
                        <div class="exam-stat-label">Questions</div>
                        <div class="exam-stat-value">${stats.question_count} logged</div>
                    </div>
                </div>
                <div class="exam-stat">
                    <span class="exam-stat-icon">📆</span>
                    <div>
                        <div class="exam-stat-label">Created</div>
                        <div class="exam-stat-value">${formatDate(exam.created_date || exam.created_at)}</div>
                    </div>
                </div>
            </div>

            <div class="exam-card-actions">
                <!-- Primary action - full width -->
                <button class="btn btn-primary exam-card-btn-main" onclick="startNewSession(${exam.id})" data-testid="dashboard-exam-${exam.id}-new-session-btn">
                    📝 New Review Session
                </button>

                <!-- Secondary actions row -->
                <div class="exam-card-actions-row">
                    <button class="btn btn-secondary" onclick="browseEntries(${exam.id})" title="Browse All Entries" data-testid="dashboard-exam-${exam.id}-browse-btn">
                        📋 Browse
                    </button>
                    <button class="btn btn-secondary" onclick="viewAnalytics(${exam.id})" title="View Analytics" data-testid="dashboard-exam-${exam.id}-analytics-btn">
                        📈 Analytics
                    </button>
                    <button class="btn btn-secondary" onclick="openExam(${exam.id})" title="Edit Subject Tree" data-testid="dashboard-exam-${exam.id}-subjects-btn">
                        🗂️ Subjects
                    </button>
                </div>

                <!-- Utility actions -->
                ${utilityActions}
            </div>
        </div>
    `;
}

function renderCreateCard() {
    return `
        <a href="wizards/exam_wizard.html" class="exam-card exam-card--create">
            <div class="exam-card-icon">+</div>
            <h3 class="exam-card-title">Create New Exam</h3>
            <p class="exam-card-description">
                Set up a new exam with custom hierarchy and weights
            </p>
        </a>
    `;
}

function renderEmptyState() {
    return `
        <div class="empty-state">
            <div class="empty-state-icon">📋</div>
            <h3 class="empty-state-title">No Exams Yet</h3>
            <p class="empty-state-text">
                Create your first exam to start tracking your mistakes and improving your study strategy.
            </p>
            <a href="wizards/exam_wizard.html" class="btn btn-primary btn-lg empty-state-action">
                Create Your First Exam
            </a>
        </div>
    `;
}

function renderLoadingState() {
    return `
        <div class="exam-card--skeleton">
            <div class="skeleton skeleton-icon"></div>
            <div class="skeleton skeleton-title"></div>
            <div class="skeleton skeleton-text"></div>
            <div class="skeleton skeleton-text"></div>
            <div class="skeleton skeleton-stats"></div>
            <div class="skeleton skeleton-button"></div>
        </div>
    `.repeat(3);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =========================================================================
// Exam Operations
// =========================================================================

async function loadExams() {
    const container = document.getElementById('exams-grid');
    if (!container) return;
    
    LandingState.isLoading = true;
    container.innerHTML = renderLoadingState();
    
    try {
        await api.ready();
        
        // Get all exam contexts
        const exams = await api.getAllExamContexts(false); // Include inactive
        LandingState.exams = exams || [];
        
        // Get stats for each exam (if method exists)
        for (const exam of LandingState.exams) {
            try {
                const stats = await api.getExamContextStats(exam.id);
                exam.stats = stats;
            } catch (e) {
                // Stats method might not exist yet
                exam.stats = { subject_count: 0, question_count: 0 };
            }
        }
        
        // Render exams
        if (LandingState.exams.length === 0) {
            container.innerHTML = renderEmptyState();
        } else {
            const cardsHtml = LandingState.exams.map(renderExamCard).join('');
            container.innerHTML = cardsHtml + renderCreateCard();
        }
        
    } catch (error) {
        console.error('Error loading exams:', error);
        container.innerHTML = `
            <div class="alert alert-error">
                <strong>Failed to load exams:</strong> ${error.message || 'Unknown error'}
                <br><br>
                <button class="btn btn-secondary" onclick="loadExams()">Retry</button>
            </div>
        `;
    } finally {
        LandingState.isLoading = false;
    }
}

function openExam(examId) {
    // Navigate to the tree editor for this exam
    window.location.href = `tree_editor.html?exam_id=${examId}`;
}

function startNewSession(examId) {
    // Navigate to the session setup page for this exam
    window.location.href = `session_setup.html?exam_id=${examId}`;
}

function browseEntries(examId) {
    // Navigate to the entry browser for this exam
    window.location.href = `entry_browser.html?exam=${examId}`;
}

function viewAnalytics(examId) {
    // Navigate to the analytics dashboard for this exam
    window.location.href = `analytics_dashboard.html?exam=${examId}`;
}

function editExam(examId) {
    // Navigate to the wizard in edit mode
    window.location.href = `wizards/exam_wizard.html?edit=${examId}`;
}

function confirmSuspendExam(examId) {
    const exam = LandingState.exams.find(e => e.id === examId);
    if (exam) {
        SuspendModal.open(exam);
    }
}

async function reactivateExam(examId) {
    try {
        await api.reactivateExamContext(examId);
        Toast.success('Exam Reactivated', 'The exam has been reactivated.');
        await loadExams();
    } catch (error) {
        console.error('Error reactivating exam:', error);
        Toast.error('Reactivation Failed', error.message || 'Could not reactivate the exam.');
    }
}

async function confirmHardDeleteExam(examId, examName) {
    if (!confirm('Are you sure you want to permanently delete "' + examName + '"? This will remove all sessions, entries, and data. This cannot be undone.')) {
        return;
    }
    try {
        await api.hardDeleteExamContext(examId);
        Toast.success('Exam Deleted', 'The exam has been permanently deleted.');
        await loadExams();
    } catch (error) {
        console.error('Error permanently deleting exam:', error);
        Toast.error('Delete Failed', error.message || 'Could not permanently delete the exam.');
    }
}

// =========================================================================
// Profile Chip (header, links to the profile picker)
// =========================================================================

function profileChipInitials(displayName, username) {
    const source = (displayName || username || '?').trim();
    const words = source.split(/\s+/).filter(Boolean);
    if (words.length >= 2) {
        return (words[0][0] + words[1][0]).toUpperCase();
    }
    return source.slice(0, 2).toUpperCase();
}

async function loadProfileChip() {
    const chip = document.getElementById('profileChip');
    if (!chip) return;
    try {
        await api.ready();
        const data = await api.getCurrentProfile();
        const profile = data && data.profile;
        if (!profile) return; // no loaded user — keep the chip hidden

        const avatarEl = document.getElementById('profileChipAvatar');
        const nameEl = document.getElementById('profileChipName');
        if (avatarEl) avatarEl.textContent = profileChipInitials(profile.display_name, profile.username);
        if (nameEl) nameEl.textContent = profile.display_name || profile.username;
        chip.title = `Switch profile (currently ${profile.display_name || profile.username})`;
        chip.classList.remove('hidden');
    } catch (error) {
        // Fail soft: profile bridge unavailable or no master DB — no chip.
        console.warn('Profile chip unavailable:', error);
    }
}

// =========================================================================
// Status Initialization
// =========================================================================

async function initializeStatus() {
    try {
        await api.ready();
        
        // Update API status
        const apiStatus = document.getElementById('api-status');
        if (apiStatus) {
            apiStatus.classList.add('connected');
        }
        
        // Check database connection
        const connection = await api.checkConnection();
        const dbStatus = document.getElementById('db-status');
        if (dbStatus) {
            if (connection.user_db_connected) {
                dbStatus.classList.add('connected');
            } else {
                dbStatus.classList.add('disconnected');
            }
        }
        
        // Get app info
        const appInfo = await api.getAppInfo();
        const versionEl = document.getElementById('app-version');
        if (versionEl) {
            versionEl.textContent = `Version: ${appInfo.version} (Phase ${appInfo.phase})`;
        }
        
    } catch (error) {
        console.error('Error initializing status:', error);
        document.getElementById('api-status')?.classList.add('disconnected');
        document.getElementById('db-status')?.classList.add('disconnected');
    }
}

// =========================================================================
// Page Initialization
// =========================================================================

async function initializeLandingPage() {
    console.log('🚀 Initializing landing page...');
    
    // Initialize modal
    SuspendModal.init();
    
    // Initialize status
    await initializeStatus();

    // Profile chip in the header (fails soft when no profile is loaded)
    await loadProfileChip();
    
    // Load analytics preview
    await loadAnalyticsPreview();
    
    // Load exams
    await loadExams();
    
    console.log('✅ Landing page initialized');
}

// =========================================================================
// Expose Global Functions for onclick handlers
// =========================================================================

window.openExam = openExam;
window.startNewSession = startNewSession;
window.browseEntries = browseEntries;
window.editExam = editExam;
window.confirmSuspendExam = confirmSuspendExam;
window.reactivateExam = reactivateExam;
window.confirmHardDeleteExam = confirmHardDeleteExam;
window.loadExams = loadExams;

// =========================================================================
// Page Initialization - Run when DOM is ready
// =========================================================================

document.addEventListener('DOMContentLoaded', initializeLandingPage);

// Listen for exam creation events (from wizard)
window.addEventListener('wimi:exam-created', () => {
    Toast.success('Exam Created', 'Your new exam has been set up successfully.');
    loadExams();
});

// Refresh exam cards when the user returns from question_entry / session pages.
// bfcache-restored navigations skip DOMContentLoaded, so we listen for pageshow.
window.addEventListener('pageshow', (e) => {
    if (e.persisted) loadExams();
});

// Refresh when an entry is created or updated elsewhere in the app.
if (window.eventBus && typeof window.eventBus.on === 'function') {
    window.eventBus.on('entry:saved', () => loadExams());
}
