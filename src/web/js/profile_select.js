/**
 * WIMI Profile Picker
 * Renders the profile card grid, create/rename/delete/restore flows,
 * startup preferences, and the export/import entry points.
 *
 * Runs with NO user database attached — every call here is master-DB-backed
 * (see src/app/bridge_domains/profiles.py).
 *
 * Export/Import are wired against the Task-4 profile transfer API
 * (api.openProfileExportDialog / exportProfile / openProfileImportDialog /
 * readProfileArchive). Those wrappers may not be present yet, so all
 * transfer controls are feature-detected and hidden when absent.
 */

// =========================================================================
// State
// =========================================================================

const ProfileState = {
    profiles: [],
    deleted: [],
    currentUserId: null,
    renameTarget: null,
    deleteTarget: null,
    exportTarget: null,
    deletedOpen: false
};

// Import preview state (populated by readProfileArchive).
const ImportState = {
    preview: null,
    busy: false
};

// sessionStorage handoff key: settings.js (and any other page) stores an
// archive path here, navigates to this page, and the preview modal
// auto-opens on load. Keeps ONE preview implementation for the whole app.
const PENDING_IMPORT_KEY = 'wimi.pendingProfileImport';

// Username rules mirror MasterDatabase._validate_username (master_db.py).
const USERNAME_MIN_LENGTH = 3;
const USERNAME_PATTERN = /^[a-zA-Z0-9_-]+$/;

// =========================================================================
// Helpers
// =========================================================================

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

/** Two-letter initials from a display name (fallback: username). */
function profileInitials(displayName, username) {
    const source = (displayName || username || '?').trim();
    const words = source.split(/\s+/).filter(Boolean);
    if (words.length >= 2) {
        return (words[0][0] + words[1][0]).toUpperCase();
    }
    return source.slice(0, 2).toUpperCase();
}

function formatLastActive(isoString) {
    if (!isoString) return 'Never opened';
    try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return 'Never opened';
        const formatted = date.toLocaleDateString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric'
        });
        return 'Last active ' + formatted;
    } catch (e) {
        return 'Never opened';
    }
}

/**
 * True when the Task-4 profile transfer API is available.
 * Hides export/import controls when the wrappers have not landed yet
 * so this page keeps working standalone.
 */
function transferApiAvailable() {
    return typeof api.openProfileExportDialog === 'function' &&
           typeof api.exportProfile === 'function' &&
           typeof api.openProfileImportDialog === 'function' &&
           typeof api.readProfileArchive === 'function';
}

/** Normalize a file-dialog response ({file_path} | string | null). */
function dialogPath(result) {
    if (!result) return null;
    if (typeof result === 'string') return result;
    return result.file_path || result.dest_path || result.path || null;
}

/** Human-readable byte size ("14.2 MB"). */
function formatBytes(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = Math.max(0, Number(bytes));
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    const rounded = unit === 0 ? Math.round(value) : value.toFixed(1);
    return `${rounded} ${units[unit]}`;
}

// =========================================================================
// Busy Overlay (long-running export/import work)
// =========================================================================

function showBusyOverlay(text) {
    ImportState.busy = true;
    const overlay = document.getElementById('busyOverlay');
    const label = document.getElementById('busyOverlayText');
    if (label) label.textContent = text || 'Working…';
    overlay?.classList.add('active');
}

function hideBusyOverlay() {
    ImportState.busy = false;
    document.getElementById('busyOverlay')?.classList.remove('active');
}

// =========================================================================
// Toasts
// =========================================================================

const Toast = {
    container: null,

    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'pf-toast-container';
            document.body.appendChild(this.container);
        }
    },

    show(type, title, message, duration = 5000) {
        this.init();
        const toast = document.createElement('div');
        toast.className = `pf-toast pf-toast--${type}`;
        toast.setAttribute('data-testid', 'profile-toast');
        toast.innerHTML = `
            <div>
                <p class="pf-toast-title">${escapeHtml(title)}</p>
                ${message ? `<p class="pf-toast-message">${escapeHtml(message)}</p>` : ''}
            </div>
        `;
        this.container.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
        return toast;
    },

    success(title, message) { return this.show('success', title, message); },
    error(title, message) { return this.show('error', title, message); },
    info(title, message) { return this.show('info', title, message); }
};

// =========================================================================
// Rendering
// =========================================================================

function renderProfileCard(profile) {
    const initials = profileInitials(profile.display_name, profile.username);
    const isCurrent = profile.id === ProfileState.currentUserId;
    const exportItem = transferApiAvailable()
        ? `<button type="button" class="profile-menu-item" data-action="export" data-testid="profile-export">Export&hellip;</button>`
        : '';

    return `
        <div class="profile-card" data-user-id="${profile.id}" data-testid="profile-card">
            <button type="button" class="profile-kebab-btn" data-action="menu"
                    data-testid="profile-menu-btn" title="Profile options"
                    aria-label="Options for ${escapeHtml(profile.display_name)}">&#8942;</button>
            <div class="profile-menu hidden" data-testid="profile-menu">
                <button type="button" class="profile-menu-item" data-action="rename" data-testid="profile-rename">Rename</button>
                ${exportItem}
                <button type="button" class="profile-menu-item profile-menu-item--danger" data-action="delete" data-testid="profile-delete">Delete</button>
            </div>
            <button type="button" class="profile-card-main" data-action="select" data-testid="profile-select"
                    aria-label="Open profile ${escapeHtml(profile.display_name)}">
                <div class="profile-avatar">${escapeHtml(initials)}</div>
                <div class="profile-card-name">${escapeHtml(profile.display_name)}</div>
                <div class="profile-card-username">@${escapeHtml(profile.username)}</div>
                <div class="profile-card-lastactive">${escapeHtml(formatLastActive(profile.last_active_at))}</div>
                ${isCurrent ? '<span class="profile-card-current-badge">Currently open</span>' : ''}
            </button>
        </div>
    `;
}

function renderCreateCard() {
    return `
        <div class="profile-card profile-card--create" id="createCard">
            <button type="button" class="profile-card-main" id="createCardOpen" data-testid="profile-create-open">
                <div class="profile-avatar profile-avatar--create">+</div>
                <div class="profile-card-name">New profile</div>
            </button>
            <form class="profile-create-form hidden" id="createForm" data-testid="profile-create-form">
                <label for="createUsername">Username</label>
                <input type="text" id="createUsername" data-testid="profile-create-username"
                       placeholder="e.g. study_account" maxlength="40" autocomplete="off" spellcheck="false">
                <label for="createDisplayName">Display name (optional)</label>
                <input type="text" id="createDisplayName" data-testid="profile-create-display-name"
                       placeholder="Shown on the card" maxlength="80" autocomplete="off">
                <div class="profile-form-error hidden" id="createError" data-testid="profile-create-error"></div>
                <div class="profile-form-actions">
                    <button type="button" class="btn btn-secondary btn-sm" id="createCancelBtn" data-testid="profile-create-cancel">Cancel</button>
                    <button type="submit" class="btn btn-primary btn-sm" id="createSubmitBtn" data-testid="profile-create-submit">Create</button>
                </div>
            </form>
        </div>
    `;
}

function renderDeletedRow(profile) {
    const initials = profileInitials(profile.display_name, profile.username);
    const days = profile.days_remaining;
    const daysLabel = days === 1 ? '1 day remaining' : `${days} days remaining`;
    return `
        <div class="profile-deleted-row" data-user-id="${profile.id}" data-testid="profile-deleted-row">
            <div class="profile-avatar profile-avatar--sm">${escapeHtml(initials)}</div>
            <div class="profile-deleted-info">
                <div class="profile-deleted-name">${escapeHtml(profile.display_name)} <span class="text-muted">@${escapeHtml(profile.username)}</span></div>
                <div class="profile-deleted-days">${escapeHtml(daysLabel)}</div>
            </div>
            <button type="button" class="btn btn-secondary btn-sm" data-action="restore" data-testid="profile-restore">Restore</button>
        </div>
    `;
}

function renderGrid() {
    const grid = document.getElementById('profileGrid');
    if (!grid) return;
    const cards = ProfileState.profiles.map(renderProfileCard).join('');
    grid.innerHTML = cards + renderCreateCard();
    wireCreateCard();
}

function renderDeletedSection() {
    const section = document.getElementById('deletedSection');
    const list = document.getElementById('deletedList');
    const label = document.getElementById('deletedToggleLabel');
    if (!section || !list || !label) return;

    const count = ProfileState.deleted.length;
    if (count === 0) {
        section.classList.add('hidden');
        list.innerHTML = '';
        return;
    }

    section.classList.remove('hidden');
    label.textContent = `Recently deleted (${count})`;
    list.innerHTML = ProfileState.deleted.map(renderDeletedRow).join('');
    list.classList.toggle('hidden', !ProfileState.deletedOpen);
    document.getElementById('deletedCaret')?.classList.toggle('open', ProfileState.deletedOpen);
}

// =========================================================================
// Data Loading
// =========================================================================

async function loadProfiles() {
    try {
        const data = await api.listProfiles();
        ProfileState.profiles = data.profiles || [];
        ProfileState.deleted = data.deleted || [];
        ProfileState.currentUserId = data.current_user_id ?? null;
        renderGrid();
        renderDeletedSection();
    } catch (error) {
        console.error('Failed to load profiles:', error);
        const grid = document.getElementById('profileGrid');
        if (grid) {
            grid.innerHTML = `
                <div class="alert alert-error">
                    <strong>Failed to load profiles:</strong> ${escapeHtml(error.message || 'Unknown error')}
                </div>
            `;
        }
    }
}

/** Show the back link only when a profile is already loaded. */
async function initBackLink() {
    try {
        const data = await api.getCurrentProfile();
        if (data && data.profile) {
            document.getElementById('backToDashboard')?.classList.remove('hidden');
        }
    } catch (e) {
        // No current profile (or master DB unavailable) — keep the link hidden.
        console.warn('getCurrentProfile failed (no back link):', e);
    }
}

async function initStartupPrefs() {
    const checkbox = document.getElementById('alwaysAskCheckbox');
    if (!checkbox) return;
    try {
        const prefs = await api.getProfileStartupPrefs();
        checkbox.checked = !!(prefs && prefs.always_ask);
    } catch (e) {
        console.warn('Failed to load startup prefs:', e);
    }
    checkbox.addEventListener('change', async () => {
        try {
            await api.setProfileStartupPrefs({ always_ask: checkbox.checked });
        } catch (error) {
            console.error('Failed to save startup prefs:', error);
            checkbox.checked = !checkbox.checked; // revert
            Toast.error('Could not save preference', error.message || '');
        }
    });
}

// =========================================================================
// Profile Selection
// =========================================================================

async function selectProfile(userId, triggerButton) {
    if (triggerButton) triggerButton.disabled = true;
    try {
        await api.selectProfile(userId);
        window.location.href = 'index.html';
    } catch (error) {
        console.error('Failed to select profile:', error);
        Toast.error('Could not open profile', error.message || 'Unknown error');
        if (triggerButton) triggerButton.disabled = false;
    }
}

// =========================================================================
// Create Profile
// =========================================================================

function wireCreateCard() {
    const openBtn = document.getElementById('createCardOpen');
    const form = document.getElementById('createForm');
    const cancelBtn = document.getElementById('createCancelBtn');
    if (!openBtn || !form) return;

    openBtn.addEventListener('click', () => {
        openBtn.classList.add('hidden');
        form.classList.remove('hidden');
        document.getElementById('createUsername')?.focus();
    });

    cancelBtn?.addEventListener('click', () => {
        form.classList.add('hidden');
        openBtn.classList.remove('hidden');
        resetCreateForm();
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await submitCreateForm();
    });
}

function resetCreateForm() {
    const username = document.getElementById('createUsername');
    const displayName = document.getElementById('createDisplayName');
    if (username) username.value = '';
    if (displayName) displayName.value = '';
    showCreateError(null);
}

function showCreateError(message) {
    const el = document.getElementById('createError');
    if (!el) return;
    if (message) {
        el.textContent = message;
        el.classList.remove('hidden');
    } else {
        el.textContent = '';
        el.classList.add('hidden');
    }
}

/** Client-side pre-validation mirroring master_db._validate_username. */
function validateUsername(username) {
    if (!username || username.length < USERNAME_MIN_LENGTH) {
        return 'Username must be at least 3 characters';
    }
    if (!USERNAME_PATTERN.test(username)) {
        return 'Username can only contain letters, numbers, hyphens, and underscores';
    }
    return null;
}

async function submitCreateForm() {
    const username = (document.getElementById('createUsername')?.value || '').trim();
    const displayName = (document.getElementById('createDisplayName')?.value || '').trim();
    const submitBtn = document.getElementById('createSubmitBtn');

    const validationError = validateUsername(username);
    if (validationError) {
        showCreateError(validationError);
        return;
    }
    showCreateError(null);

    if (submitBtn) submitBtn.disabled = true;
    try {
        await api.createProfile({
            username: username,
            display_name: displayName || username
        });
        Toast.success('Profile created', `@${username} is ready to use.`);
        await loadProfiles();
    } catch (error) {
        console.error('Failed to create profile:', error);
        showCreateError(error.message || 'Failed to create profile');
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

// =========================================================================
// Kebab Menus (event delegation on the grid)
// =========================================================================

function closeAllMenus() {
    document.querySelectorAll('.profile-menu').forEach((menu) => menu.classList.add('hidden'));
}

function wireGrid() {
    const grid = document.getElementById('profileGrid');
    if (!grid) return;

    grid.addEventListener('click', (e) => {
        const actionEl = e.target.closest('[data-action]');
        if (!actionEl || !grid.contains(actionEl)) return;

        const card = actionEl.closest('.profile-card[data-user-id]');
        const userId = card ? parseInt(card.dataset.userId, 10) : null;
        const profile = ProfileState.profiles.find((p) => p.id === userId) || null;
        const action = actionEl.dataset.action;

        if (action === 'menu') {
            e.stopPropagation();
            const menu = card?.querySelector('.profile-menu');
            const wasHidden = menu?.classList.contains('hidden');
            closeAllMenus();
            if (menu && wasHidden) menu.classList.remove('hidden');
            return;
        }

        closeAllMenus();
        if (!profile) return;

        if (action === 'select') {
            selectProfile(profile.id, actionEl);
        } else if (action === 'rename') {
            openRenameModal(profile);
        } else if (action === 'delete') {
            openDeleteModal(profile);
        } else if (action === 'export') {
            openExportModal(profile);
        }
    });

    // Close menus on any outside click.
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.profile-menu') && !e.target.closest('.profile-kebab-btn')) {
            closeAllMenus();
        }
    });
}

// =========================================================================
// Modal Helpers
// =========================================================================

function openModal(id) {
    document.getElementById(id)?.classList.add('active');
}

function closeModal(id) {
    document.getElementById(id)?.classList.remove('active');
}

function showModalError(elId, message) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (message) {
        el.textContent = message;
        el.classList.remove('hidden');
    } else {
        el.textContent = '';
        el.classList.add('hidden');
    }
}

function wireModalDismissal() {
    ['renameModal', 'deleteModal', 'exportModal', 'importModal'].forEach((id) => {
        const backdrop = document.getElementById(id);
        backdrop?.addEventListener('click', (e) => {
            if (ImportState.busy) return; // no dismissal mid-import/export
            if (e.target === backdrop) closeModal(id);
        });
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !ImportState.busy) {
            ['renameModal', 'deleteModal', 'exportModal', 'importModal'].forEach(closeModal);
        }
    });
}

// =========================================================================
// Rename Flow
// =========================================================================

function openRenameModal(profile) {
    ProfileState.renameTarget = profile;
    const nameEl = document.getElementById('renameModalName');
    const input = document.getElementById('renameInput');
    if (nameEl) nameEl.textContent = `@${profile.username}`;
    if (input) input.value = profile.display_name || '';
    showModalError('renameError', null);
    openModal('renameModal');
    input?.focus();
    input?.select();
}

function wireRenameModal() {
    document.getElementById('renameCancelBtn')?.addEventListener('click', () => closeModal('renameModal'));
    document.getElementById('renameInput')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            document.getElementById('renameSaveBtn')?.click();
        }
    });
    document.getElementById('renameSaveBtn')?.addEventListener('click', async () => {
        const target = ProfileState.renameTarget;
        if (!target) return;
        const newName = (document.getElementById('renameInput')?.value || '').trim();
        if (!newName) {
            showModalError('renameError', 'Display name cannot be empty');
            return;
        }
        const saveBtn = document.getElementById('renameSaveBtn');
        if (saveBtn) saveBtn.disabled = true;
        try {
            await api.renameProfile(target.id, newName);
            closeModal('renameModal');
            Toast.success('Profile renamed', `@${target.username} is now "${newName}".`);
            await loadProfiles();
        } catch (error) {
            console.error('Failed to rename profile:', error);
            showModalError('renameError', error.message || 'Failed to rename profile');
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    });
}

// =========================================================================
// Delete Flow
// =========================================================================

function openDeleteModal(profile) {
    ProfileState.deleteTarget = profile;
    const nameEl = document.getElementById('deleteModalName');
    if (nameEl) nameEl.textContent = `${profile.display_name} (@${profile.username})`;
    showModalError('deleteError', null);
    openModal('deleteModal');
}

function wireDeleteModal() {
    document.getElementById('deleteCancelBtn')?.addEventListener('click', () => closeModal('deleteModal'));
    document.getElementById('deleteConfirmBtn')?.addEventListener('click', async () => {
        const target = ProfileState.deleteTarget;
        if (!target) return;
        const confirmBtn = document.getElementById('deleteConfirmBtn');
        if (confirmBtn) confirmBtn.disabled = true;
        try {
            await api.deleteProfile(target.id);
            closeModal('deleteModal');
            Toast.success('Profile deleted', `${target.display_name} can be restored for 10 days.`);
            await loadProfiles();
        } catch (error) {
            console.error('Failed to delete profile:', error);
            showModalError('deleteError', error.message || 'Failed to delete profile');
        } finally {
            if (confirmBtn) confirmBtn.disabled = false;
        }
    });
}

// =========================================================================
// Restore Flow
// =========================================================================

function wireDeletedSection() {
    document.getElementById('deletedToggle')?.addEventListener('click', () => {
        ProfileState.deletedOpen = !ProfileState.deletedOpen;
        renderDeletedSection();
    });

    document.getElementById('deletedList')?.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action="restore"]');
        if (!btn) return;
        const row = btn.closest('.profile-deleted-row[data-user-id]');
        const userId = row ? parseInt(row.dataset.userId, 10) : null;
        if (!userId) return;
        btn.disabled = true;
        try {
            await api.restoreProfile(userId);
            Toast.success('Profile restored', 'The profile is active again.');
            await loadProfiles();
        } catch (error) {
            console.error('Failed to restore profile:', error);
            Toast.error('Could not restore profile', error.message || 'Unknown error');
            btn.disabled = false;
        }
    });
}

// =========================================================================
// Export Flow (Task-4 transfer API, feature-detected)
// =========================================================================

function openExportModal(profile) {
    if (!transferApiAvailable()) return;
    ProfileState.exportTarget = profile;
    const nameEl = document.getElementById('exportModalName');
    if (nameEl) nameEl.textContent = `${profile.display_name} (@${profile.username})`;
    showModalError('exportError', null);
    openModal('exportModal');
}

function wireExportModal() {
    document.getElementById('exportCancelBtn')?.addEventListener('click', () => closeModal('exportModal'));
    document.getElementById('exportConfirmBtn')?.addEventListener('click', async () => {
        const target = ProfileState.exportTarget;
        if (!target || !transferApiAvailable()) return;

        const includeMedia = !!document.getElementById('exportIncludeMedia')?.checked;
        const confirmBtn = document.getElementById('exportConfirmBtn');
        const originalText = confirmBtn?.textContent;
        showModalError('exportError', null);

        try {
            const dialogResult = await api.openProfileExportDialog({
                default_filename: `${target.username}.wimi`
            });
            const destPath = dialogPath(dialogResult);
            if (!destPath) return; // user cancelled the save dialog

            if (confirmBtn) {
                confirmBtn.disabled = true;
                confirmBtn.innerHTML = '<span class="spinner spinner-sm"></span> Exporting&hellip;';
            }
            showBusyOverlay('Exporting profile…');

            await api.exportProfile({
                user_id: target.id,
                include_media: includeMedia,
                dest_path: destPath
            });

            closeModal('exportModal');
            Toast.success('Profile exported', destPath);
        } catch (error) {
            console.error('Failed to export profile:', error);
            showModalError('exportError', error.message || 'Failed to export profile');
        } finally {
            hideBusyOverlay();
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.textContent = originalText;
            }
        }
    });
}

// =========================================================================
// Import Flow (Task-4 transfer API, feature-detected)
// =========================================================================

function wireImportButton() {
    const importBtn = document.getElementById('importProfileBtn');
    if (!importBtn) return;

    if (!transferApiAvailable()) {
        importBtn.classList.add('hidden');
        return;
    }

    importBtn.addEventListener('click', async () => {
        try {
            const dialogResult = await api.openProfileImportDialog();
            const archivePath = dialogPath(dialogResult);
            if (!archivePath) return; // user cancelled

            // Hand off to the import preview flow. Task 6 builds the preview
            // modal on top of this event.
            window.dispatchEvent(new CustomEvent('wimi:profile-import-requested', {
                detail: { path: archivePath }
            }));
        } catch (error) {
            console.error('Failed to open import dialog:', error);
            Toast.error('Import failed', error.message || 'Could not open the file dialog');
        }
    });
}

/**
 * Read an archive and open the import preview modal.
 * Entry points: the footer Import button (via the custom event below) and
 * the sessionStorage handoff from settings.js (consumePendingImport).
 */
async function handleImportRequest(archivePath) {
    if (!archivePath || !transferApiAvailable()) return;
    showBusyOverlay('Reading archive…');
    try {
        const preview = await api.readProfileArchive(archivePath);
        hideBusyOverlay();
        openImportPreviewModal(preview);
    } catch (error) {
        hideBusyOverlay();
        console.error('Failed to read profile archive:', error);
        Toast.error('Could not read archive', error.message || 'Unknown error');
    }
}

window.addEventListener('wimi:profile-import-requested', (e) => {
    handleImportRequest(e.detail && e.detail.path);
});

/** Populate and open the import preview modal for a readProfileArchive payload. */
function openImportPreviewModal(preview) {
    ImportState.preview = preview;

    const manifest = preview.manifest || {};
    const user = manifest.user || {};
    const stats = manifest.stats || {};
    const media = preview.media || {};
    const schema = preview.schema || {};
    const collision = preview.collision || {};

    // ---- Who ----
    const displayName = user.display_name || user.username || 'Unknown profile';
    const avatarEl = document.getElementById('importAvatar');
    if (avatarEl) avatarEl.textContent = profileInitials(user.display_name, user.username);
    const nameEl = document.getElementById('importDisplayName');
    if (nameEl) nameEl.textContent = displayName;
    const userEl = document.getElementById('importUsername');
    if (userEl) userEl.textContent = user.username ? `@${user.username}` : '';

    // ---- Stats ----
    const statsEl = document.getElementById('importStats');
    if (statsEl) {
        const items = [
            { label: 'Entries', value: stats.entries },
            { label: 'Sessions', value: stats.sessions },
            { label: 'Exams', value: stats.exam_contexts }
        ];
        statsEl.innerHTML = items.map((item) => `
            <div class="profile-import-stat">
                <div class="profile-import-stat-value">${escapeHtml(item.value ?? 0)}</div>
                <div class="profile-import-stat-label">${escapeHtml(item.label)}</div>
            </div>
        `).join('');
    }

    // ---- Media ----
    const mediaEl = document.getElementById('importMediaInfo');
    if (mediaEl) {
        mediaEl.classList.remove('profile-import-media--warning');
        if (media.included) {
            const count = media.file_count || 0;
            const size = formatBytes(media.total_bytes || 0);
            mediaEl.textContent = count === 1
                ? `Includes 1 media file (${size})`
                : `Includes ${count} media files (${size})`;
        } else if (media.db_references_media) {
            mediaEl.textContent = 'Images referenced but not included — they will appear missing.';
            mediaEl.classList.add('profile-import-media--warning');
        } else {
            mediaEl.textContent = 'No media files.';
        }
    }

    // ---- Schema verdict ----
    const schemaBlocked = schema.verdict === 'newer_app_required';
    const noteEl = document.getElementById('importSchemaNote');
    if (noteEl) {
        noteEl.classList.remove('profile-import-note--error');
        if (schemaBlocked) {
            noteEl.textContent = schema.reason ||
                'This profile was exported from a newer version of WIMI. Update WIMI to import it.';
            noteEl.classList.add('profile-import-note--error');
            noteEl.classList.remove('hidden');
        } else if (schema.verdict === 'will_upgrade') {
            noteEl.textContent =
                'This profile was exported from an older version of WIMI and will be upgraded during import.';
            noteEl.classList.remove('hidden');
        } else {
            // 'ok' — stay silent.
            noteEl.textContent = '';
            noteEl.classList.add('hidden');
        }
    }

    // ---- Mode choice: create ----
    const createRadio = document.getElementById('importModeCreate');
    const replaceRadio = document.getElementById('importModeReplace');
    if (createRadio) createRadio.checked = true;
    if (replaceRadio) replaceRadio.checked = false;

    const suggestedEl = document.getElementById('importSuggestedName');
    if (suggestedEl) {
        if (collision.username_exists && collision.suggested_username) {
            suggestedEl.textContent =
                `@${user.username || ''} already exists — will be created as @${collision.suggested_username}`;
            suggestedEl.classList.remove('hidden');
        } else {
            suggestedEl.textContent = '';
            suggestedEl.classList.add('hidden');
        }
    }

    // ---- Mode choice: replace ----
    const targetSelect = document.getElementById('importReplaceTarget');
    if (targetSelect) {
        const targets = preview.replace_targets || [];
        const options = ['<option value="">Choose a profile to replace…</option>'];
        targets.forEach((t) => {
            const label = `${t.display_name || t.username} (@${t.username})` +
                (t.is_current ? ' — currently open' : '');
            options.push(
                `<option value="${t.user_id}" ${t.is_current ? 'disabled' : ''}>${escapeHtml(label)}</option>`
            );
        });
        targetSelect.innerHTML = options.join('');
        targetSelect.value = '';
    }
    const replaceConfirm = document.getElementById('importReplaceConfirm');
    if (replaceConfirm) replaceConfirm.checked = false;
    const hintEl = document.getElementById('importReplaceHint');
    if (hintEl) {
        const hasCurrent = (preview.replace_targets || []).some((t) => t.is_current);
        if (hasCurrent) {
            hintEl.textContent =
                'The currently open profile cannot be replaced — switch to another profile first.';
            hintEl.classList.remove('hidden');
        } else {
            hintEl.textContent = '';
            hintEl.classList.add('hidden');
        }
    }
    document.getElementById('importReplaceOptions')?.classList.add('hidden');

    showModalError('importError', null);
    updateImportControls();
    openModal('importModal');
}

/** Enable/disable the Import button based on verdict + mode + replace inputs. */
function updateImportControls() {
    const preview = ImportState.preview;
    const confirmBtn = document.getElementById('importConfirmBtn');
    const modeChoice = document.getElementById('importModeChoice');
    if (!confirmBtn) return;

    const schemaBlocked = !!(preview && preview.schema &&
        preview.schema.verdict === 'newer_app_required');
    modeChoice?.classList.toggle('profile-import-modes--disabled', schemaBlocked);
    // Disable the radios/select/checkbox wholesale when the archive is
    // blocked (per-<option> disabled state is baked into the markup).
    modeChoice?.querySelectorAll('input, select').forEach((el) => {
        el.disabled = schemaBlocked;
    });

    if (schemaBlocked) {
        confirmBtn.disabled = true;
        return;
    }

    const replaceMode = !!document.getElementById('importModeReplace')?.checked;
    document.getElementById('importReplaceOptions')?.classList.toggle('hidden', !replaceMode);

    if (!replaceMode) {
        confirmBtn.disabled = false;
        return;
    }

    const targetSelect = document.getElementById('importReplaceTarget');
    const targetId = targetSelect && targetSelect.value ? parseInt(targetSelect.value, 10) : null;
    const target = (preview?.replace_targets || []).find((t) => t.user_id === targetId) || null;
    const confirmed = !!document.getElementById('importReplaceConfirm')?.checked;
    confirmBtn.disabled = !(target && !target.is_current && confirmed);
}

/** Run executeProfileImport for the current modal state. */
async function executeImportFromModal() {
    const preview = ImportState.preview;
    if (!preview || !transferApiAvailable()) return;

    const replaceMode = !!document.getElementById('importModeReplace')?.checked;
    const params = {
        archive_path: preview.path,
        mode: replaceMode ? 'replace' : 'create'
    };
    if (replaceMode) {
        const targetSelect = document.getElementById('importReplaceTarget');
        const targetId = targetSelect && targetSelect.value ? parseInt(targetSelect.value, 10) : null;
        if (!targetId) return;
        params.target_user_id = targetId;
        params.confirm_replace = !!document.getElementById('importReplaceConfirm')?.checked;
    }

    showModalError('importError', null);
    const confirmBtn = document.getElementById('importConfirmBtn');
    if (confirmBtn) confirmBtn.disabled = true;
    showBusyOverlay('Importing profile…');
    try {
        const result = await api.executeProfileImport(params);
        hideBusyOverlay();
        closeModal('importModal');
        ImportState.preview = null;
        Toast.success(
            'Profile imported',
            `${result.display_name || result.username} (@${result.username})`
        );
        (result.warnings || []).forEach((warning) => Toast.info('Import note', warning));
        await loadProfiles();
    } catch (error) {
        hideBusyOverlay();
        console.error('Failed to import profile:', error);
        showModalError('importError', error.message || 'Failed to import profile');
        updateImportControls();
    }
}

function wireImportModal() {
    document.getElementById('importCancelBtn')?.addEventListener('click', () => {
        if (ImportState.busy) return;
        closeModal('importModal');
        ImportState.preview = null;
    });
    document.getElementById('importModeCreate')?.addEventListener('change', updateImportControls);
    document.getElementById('importModeReplace')?.addEventListener('change', updateImportControls);
    document.getElementById('importReplaceTarget')?.addEventListener('change', updateImportControls);
    document.getElementById('importReplaceConfirm')?.addEventListener('change', updateImportControls);
    document.getElementById('importConfirmBtn')?.addEventListener('click', executeImportFromModal);
}

/**
 * sessionStorage handoff (see PENDING_IMPORT_KEY): another page picked an
 * archive and navigated here — auto-open the preview modal for it.
 */
function consumePendingImport() {
    let path = null;
    try {
        path = sessionStorage.getItem(PENDING_IMPORT_KEY);
        if (path) sessionStorage.removeItem(PENDING_IMPORT_KEY);
    } catch (e) {
        console.warn('sessionStorage unavailable for pending import:', e);
        return;
    }
    if (path) handleImportRequest(path);
}

// =========================================================================
// Page Initialization
// =========================================================================

async function initializeProfileSelectPage() {
    wireGrid();
    wireModalDismissal();
    wireRenameModal();
    wireDeleteModal();
    wireExportModal();
    wireImportButton();
    wireImportModal();
    wireDeletedSection();

    try {
        await api.ready();
    } catch (error) {
        console.error('Bridge connection failed:', error);
        return; // _bridge.js shows the connection-error overlay
    }

    await Promise.all([
        loadProfiles(),
        initBackLink(),
        initStartupPrefs()
    ]);

    // Auto-open the import preview when another page handed us an archive
    // path (e.g. the Settings page's "Import profile…" button).
    consumePendingImport();
}

document.addEventListener('DOMContentLoaded', initializeProfileSelectPage);
