/**
 * WIMI Entry Detail View
 * Phase 5: Entry Detail & Related Topics
 * 
 * Displays full entry details with media gallery and related topics.
 */

class EntryDetail {
    constructor() {
        // State
        this.entryId = null;
        this.examContextId = null;
        this.entry = null;
        this.context = null;
        this.media = [];
        this.relatedTopics = [];
        this.allExamSubjects = [];
        this.currentMediaIndex = 0;

        // Navigation context (from entry browser)
        this.navContext = null;

        // DOM Elements
        this.elements = {};

        // Initialize
        this.init();
    }
    
    async init() {
        console.log('Entry Detail initializing...');

        // Parse URL parameters
        this.parseUrlParams();

        if (!this.entryId) {
            this.showError('No entry ID provided');
            return;
        }

        // Load navigation context from sessionStorage
        this.loadNavContext();

        // Cache DOM elements
        this.cacheElements();

        // Setup event listeners
        this.setupEventListeners();

        // Load entry data
        await this.loadEntryData();

        // Update navigation UI after entry data is loaded
        this.updateNavigationUI();

        console.log('Entry Detail ready');
    }
    
    parseUrlParams() {
        const params = new URLSearchParams(window.location.search);
        this.entryId = parseInt(params.get('entry') || params.get('id'), 10);
        this.examContextId = parseInt(params.get('exam'), 10) || null;
    }
    
    cacheElements() {
        this.elements = {
            // States
            loadingState: document.getElementById('loading-state'),
            errorState: document.getElementById('error-state'),
            errorMessage: document.getElementById('error-message'),
            mainContent: document.getElementById('main-content'),
            
            // Header
            backLink: document.getElementById('back-link'),
            editBtn: document.getElementById('edit-btn'),
            
            // Entry header
            subjectPath: document.getElementById('subject-path'),
            difficultyBadge: document.getElementById('difficulty-badge'),
            sourceName: document.getElementById('source-name'),
            entryDate: document.getElementById('entry-date'),
            questionId: document.getElementById('question-id'),
            timeSpent: document.getElementById('time-spent'),
            timeSeparator: document.getElementById('time-separator'),
            tagsContainer: document.getElementById('tags-container'),
            
            // Answers
            userAnswer: document.getElementById('user-answer'),
            correctAnswer: document.getElementById('correct-answer'),
            
            // Content sections
            reflectionContent: document.getElementById('reflection-content'),
            explanationContent: document.getElementById('explanation-content'),
            
            // Attachments & Notes
            attachmentCount: document.getElementById('attachment-count'),
            attachmentsGrid: document.getElementById('attachments-grid'),
            noAttachments: document.getElementById('no-attachments'),
            notesContent: document.getElementById('notes-content'),
            noNotes: document.getElementById('no-notes'),
            notesTabs: document.getElementById('notes-tabs'),
            notesTabContent: document.getElementById('notes-tab-content'),
            notesCount: document.getElementById('notes-count'),
            
            // Related Topics
            relatedTopicsGrid: document.getElementById('related-topics-grid'),
            noRelatedTopics: document.getElementById('no-related-topics'),
            
            // Lightbox
            lightboxModal: document.getElementById('lightbox-modal'),
            lightboxImage: document.getElementById('lightbox-image'),
            lightboxClose: document.getElementById('lightbox-close'),
            lightboxPrev: document.getElementById('lightbox-prev'),
            lightboxNext: document.getElementById('lightbox-next'),
            lightboxCaption: document.getElementById('lightbox-caption'),

            // Entry Navigation
            prevEntryBtn: document.getElementById('prev-entry-btn'),
            nextEntryBtn: document.getElementById('next-entry-btn'),
            positionIndicator: document.getElementById('position-indicator'),
            entryNavigation: document.querySelector('.entry-navigation'),

            // Export
            exportActions: document.getElementById('export-actions'),
            exportBtn: document.getElementById('export-btn'),
            exportDropdownMenu: document.getElementById('export-dropdown-menu'),
            exportCopyThis: document.getElementById('export-copy-this'),
            exportSessionIds: document.getElementById('export-session-ids')
        };
    }
    
    setupEventListeners() {
        // Back link
        this.elements.backLink.addEventListener('click', (e) => {
            e.preventDefault();
            this.navigateBack();
        });
        
        // Edit button
        this.elements.editBtn.addEventListener('click', (e) => {
            console.log('🔧 DEBUG: Edit button clicked');
            console.log('🔧 DEBUG: Event:', e);
            e.preventDefault();
            e.stopPropagation();
            this.navigateToEdit();
        });
        
        // Lightbox controls
        this.elements.lightboxClose.addEventListener('click', () => this.closeLightbox());
        this.elements.lightboxPrev.addEventListener('click', () => this.prevMedia());
        this.elements.lightboxNext.addEventListener('click', () => this.nextMedia());
        
        // Close lightbox on backdrop click
        this.elements.lightboxModal.querySelector('.lightbox-backdrop')
            .addEventListener('click', () => this.closeLightbox());
        
        // Keyboard navigation for lightbox and entry navigation
        document.addEventListener('keydown', (e) => {
            // Lightbox navigation takes priority when open
            if (this.elements.lightboxModal.classList.contains('active')) {
                switch (e.key) {
                    case 'Escape':
                        this.closeLightbox();
                        break;
                    case 'ArrowLeft':
                        this.prevMedia();
                        break;
                    case 'ArrowRight':
                        this.nextMedia();
                        break;
                }
                return;
            }

            // Entry navigation when lightbox is closed
            if (this.navContext && this.navContext.ids && this.navContext.ids.length > 1) {
                switch (e.key) {
                    case 'ArrowLeft':
                        e.preventDefault();
                        this.navigateToPreviousEntry();
                        break;
                    case 'ArrowRight':
                        e.preventDefault();
                        this.navigateToNextEntry();
                        break;
                }
            }
        });

        // Entry navigation buttons
        if (this.elements.prevEntryBtn) {
            this.elements.prevEntryBtn.addEventListener('click', () => {
                this.navigateToPreviousEntry();
            });
        }

        if (this.elements.nextEntryBtn) {
            this.elements.nextEntryBtn.addEventListener('click', () => {
                this.navigateToNextEntry();
            });
        }

        // Export dropdown toggle
        if (this.elements.exportBtn) {
            this.elements.exportBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.elements.exportDropdownMenu.classList.toggle('open');
            });
        }

        // Close export dropdown on outside click
        document.addEventListener('click', () => {
            if (this.elements.exportDropdownMenu) {
                this.elements.exportDropdownMenu.classList.remove('open');
            }
        });

        // Copy This ID
        if (this.elements.exportCopyThis) {
            this.elements.exportCopyThis.addEventListener('click', () => {
                this.elements.exportDropdownMenu.classList.remove('open');
                this.copyCurrentId();
            });
        }

        // Export Session IDs
        if (this.elements.exportSessionIds) {
            this.elements.exportSessionIds.addEventListener('click', () => {
                this.elements.exportDropdownMenu.classList.remove('open');
                this.exportSessionQuestionIds();
            });
        }
    }
    
    // =========================================================================
    // Data Loading
    // =========================================================================
    
    async loadEntryData() {
        try {
            await api.ready();
            
            // Load entry with full context
            const result = await api.getEntryWithContext(this.entryId);
            
            this.entry = result.entry;
            this.context = {
                session: result.session,
                exam: result.exam,
                source: result.source
            };
            
            // Store exam context ID for navigation
            if (result.exam) {
                this.examContextId = result.exam.id;
            }
            
            // Load media
            await this.loadMedia();
            
            // Load related topics
            await this.loadRelatedTopics();

            // Load all exam subjects for resolving non-entry subject names in note tabs
            await this.loadAllExamSubjects();

            // Render the entry
            this.renderEntry();

            // Show/hide export button
            this.updateExportUI();

            // Show content
            this.showContent();

            // Show any pending toast from navigation wrap
            this.showPendingToast();

        } catch (error) {
            console.error('Failed to load entry:', error);
            this.showError(error.message || 'Failed to load entry');
        }
    }
    
    async loadMedia() {
        try {
            this.media = await api.getQuestionMedia(this.entryId);
        } catch (error) {
            console.error('Failed to load media:', error);
            this.media = [];
        }
    }
    
    async loadRelatedTopics() {
        if (!this.entry.primary_subjects || this.entry.primary_subjects.length === 0) {
            this.relatedTopics = [];
            return;
        }
        
        try {
            // Get related subjects based on the first primary subject
            const primarySubject = this.entry.primary_subjects[0];
            this.relatedTopics = await api.getRelatedSubjects(
                primarySubject.id,
                this.examContextId,
                4  // Limit to 4 related topics
            );
        } catch (error) {
            console.error('Failed to load related topics:', error);
            this.relatedTopics = [];
        }
    }

    async loadAllExamSubjects() {
        if (!this.examContextId) return;
        try {
            this.allExamSubjects = await api.getAllSubjectsForExam(this.examContextId) || [];
        } catch (error) {
            console.error('Failed to load exam subjects:', error);
            this.allExamSubjects = [];
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================
    
    renderEntry() {
        // Render subject path
        this.renderSubjectPath();
        
        // Render difficulty badge
        this.renderDifficultyBadge();
        
        // Render meta info
        this.renderMetaInfo();
        
        // Render tags
        this.renderTags();
        
        // Render answers
        this.renderAnswers();
        
        // Render content sections
        this.renderContentSections();
        
        // Render attachments
        this.renderAttachments();
        
        // Render notes
        this.renderNotes();
        
        // Render related topics
        this.renderRelatedTopics();
    }
    
    renderSubjectPath() {
        const subjects = this.entry.primary_subjects || [];
        
        if (subjects.length === 0) {
            this.elements.subjectPath.textContent = 'No subject assigned';
            return;
        }
        
        // Build path from subject path or construct from subjects
        const pathParts = [];
        
        // Use the path if available, otherwise use subject names
        if (subjects[0].path) {
            const parts = subjects[0].path.split(' > ');
            parts.forEach((part, index) => {
                if (index > 0) {
                    const separator = document.createElement('span');
                    separator.className = 'path-separator';
                    separator.textContent = '→';
                    this.elements.subjectPath.appendChild(separator);
                }
                const span = document.createElement('span');
                span.textContent = part;
                this.elements.subjectPath.appendChild(span);
            });
        } else {
            subjects.forEach((subject, index) => {
                if (index > 0) {
                    const separator = document.createElement('span');
                    separator.className = 'path-separator';
                    separator.textContent = '→';
                    this.elements.subjectPath.appendChild(separator);
                }
                const span = document.createElement('span');
                span.textContent = subject.name;
                this.elements.subjectPath.appendChild(span);
            });
        }
    }
    
    renderDifficultyBadge() {
        const difficulty = this.entry.perceived_difficulty;
        
        if (!difficulty) {
            this.elements.difficultyBadge.style.display = 'none';
            return;
        }
        
        const difficultyMap = {
            1: { label: 'Easy', class: 'easy' },
            2: { label: 'Medium', class: 'medium' },
            3: { label: 'Hard', class: 'hard' },
            4: { label: 'Very Hard', class: 'very-hard' },
            5: { label: 'Very Hard', class: 'very-hard' }
        };
        
        const diffInfo = difficultyMap[difficulty] || { label: 'Unknown', class: '' };
        
        this.elements.difficultyBadge.textContent = diffInfo.label;
        this.elements.difficultyBadge.className = `difficulty-badge ${diffInfo.class}`;
    }
    
    renderMetaInfo() {
        // Source name
        if (this.context.source) {
            this.elements.sourceName.querySelector('.meta-text').textContent = 
                this.context.source.source_name;
        } else if (this.context.session?.session_name) {
            this.elements.sourceName.querySelector('.meta-text').textContent = 
                this.context.session.session_name;
        } else {
            this.elements.sourceName.style.display = 'none';
        }
        
        // Date
        const sessionDate = this.context.session?.date_encountered;
        if (sessionDate) {
            this.elements.entryDate.querySelector('.meta-text').textContent = 
                this.formatDate(sessionDate);
        } else {
            this.elements.entryDate.style.display = 'none';
        }
        
        // Question ID
        if (this.entry.question_id) {
            this.elements.questionId.querySelector('.meta-text').textContent = 
                `Q #${this.entry.question_id}`;
        } else {
            this.elements.questionId.style.display = 'none';
            // Hide preceding separator
            const separators = this.elements.questionId.previousElementSibling;
            if (separators?.classList.contains('meta-separator')) {
                separators.style.display = 'none';
            }
        }
        
        // Time spent
        if (this.entry.time_spent_seconds) {
            this.elements.timeSpent.querySelector('.meta-text').textContent = 
                this.formatTime(this.entry.time_spent_seconds);
        } else {
            this.elements.timeSpent.style.display = 'none';
            this.elements.timeSeparator.style.display = 'none';
        }
    }
    
    renderTags() {
        const tags = this.entry.tags || [];
        this.elements.tagsContainer.innerHTML = '';
        
        if (tags.length === 0) {
            this.elements.tagsContainer.style.display = 'none';
            return;
        }
        
        tags.forEach((tag, index) => {
            const chip = document.createElement('span');
            chip.className = 'tag-chip';
            chip.textContent = tag.name;
            chip.setAttribute('data-testid', `detail-tag-${index}`);

            // Apply color
            const color = tag.color || '#6b7280';
            chip.style.backgroundColor = this.lightenColor(color, 0.85);
            chip.style.borderColor = this.lightenColor(color, 0.6);
            chip.style.color = this.darkenColor(color, 0.2);

            this.elements.tagsContainer.appendChild(chip);
        });
    }
    
    renderAnswers() {
        // User answer
        this.elements.userAnswer.textContent = 
            this.entry.user_answer || 'No answer recorded';
        
        // Correct answer
        this.elements.correctAnswer.textContent = 
            this.entry.correct_answer || 'No correct answer recorded';
    }
    
    renderContentSections() {
        // Reflection - use RichContentRenderer to properly render HTML content
        RichContentRenderer.render(
            this.elements.reflectionContent,
            this.entry.reflection,
            { emptyMessage: 'No reflection provided' }
        );

        // Explanation - use RichContentRenderer to properly render HTML content
        RichContentRenderer.render(
            this.elements.explanationContent,
            this.entry.explanation,
            { emptyMessage: 'No explanation provided' }
        );
    }
    
    renderAttachments() {
        this.elements.attachmentsGrid.innerHTML = '';
        this.elements.attachmentCount.textContent = this.media.length;
        
        if (this.media.length === 0) {
            this.elements.attachmentsGrid.style.display = 'none';
            this.elements.noAttachments.style.display = 'block';
            return;
        }
        
        this.elements.noAttachments.style.display = 'none';
        this.elements.attachmentsGrid.style.display = 'flex';
        
        this.media.forEach((item, index) => {
            const thumb = document.createElement('div');
            thumb.className = 'attachment-thumb';
            thumb.dataset.index = index;
            thumb.setAttribute('data-testid', `detail-attachment-thumb-${index}`);
            
            if (item.thumbnail_url) {
                const img = document.createElement('img');
                img.src = item.thumbnail_url;
                img.alt = item.user_filename || item.original_filename || 'Attachment';
                thumb.appendChild(img);
            } else {
                const placeholder = document.createElement('span');
                placeholder.className = 'placeholder-icon';
                placeholder.textContent = '🖼️';
                thumb.appendChild(placeholder);
            }
            
            // Add exam context badge if available
            if (item.exam_names && item.exam_names.length > 0) {
                const badge = document.createElement('div');
                badge.className = 'thumbnail-exam-badge';
                badge.title = item.exam_names.join(', ');
                badge.textContent = item.exam_names[0];
                thumb.appendChild(badge);
            }

            thumb.addEventListener('click', () => this.openLightbox(index));

            this.elements.attachmentsGrid.appendChild(thumb);
        });
    }
    
    renderNotes() {
        const notesList = this.entry.notes_list || [];

        if (notesList.length > 0) {
            // Show note count
            if (this.elements.notesCount) {
                this.elements.notesCount.textContent = `(${notesList.length})`;
            }

            // Build tabs
            const tabData = this.buildNoteTabs(notesList);
            this.renderNoteTabs(tabData);
            // Show first tab
            const firstKey = tabData.length > 0 ? tabData[0].key : null;
            if (firstKey) this.showNoteTab(firstKey, notesList, tabData);

            this.elements.notesContent.style.display = 'none';
            this.elements.noNotes.style.display = 'none';
            if (this.elements.notesTabs) this.elements.notesTabs.style.display = '';
            if (this.elements.notesTabContent) this.elements.notesTabContent.style.display = '';
        } else if (this.entry.notes && !RichContentRenderer.isEmpty(this.entry.notes)) {
            // Legacy fallback
            if (this.elements.notesTabs) this.elements.notesTabs.style.display = 'none';
            if (this.elements.notesTabContent) this.elements.notesTabContent.style.display = 'none';
            RichContentRenderer.render(
                this.elements.notesContent,
                this.entry.notes,
                { emptyMessage: 'No notes added' }
            );
            this.elements.notesContent.style.display = 'block';
            this.elements.noNotes.style.display = 'none';
            if (this.elements.notesCount) this.elements.notesCount.textContent = '';
        } else {
            if (this.elements.notesTabs) this.elements.notesTabs.style.display = 'none';
            if (this.elements.notesTabContent) this.elements.notesTabContent.style.display = 'none';
            this.elements.notesContent.style.display = 'none';
            this.elements.noNotes.style.display = 'block';
            if (this.elements.notesCount) this.elements.notesCount.textContent = '';
        }
    }

    buildNoteTabs(notesList) {
        const tabs = [];
        const generalNotes = notesList.filter(n => n.is_general);
        if (generalNotes.length > 0) {
            tabs.push({ key: 'general', label: 'General', count: generalNotes.length });
        }

        // Collect all subjects referenced by notes
        const subjectMap = {};
        const entrySubjects = [
            ...(this.entry.primary_subjects || []),
            ...(this.entry.secondary_subjects || [])
        ];
        for (const note of notesList) {
            if (note.linked_subject_ids && note.linked_subject_ids.length > 0) {
                for (const sid of note.linked_subject_ids) {
                    if (!subjectMap[sid]) {
                        // Look up in entry subjects first, then full exam hierarchy
                        let subject = entrySubjects.find(s => s.id === sid);
                        if (!subject && this.allExamSubjects.length > 0) {
                            subject = this.allExamSubjects.find(s => s.id === sid);
                        }
                        subjectMap[sid] = {
                            key: `subject-${sid}`,
                            label: subject ? subject.name : `Subject #${sid}`,
                            count: 0
                        };
                    }
                    subjectMap[sid].count++;
                }
            }
        }
        for (const tab of Object.values(subjectMap)) {
            tabs.push(tab);
        }

        return tabs;
    }

    renderNoteTabs(tabData) {
        const container = this.elements.notesTabs;
        if (!container) return;
        container.innerHTML = '';

        if (tabData.length <= 1) {
            // Single tab — no need for tab bar
            container.style.display = 'none';
            return;
        }

        container.style.display = '';
        for (const tab of tabData) {
            const btn = document.createElement('button');
            btn.className = 'notes-tab';
            btn.dataset.key = tab.key;
            btn.textContent = `${tab.label} (${tab.count})`;
            // Testid: 'detail-notes-tab-general' or 'detail-notes-tab-subject-{subjectId}'
            // tab.key is already either 'general' or 'subject-{id}'
            btn.setAttribute('data-testid', `detail-notes-tab-${tab.key}`);
            btn.addEventListener('click', () => {
                this.showNoteTab(tab.key, this.entry.notes_list || [], tabData);
            });
            container.appendChild(btn);
        }
    }

    showNoteTab(key, notesList, tabData) {
        // Update active tab
        const tabContainer = this.elements.notesTabs;
        if (tabContainer) {
            tabContainer.querySelectorAll('.notes-tab').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.key === key);
            });
        }

        // Filter notes for this tab
        let filtered;
        if (key === 'general') {
            filtered = notesList.filter(n => n.is_general);
        } else {
            const sid = parseInt(key.replace('subject-', ''));
            filtered = notesList.filter(n =>
                n.linked_subject_ids && n.linked_subject_ids.includes(sid)
            );
        }

        // Render notes
        const content = this.elements.notesTabContent;
        if (!content) return;
        content.innerHTML = '';

        for (const note of filtered) {
            if (!note.content_html || RichContentRenderer.isEmpty(note.content_html)) continue;
            const card = document.createElement('div');
            card.className = 'note-display-card';
            RichContentRenderer.render(card, note.content_html, { emptyMessage: '' });
            content.appendChild(card);
        }

        if (content.children.length === 0) {
            content.innerHTML = '<div class="text-muted">No notes in this category</div>';
        }
    }
    
    renderRelatedTopics() {
        this.elements.relatedTopicsGrid.innerHTML = '';
        
        if (this.relatedTopics.length === 0) {
            this.elements.relatedTopicsGrid.style.display = 'none';
            this.elements.noRelatedTopics.style.display = 'block';
            return;
        }
        
        this.elements.noRelatedTopics.style.display = 'none';
        this.elements.relatedTopicsGrid.style.display = 'flex';
        
        this.relatedTopics.forEach(topic => {
            const link = document.createElement('a');
            link.className = 'related-topic-link';
            link.href = '#';
            link.textContent = topic.name;
            link.dataset.subjectId = topic.id;
            link.setAttribute('data-testid', `detail-related-topic-${topic.id}`);

            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigateToSubjectEntries(topic.id, topic.name);
            });

            this.elements.relatedTopicsGrid.appendChild(link);
        });
    }
    
    // =========================================================================
    // Export Question IDs
    // =========================================================================

    /**
     * Show or hide the export button based on whether the entry has a question_id.
     * Called after entry data is loaded and rendered.
     */
    updateExportUI() {
        if (this.elements.exportActions && this.entry && this.entry.question_id) {
            this.elements.exportActions.style.display = '';
        }
    }

    /**
     * Copy the current entry's question_id to clipboard.
     * Uses Qt bridge (primary) with web API and execCommand as fallbacks.
     */
    async copyCurrentId() {
        const qid = this.entry?.question_id;
        if (!qid) return;

        const text = String(qid);
        let success = false;

        // Primary: Qt bridge
        if (typeof api !== 'undefined' && api.copyToClipboard) {
            try {
                await api.copyToClipboard(text);
                success = true;
            } catch (e) { /* fallback below */ }
        }

        // Fallback 1: Clipboard API
        if (!success && navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                success = true;
            } catch (e) { /* fallback below */ }
        }

        // Fallback 2: execCommand
        if (!success) {
            try {
                const temp = document.createElement('textarea');
                temp.value = text;
                temp.style.position = 'fixed';
                temp.style.opacity = '0';
                document.body.appendChild(temp);
                temp.select();
                success = document.execCommand('copy');
                document.body.removeChild(temp);
            } catch (e) { /* ignore */ }
        }

        if (typeof Toast !== 'undefined') {
            if (success) {
                Toast.success(`Copied: ${text}`);
            } else {
                Toast.warning('Could not copy to clipboard');
            }
        }
    }

    /**
     * Fetch all entries in this session and open the export dialog with their question IDs.
     */
    async exportSessionQuestionIds() {
        const sessionId = this.entry?.review_session_id;
        if (!sessionId) return;

        try {
            const entries = await api.getSessionEntries(sessionId);
            const questionIds = [];
            let skippedCount = 0;

            (entries || []).forEach(entry => {
                if (entry.question_id) {
                    questionIds.push(String(entry.question_id));
                } else {
                    skippedCount++;
                }
            });

            if (questionIds.length === 0) {
                if (typeof Toast !== 'undefined') {
                    Toast.warning('No question IDs found in this session');
                }
                return;
            }

            await ExportQuestionIdsDialog.show(questionIds, { skippedCount });
        } catch (error) {
            console.error('Error exporting session IDs:', error);
            if (typeof Toast !== 'undefined') {
                Toast.error('Failed to load session entries');
            }
        }
    }

    // =========================================================================
    // Lightbox
    // =========================================================================
    
    openLightbox(index) {
        this.currentMediaIndex = index;
        this.updateLightboxImage();
        this.elements.lightboxModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
    
    closeLightbox() {
        this.elements.lightboxModal.classList.remove('active');
        document.body.style.overflow = '';
    }
    
    prevMedia() {
        if (this.media.length <= 1) return;
        this.currentMediaIndex = (this.currentMediaIndex - 1 + this.media.length) % this.media.length;
        this.updateLightboxImage();
    }
    
    nextMedia() {
        if (this.media.length <= 1) return;
        this.currentMediaIndex = (this.currentMediaIndex + 1) % this.media.length;
        this.updateLightboxImage();
    }
    
    updateLightboxImage() {
        const item = this.media[this.currentMediaIndex];
        if (!item) return;
        
        this.elements.lightboxImage.src = item.full_url || item.thumbnail_url || '';
        this.elements.lightboxCaption.textContent = 
            item.user_filename || item.original_filename || `Image ${this.currentMediaIndex + 1}`;
        
        // Update nav visibility
        const showNav = this.media.length > 1;
        this.elements.lightboxPrev.style.display = showNav ? 'block' : 'none';
        this.elements.lightboxNext.style.display = showNav ? 'block' : 'none';
    }
    
    // =========================================================================
    // Navigation
    // =========================================================================
    
    navigateBack() {
        // Always go to entry browser for this exam context
        if (this.examContextId) {
            window.location.href = `entry_browser.html?exam=${this.examContextId}`;
        } 
        else {
            // Fallback: try to use history, or go to dashboard
            if (document.referrer.includes('entry_browser.html')) {
                history.back();
            } else {
                window.location.href = 'entry_browser.html';
            }
        }
    }
    
    navigateToEdit() {
        // Navigate to question entry page in edit mode
        console.log('🔧 DEBUG: navigateToEdit() called');
        console.log('🔧 DEBUG: this.entry =', this.entry);
        console.log('🔧 DEBUG: this.entryId =', this.entryId);
        
        if (!this.entry) {
            console.error('❌ DEBUG: this.entry is null/undefined!');
            alert('Error: Entry data not loaded. Cannot edit.');
            return;
        }
        
        const sessionId = this.entry.review_session_id;
        console.log('🔧 DEBUG: sessionId =', sessionId);
        
        if (!sessionId) {
            console.error('❌ DEBUG: sessionId is null/undefined!');
            alert('Error: Session ID not found. Cannot edit.');
            return;
        }
        
        const targetUrl = `question_entry.html?session=${sessionId}&entry=${this.entryId}&edit=true`;
        console.log('🔧 DEBUG: Navigating to:', targetUrl);
        
        window.location.href = targetUrl;
    }
    
    navigateToSubjectEntries(subjectId, subjectName) {
        // Navigate to browser filtered by this subject
        const params = new URLSearchParams();
        if (this.examContextId) params.set('exam', this.examContextId);
        params.set('subject', subjectId);
        window.location.href = `entry_browser.html?${params.toString()}`;
    }

    // =========================================================================
    // Entry Navigation (Prev/Next)
    // =========================================================================

    /**
     * Load navigation context from sessionStorage.
     * This contains the list of entry IDs and current position from the browser.
     */
    loadNavContext() {
        try {
            const stored = sessionStorage.getItem('entryNavContext');
            if (stored) {
                this.navContext = JSON.parse(stored);
                console.log('Loaded navigation context:', this.navContext);

                // Verify current entry is in the list and update index
                if (this.navContext.ids && this.navContext.ids.includes(this.entryId)) {
                    this.navContext.index = this.navContext.ids.indexOf(this.entryId);
                }
            }
        } catch (error) {
            console.error('Failed to load navigation context:', error);
            this.navContext = null;
        }
    }

    /**
     * Update the navigation UI based on current context.
     * Shows/hides navigation buttons and updates position indicator.
     */
    updateNavigationUI() {
        const navEl = this.elements.entryNavigation;
        const prevBtn = this.elements.prevEntryBtn;
        const nextBtn = this.elements.nextEntryBtn;
        const indicator = this.elements.positionIndicator;

        // Hide navigation if no context or only one entry
        if (!this.navContext || !this.navContext.ids || this.navContext.ids.length <= 1) {
            if (navEl) navEl.style.display = 'none';
            return;
        }

        // Show navigation
        if (navEl) navEl.style.display = 'flex';

        // Update position indicator
        const currentPosition = this.navContext.index + 1;
        const totalCount = this.navContext.ids.length;
        if (indicator) {
            indicator.textContent = `${currentPosition} of ${totalCount}`;
        }

        // Enable/disable buttons (always enabled for wrap navigation)
        if (prevBtn) prevBtn.disabled = false;
        if (nextBtn) nextBtn.disabled = false;
    }

    /**
     * Navigate to the previous entry in the list.
     * Wraps from first to last entry with a toast notification.
     */
    navigateToPreviousEntry() {
        if (!this.navContext || !this.navContext.ids || this.navContext.ids.length <= 1) {
            return;
        }

        const currentIndex = this.navContext.index;
        const totalEntries = this.navContext.ids.length;

        let newIndex;
        let toastMessage = null;

        if (currentIndex === 0) {
            // Wrap to last entry
            newIndex = totalEntries - 1;
            toastMessage = 'Continued from last entry';
        } else {
            newIndex = currentIndex - 1;
        }

        this.navigateToEntryAtIndex(newIndex, toastMessage);
    }

    /**
     * Navigate to the next entry in the list.
     * Wraps from last to first entry with a toast notification.
     */
    navigateToNextEntry() {
        if (!this.navContext || !this.navContext.ids || this.navContext.ids.length <= 1) {
            return;
        }

        const currentIndex = this.navContext.index;
        const totalEntries = this.navContext.ids.length;

        let newIndex;
        let toastMessage = null;

        if (currentIndex === totalEntries - 1) {
            // Wrap to first entry
            newIndex = 0;
            toastMessage = 'Returned to first entry';
        } else {
            newIndex = currentIndex + 1;
        }

        this.navigateToEntryAtIndex(newIndex, toastMessage);
    }

    /**
     * Navigate to an entry at a specific index in the navigation list.
     * @param {number} index - The index in navContext.ids to navigate to.
     * @param {string|null} toastMessage - Optional toast message to show after navigation.
     */
    navigateToEntryAtIndex(index, toastMessage = null) {
        if (!this.navContext || !this.navContext.ids) return;

        const entryId = this.navContext.ids[index];
        if (!entryId) return;

        // Update context with new index before navigating
        this.navContext.index = index;
        sessionStorage.setItem('entryNavContext', JSON.stringify(this.navContext));

        // Store toast message to show after page load (if wrapping)
        if (toastMessage) {
            sessionStorage.setItem('entryNavToast', toastMessage);
        }

        // Navigate to the entry
        window.location.href = `entry_detail.html?id=${entryId}`;
    }

    /**
     * Check for and show any pending toast message from navigation wrap.
     * Called after page load.
     */
    showPendingToast() {
        const message = sessionStorage.getItem('entryNavToast');
        if (message && typeof Toast !== 'undefined') {
            sessionStorage.removeItem('entryNavToast');
            Toast.show(message, { type: 'info', duration: 2500 });
        }
    }

    // =========================================================================
    // UI State
    // =========================================================================
    
    showLoading() {
        this.elements.loadingState.style.display = 'flex';
        this.elements.errorState.style.display = 'none';
        this.elements.mainContent.style.display = 'none';
    }
    
    showError(message) {
        this.elements.loadingState.style.display = 'none';
        this.elements.errorState.style.display = 'flex';
        this.elements.errorMessage.textContent = message;
        this.elements.mainContent.style.display = 'none';
    }
    
    showContent() {
        this.elements.loadingState.style.display = 'none';
        this.elements.errorState.style.display = 'none';
        this.elements.mainContent.style.display = 'flex';
    }
    
    // =========================================================================
    // Utilities
    // =========================================================================
    
    formatDate(dateStr) {
        if (!dateStr) return '';
        
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        } catch {
            return dateStr;
        }
    }
    
    formatTime(seconds) {
        if (!seconds) return '';
        
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        
        if (mins === 0) {
            return `${secs}s`;
        } else if (secs === 0) {
            return `${mins}m`;
        } else {
            return `${mins}m ${secs}s`;
        }
    }
    
    lightenColor(color, factor) {
        // Convert hex to RGB, lighten, convert back
        const hex = color.replace('#', '');
        const r = parseInt(hex.substr(0, 2), 16);
        const g = parseInt(hex.substr(2, 2), 16);
        const b = parseInt(hex.substr(4, 2), 16);
        
        const newR = Math.round(r + (255 - r) * factor);
        const newG = Math.round(g + (255 - g) * factor);
        const newB = Math.round(b + (255 - b) * factor);
        
        return `rgb(${newR}, ${newG}, ${newB})`;
    }
    
    darkenColor(color, factor) {
        const hex = color.replace('#', '');
        const r = parseInt(hex.substr(0, 2), 16);
        const g = parseInt(hex.substr(2, 2), 16);
        const b = parseInt(hex.substr(4, 2), 16);
        
        const newR = Math.round(r * (1 - factor));
        const newG = Math.round(g * (1 - factor));
        const newB = Math.round(b * (1 - factor));
        
        return `rgb(${newR}, ${newG}, ${newB})`;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.entryDetail = new EntryDetail();
});
