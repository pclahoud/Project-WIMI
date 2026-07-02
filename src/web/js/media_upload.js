/**
 * Media Upload Component for WIMI
 * Handles image upload via paste, drag-drop, and file picker
 * 
 * Phase 4 Stage 5
 */

class MediaUpload {
    /**
     * Create a MediaUpload component
     * @param {HTMLElement} container - Container element for the component
     * @param {Object} options - Configuration options
     * @param {number} options.entryId - Question entry ID
     * @param {number} options.examContextId - Exam context ID for image browser
     * @param {Function} options.onUpload - Callback when media is uploaded
     * @param {Function} options.onDelete - Callback when media is deleted
     * @param {Function} options.onError - Callback for errors
     */
    constructor(container, options = {}) {
        this.container = container;
        this.entryId = options.entryId || null;
        this.examContextId = options.examContextId || null;
        this.onUpload = options.onUpload || (() => {});
        this.onDelete = options.onDelete || (() => {});
        this.onError = options.onError || ((err) => console.error(err));
        this.onSubjectAssigned = options.onSubjectAssigned || null;

        this.mediaItems = [];
        this.isUploading = false;
        this.imageBrowser = null;

        // Dimension support
        this.isMultiDimensional = false;
        this.dimensions = [];

        // Subject assignment support
        this.entrySubjects = []; // Subjects assigned to the current entry
        this.currentSubjectAssignmentMedia = null; // Media item being assigned
        this.subjectAssignmentCallback = null; // Callback after assignment

        this.init();
    }
    
    /**
     * Initialize the component
     */
    init() {
        this.render();
        this.setupEventListeners();
        this.checkMultiDimensional();
    }

    /**
     * Check if exam uses multi-dimensional system and load dimensions
     */
    async checkMultiDimensional() {
        if (!this.examContextId || !window.api) return;

        try {
            const result = await window.api.examUsesDimensions(this.examContextId);
            this.isMultiDimensional = result?.uses_dimensions || false;

            if (this.isMultiDimensional) {
                const dimensions = await window.api.getDimensions(this.examContextId);
                this.dimensions = dimensions || [];
                // Re-render thumbnails if we have media loaded
                if (this.mediaItems.length > 0) {
                    this.renderThumbnails();
                }
            }
        } catch (error) {
            console.error('Failed to check multi-dimensional status:', error);
        }
    }
    
    /**
     * Render the component HTML
     */
    render() {
        this.container.innerHTML = `
            <div class="media-upload-component">
                <div class="media-dropzone" id="media-dropzone" data-testid="entry-form-media-dropzone">
                    <div class="dropzone-content">
                        <span class="dropzone-icon">📎</span>
                        <span class="dropzone-text">
                            Drop images here, paste (Ctrl+V), or
                            <button type="button" class="btn-link" id="media-browse-btn" data-testid="entry-form-media-browse-button">browse files</button>
                        </span>
                        <input type="file" id="media-file-input" multiple accept="image/*" hidden>
                        <button type="button" class="btn btn-sm btn-secondary" id="media-browse-existing-btn" style="margin-top: 8px;" data-testid="entry-form-media-browse-existing-button">
                            🔍 Browse Existing Images
                        </button>
                    </div>
                    <div class="dropzone-uploading" style="display: none;">
                        <span class="spinner"></span>
                        <span>Uploading...</span>
                    </div>
                </div>

                <div class="media-grid" id="media-grid"></div>

                <div class="media-actions" id="media-actions" style="display: none;">
                    <button type="button" class="btn btn-ghost btn-sm" id="media-sort-btn" data-testid="entry-form-media-sort-button">
                        ↕ Sort by Name
                    </button>
                </div>
            </div>

            <!-- Full-size image modal -->
            <div class="media-modal" id="media-modal" style="display: none;" data-testid="entry-form-media-modal">
                <div class="media-modal-backdrop"></div>
                <div class="media-modal-content">
                    <button type="button" class="media-modal-close" id="media-modal-close" data-testid="entry-form-media-modal-close-button">×</button>
                    <img id="media-modal-image" src="" alt="Full size image">
                    <div class="media-modal-caption" id="media-modal-caption"></div>
                </div>
            </div>

            <!-- Rename modal -->
            <div class="media-rename-modal" id="media-rename-modal" style="display: none;" data-testid="entry-form-media-rename-modal">
                <div class="media-modal-backdrop"></div>
                <div class="media-rename-content">
                    <h4>Rename Image</h4>
                    <input type="text" id="media-rename-input" class="form-input" placeholder="Enter new name" data-testid="entry-form-media-rename-input">
                    <div class="media-rename-actions">
                        <button type="button" class="btn btn-secondary btn-sm" id="media-rename-cancel" data-testid="entry-form-media-rename-cancel-button">Cancel</button>
                        <button type="button" class="btn btn-primary btn-sm" id="media-rename-save" data-testid="entry-form-media-rename-save-button">Save</button>
                    </div>
                </div>
            </div>
            
            <!-- Delete confirmation modal -->
            <div class="media-delete-modal" id="media-delete-modal" style="display: none;" data-testid="entry-form-media-delete-modal">
                <div class="media-modal-backdrop"></div>
                <div class="media-delete-content">
                    <h4>Remove Image</h4>
                    <p class="media-delete-filename" id="media-delete-filename"></p>
                    <p>How would you like to remove this image?</p>
                    <div class="media-delete-options">
                        <button type="button" class="btn btn-secondary btn-block" id="media-delete-unassign" data-testid="entry-form-media-delete-unassign-button">
                            <span class="btn-icon">🔗</span>
                            <span class="btn-text">
                                <strong>Remove from Entry</strong>
                                <small>Image stays in database for reuse</small>
                            </span>
                        </button>
                        <button type="button" class="btn btn-danger btn-block" id="media-delete-permanent" data-testid="entry-form-media-delete-permanent-button">
                            <span class="btn-icon">🗑️</span>
                            <span class="btn-text">
                                <strong>Delete Permanently</strong>
                                <small>Cannot be undone</small>
                            </span>
                        </button>
                    </div>
                    <div class="media-delete-actions">
                        <button type="button" class="btn btn-ghost btn-sm" id="media-delete-cancel" data-testid="entry-form-media-delete-cancel-button">Cancel</button>
                    </div>
                </div>
            </div>

            <!-- Subject Assignment Modal -->
            <div class="media-subject-modal" id="media-subject-modal" style="display: none;" data-testid="entry-form-media-subject-modal">
                <div class="media-modal-backdrop"></div>
                <div class="media-subject-content">
                    <h4>Assign Subjects to Image</h4>
                    <div class="media-subject-preview" id="media-subject-preview"></div>
                    <p class="media-subject-hint">Select which subjects this image relates to:</p>
                    <div class="media-subject-list" id="media-subject-list"></div>
                    <div class="media-subject-actions">
                        <button type="button" class="btn btn-secondary btn-sm" id="media-subject-cancel" data-testid="entry-form-media-subject-cancel-button">
                            Cancel
                        </button>
                        <button type="button" class="btn btn-primary btn-sm" id="media-subject-save" disabled data-testid="entry-form-media-subject-save-button">
                            Save Assignment
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // Cache DOM elements
        this.dropzone = this.container.querySelector('#media-dropzone');
        this.dropzoneContent = this.container.querySelector('.dropzone-content');
        this.dropzoneUploading = this.container.querySelector('.dropzone-uploading');
        this.fileInput = this.container.querySelector('#media-file-input');
        this.browseBtn = this.container.querySelector('#media-browse-btn');
        this.grid = this.container.querySelector('#media-grid');
        this.actionsBar = this.container.querySelector('#media-actions');
        this.sortBtn = this.container.querySelector('#media-sort-btn');
        
        // Modals
        this.fullModal = this.container.querySelector('#media-modal');
        this.fullModalImage = this.container.querySelector('#media-modal-image');
        this.fullModalCaption = this.container.querySelector('#media-modal-caption');
        this.renameModal = this.container.querySelector('#media-rename-modal');
        this.renameInput = this.container.querySelector('#media-rename-input');
        this.deleteModal = this.container.querySelector('#media-delete-modal');
        this.subjectModal = this.container.querySelector('#media-subject-modal');
        this.subjectPreview = this.container.querySelector('#media-subject-preview');
        this.subjectList = this.container.querySelector('#media-subject-list');
        this.subjectSaveBtn = this.container.querySelector('#media-subject-save');
        this.subjectCancelBtn = this.container.querySelector('#media-subject-cancel');
    }
    
    /**
     * Set up event listeners
     */
    setupEventListeners() {
        // Browse button (file picker)
        this.browseBtn.addEventListener('click', () => this.fileInput.click());

        // Browse existing images button
        const browseExistingBtn = this.container.querySelector('#media-browse-existing-btn');
        if (browseExistingBtn) {
            browseExistingBtn.addEventListener('click', () => this.openImageBrowser());
        }

        // File input change
        this.fileInput.addEventListener('change', (e) => {
            this.handleFiles(e.target.files);
            this.fileInput.value = ''; // Reset for same file selection
        });

        // Drag and drop
        this.dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.dropzone.classList.add('dragover');
        });

        this.dropzone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.dropzone.classList.remove('dragover');
        });

        this.dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.dropzone.classList.remove('dragover');

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.handleFiles(files);
            }
        });

        // Paste handler (attached to document for global paste)
        this.pasteHandler = (e) => this.handlePaste(e);
        document.addEventListener('paste', this.pasteHandler);

        // Sort button
        this.sortBtn.addEventListener('click', () => this.sortByName());
        
        // Modal close handlers
        this.container.querySelector('#media-modal-close').addEventListener('click', () => this.closeFullModal());
        this.container.querySelector('.media-modal-backdrop').addEventListener('click', () => this.closeFullModal());
        
        // Rename modal handlers
        this.container.querySelector('#media-rename-cancel').addEventListener('click', () => this.closeRenameModal());
        this.container.querySelector('#media-rename-save').addEventListener('click', () => this.saveRename());
        this.renameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.saveRename();
            if (e.key === 'Escape') this.closeRenameModal();
        });
        
        // Delete modal handlers
        this.container.querySelector('#media-delete-cancel').addEventListener('click', () => this.closeDeleteModal());
        this.container.querySelector('#media-delete-unassign').addEventListener('click', () => this.confirmRemoveFromEntry());
        this.container.querySelector('#media-delete-permanent').addEventListener('click', () => this.confirmDeletePermanent());

        // Subject assignment modal handlers
        this.subjectSaveBtn.addEventListener('click', () => this.saveSubjectAssignment());
        this.subjectCancelBtn.addEventListener('click', () => this.closeSubjectAssignmentModal());

        // Escape key to close modals
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeFullModal();
                this.closeRenameModal();
                this.closeDeleteModal();
                this.closeSubjectAssignmentModal();
            }
        });
    }
    
    /**
     * Handle paste event
     */
    handlePaste(e) {
        // Only handle if this component's container is visible
        if (!this.container.offsetParent) return;
        
        const items = e.clipboardData?.items;
        if (!items) return;
        
        const imageFiles = [];
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (file) {
                    imageFiles.push(file);
                }
            }
        }
        
        if (imageFiles.length > 0) {
            e.preventDefault();
            this.handleFiles(imageFiles);
        }
    }
    
    /**
     * Handle files from any source (paste, drop, picker)
     */
    async handleFiles(files) {
        if (!this.entryId) {
            this.onError('Please save the entry first before adding images.');
            return;
        }
        
        const validFiles = Array.from(files).filter(file => {
            if (!file.type.startsWith('image/')) {
                this.onError(`${file.name} is not an image file.`);
                return false;
            }
            return true;
        });
        
        if (validFiles.length === 0) return;
        
        this.setUploading(true);
        
        for (const file of validFiles) {
            try {
                await this.uploadFile(file);
            } catch (error) {
                this.onError(`Failed to upload ${file.name}: ${error.message}`);
            }
        }
        
        this.setUploading(false);
    }
    
    /**
     * Upload a single file
     */
    async uploadFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            
            reader.onload = async (e) => {
                const base64Data = e.target.result;
                
                try {
                    const result = await this.callApi('addQuestionMedia', 
                        this.entryId, 
                        base64Data, 
                        file.name, 
                        file.type
                    );
                    
                    if (result.success) {
                        this.mediaItems.push(result.data);
                        this.renderThumbnails();
                        this.onUpload(result.data);

                        // Show subject assignment modal if entry has subjects
                        if (this.entrySubjects.length > 0) {
                            this.showSubjectAssignmentModal(result.data);
                        }

                        resolve(result.data);
                    } else {
                        reject(new Error(result.error || 'Upload failed'));
                    }
                } catch (error) {
                    reject(error);
                }
            };
            
            reader.onerror = () => reject(new Error('Failed to read file'));
            reader.readAsDataURL(file);
        });
    }
    
    /**
     * Call API method
     * The WIMIApi methods already handle parsing and throw on error
     */
    async callApi(method, ...args) {
        if (!window.api) {
            throw new Error('API not initialized');
        }
        
        if (typeof window.api[method] !== 'function') {
            throw new Error(`API method ${method} not available`);
        }
        
        try {
            const data = await window.api[method](...args);
            return { success: true, data: data };
        } catch (error) {
            console.error(`[MediaUpload] ${method} failed:`, error);
            return { success: false, error: error.message };
        }
    }
    
    /**
     * Set uploading state
     */
    setUploading(isUploading) {
        this.isUploading = isUploading;
        this.dropzoneContent.style.display = isUploading ? 'none' : 'flex';
        this.dropzoneUploading.style.display = isUploading ? 'flex' : 'none';
    }
    
    /**
     * Set the entry ID (when entry is created/loaded)
     */
    setEntryId(entryId) {
        this.entryId = entryId;
    }

    /**
     * Set the exam context ID (for image browser and dimension support)
     */
    setExamContextId(examContextId) {
        const changed = this.examContextId !== examContextId;
        this.examContextId = examContextId;
        if (changed) {
            this.checkMultiDimensional();
        }
    }

    /**
     * Open the image browser to select existing images
     */
    openImageBrowser() {
        if (!window.ImageBrowser) {
            this.onError('Image browser component not available');
            return;
        }

        this.imageBrowser = new window.ImageBrowser({
            onSelect: (mediaItem) => this.handleExistingImageSelected(mediaItem),
            onClose: () => {
                this.imageBrowser = null;
            }
        });

        this.imageBrowser.open();
    }

    /**
     * Handle selection of an existing image from the browser
     */
    async handleExistingImageSelected(mediaItem) {
        // Check if this image is already attached
        const alreadyAttached = this.mediaItems.some(m => m.id === mediaItem.id);
        if (alreadyAttached) {
            this.onError('This image is already attached to this entry');
            return;
        }

        // Persist the junction link if entry is already saved
        if (this.entryId) {
            try {
                await window.api.attachMediaToEntry(mediaItem.id, this.entryId);
            } catch (err) {
                console.error('Failed to attach media to entry:', err);
            }
        }

        // Add to local list and render
        this.mediaItems.push(mediaItem);
        this.renderThumbnails();
        this.onUpload(mediaItem);

        // Show subject assignment modal if entry has subjects
        if (this.entrySubjects.length > 0) {
            this.showSubjectAssignmentModal(mediaItem);
        }
    }

    /**
     * Load media for an entry
     */
    async loadMedia(entryId) {
        this.entryId = entryId;
        this.mediaItems = [];
        
        if (!entryId) {
            this.renderThumbnails();
            return;
        }
        
        try {
            const result = await this.callApi('getQuestionMedia', entryId);
            if (result.success) {
                this.mediaItems = result.data || [];
                this.renderThumbnails();
            }
        } catch (error) {
            console.error('Failed to load media:', error);
        }
    }
    
    /**
     * Render thumbnail grid
     */
    renderThumbnails() {
        this.grid.innerHTML = '';

        if (this.mediaItems.length === 0) {
            this.actionsBar.style.display = 'none';
            return;
        }

        this.actionsBar.style.display = 'flex';

        this.mediaItems.forEach((item, index) => {
            const thumb = document.createElement('div');
            const isUnassigned = !item.linked_subject_ids || item.linked_subject_ids.length === 0;
            thumb.className = 'media-thumbnail' + (isUnassigned ? ' unassigned' : '');
            thumb.style.cssText = 'position: relative;';
            thumb.dataset.mediaId = item.id;
            thumb.dataset.index = index;
            thumb.dataset.testid = `entry-form-media-thumbnail-${item.id}`;

            // Build dimension selector HTML if multi-dimensional
            const dimensionSelectorHtml = this.isMultiDimensional && this.dimensions.length > 0
                ? `<div class="thumbnail-dimension" style="margin-top: 4px;">
                       <select class="dimension-select" data-media-id="${item.id}"
                               style="width: 100%; padding: 2px 4px; font-size: 0.7rem; border: 1px solid var(--border-color); border-radius: 4px; background: var(--bg-primary); color: var(--text-primary);">
                           <option value="">No dimension</option>
                           ${this.dimensions.map(d =>
                               `<option value="${d.id}" ${item.dimension_id === d.id ? 'selected' : ''}>${d.name}</option>`
                           ).join('')}
                       </select>
                   </div>`
                : '';

            // Build subject chips HTML
            const subjectChipsHtml = this.buildSubjectChipsHtml(item);

            const thumbnailHtml = `
                <div class="thumbnail-image-container">
                    <img src="${item.thumbnail_url}" alt="${item.user_filename || item.original_filename}"
                         style="max-width: 100%; max-height: 100%; object-fit: contain;"
                         loading="lazy" draggable="false">
                </div>
                <div class="thumbnail-info">
                    <span class="thumbnail-name" title="${item.user_filename || item.original_filename}">
                        ${this.truncateFilename(item.user_filename || item.original_filename)}
                    </span>
                    ${subjectChipsHtml}
                    ${dimensionSelectorHtml}
                </div>
                <div class="thumbnail-actions">
                    <button type="button" class="thumb-action-btn thumb-subjects" title="Edit Subjects"
                            aria-label="Edit Subjects"
                            data-testid="entry-form-media-thumbnail-${item.id}-subjects-button">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M4 7h16M4 12h16M4 17h10"/>
                        </svg>
                    </button>
                    <button type="button" class="thumb-action-btn thumb-view" title="View full size"
                            aria-label="View full size"
                            data-testid="entry-form-media-thumbnail-${item.id}-fullscreen-button">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="3"/>
                            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/>
                        </svg>
                    </button>
                    <button type="button" class="thumb-action-btn thumb-rename" title="Rename"
                            aria-label="Rename"
                            data-testid="entry-form-media-thumbnail-${item.id}-rename-button">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
                        </svg>
                    </button>
                    <button type="button" class="thumb-action-btn thumb-delete" title="Delete"
                            aria-label="Delete"
                            data-testid="entry-form-media-thumbnail-${item.id}-delete-button">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                    </button>
                </div>
            `;
            thumb.innerHTML = thumbnailHtml;

            // Click on image to view full size
            thumb.querySelector('.thumbnail-image-container').addEventListener('click', () => {
                this.showFullModal(item);
            });

            // Action buttons
            thumb.querySelector('.thumb-view').addEventListener('click', (e) => {
                e.stopPropagation();
                this.showFullModal(item);
            });

            thumb.querySelector('.thumb-rename').addEventListener('click', (e) => {
                e.stopPropagation();
                this.showRenameModal(item);
            });

            thumb.querySelector('.thumb-delete').addEventListener('click', (e) => {
                e.stopPropagation();
                this.showDeleteModal(item);
            });

            // Edit subjects button
            thumb.querySelector('.thumb-subjects').addEventListener('click', (e) => {
                e.stopPropagation();
                this.showSubjectAssignmentModal(item);
            });

            // Dimension selector change handler
            const dimensionSelect = thumb.querySelector('.dimension-select');
            if (dimensionSelect) {
                dimensionSelect.addEventListener('change', (e) => {
                    e.stopPropagation();
                    const mediaId = parseInt(e.target.dataset.mediaId);
                    const dimensionId = e.target.value ? parseInt(e.target.value) : 0;
                    this.updateMediaDimension(mediaId, dimensionId);
                });
            }

            this.grid.appendChild(thumb);
        });
    }

    /**
     * Build subject chips HTML for a media item
     */
    buildSubjectChipsHtml(mediaItem) {
        const linkedIds = mediaItem.linked_subject_ids || [];
        if (linkedIds.length === 0) {
            return '<div class="thumbnail-subjects" style="margin-top: 4px;"><span style="font-size: 0.65rem; color: var(--color-error);">No subjects assigned</span></div>';
        }

        // Look up subject names from entrySubjects
        const chips = linkedIds.map(id => {
            const subject = this.entrySubjects.find(s => s.id === id);
            const name = subject ? subject.name : `Subject #${id}`;
            return `<span class="thumbnail-subject-chip" title="${name}">${this.truncateFilename(name, 12)}</span>`;
        });

        return `<div class="thumbnail-subjects">${chips.join('')}</div>`;
    }

    /**
     * Update dimension assignment for a media item
     */
    async updateMediaDimension(mediaId, dimensionId) {
        try {
            const result = await this.callApi('updateMediaDimension', mediaId, dimensionId);
            if (result.success) {
                // Update local media item
                const item = this.mediaItems.find(m => m.id === mediaId);
                if (item) {
                    item.dimension_id = dimensionId || null;
                }
            } else {
                this.onError(result.error || 'Failed to update dimension');
            }
        } catch (error) {
            this.onError('Failed to update dimension: ' + error.message);
        }
    }
    
    /**
     * Truncate filename for display
     */
    truncateFilename(filename, maxLength = 15) {
        if (!filename) return 'Untitled';
        if (filename.length <= maxLength) return filename;
        
        const ext = filename.includes('.') ? filename.slice(filename.lastIndexOf('.')) : '';
        const name = filename.slice(0, filename.length - ext.length);
        const truncatedName = name.slice(0, maxLength - ext.length - 3) + '...';
        
        return truncatedName + ext;
    }
    
    /**
     * Show full-size image modal
     */
    showFullModal(item) {
        this.fullModalImage.src = item.full_url;
        this.fullModalCaption.textContent = item.user_filename || item.original_filename;
        this.fullModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
    
    /**
     * Close full-size modal
     */
    closeFullModal() {
        this.fullModal.style.display = 'none';
        this.fullModalImage.src = '';
        document.body.style.overflow = '';
    }
    
    /**
     * Show rename modal
     */
    showRenameModal(item) {
        this.currentRenameItem = item;
        
        // Get name without extension
        const filename = item.user_filename || item.original_filename || '';
        const ext = filename.includes('.') ? filename.slice(filename.lastIndexOf('.')) : '';
        const name = filename.slice(0, filename.length - ext.length);
        
        this.renameInput.value = name;
        this.renameModal.style.display = 'flex';
        
        setTimeout(() => {
            this.renameInput.focus();
            this.renameInput.select();
        }, 50);
    }
    
    /**
     * Close rename modal
     */
    closeRenameModal() {
        this.renameModal.style.display = 'none';
        this.currentRenameItem = null;
        this.renameInput.value = '';
    }
    
    /**
     * Save renamed file
     */
    async saveRename() {
        if (!this.currentRenameItem) return;
        
        const newName = this.renameInput.value.trim();
        if (!newName) {
            this.onError('Please enter a name');
            return;
        }
        
        // Preserve original extension
        const originalFilename = this.currentRenameItem.original_filename || '';
        const ext = originalFilename.includes('.') ? originalFilename.slice(originalFilename.lastIndexOf('.')) : '';
        const fullNewName = newName + ext;
        
        try {
            const result = await this.callApi('renameMedia', this.currentRenameItem.id, fullNewName);
            
            if (result.success) {
                // Update local data
                const item = this.mediaItems.find(m => m.id === this.currentRenameItem.id);
                if (item) {
                    item.user_filename = result.data.user_filename;
                }
                this.renderThumbnails();
                this.closeRenameModal();
            } else {
                this.onError(result.error || 'Failed to rename');
            }
        } catch (error) {
            this.onError('Failed to rename: ' + error.message);
        }
    }
    
    /**
     * Show delete confirmation modal
     */
    showDeleteModal(item) {
        this.currentDeleteItem = item;

        // Show the filename in the modal
        const filenameEl = this.container.querySelector('#media-delete-filename');
        if (filenameEl) {
            filenameEl.textContent = item.user_filename || item.original_filename || 'Untitled';
        }

        this.deleteModal.style.display = 'flex';
    }
    
    /**
     * Close delete modal
     */
    closeDeleteModal() {
        this.deleteModal.style.display = 'none';
        this.currentDeleteItem = null;
    }
    
    /**
     * Remove image from entry only (keeps file in database for reuse)
     */
    async confirmRemoveFromEntry() {
        if (!this.currentDeleteItem) return;

        try {
            const result = await this.callApi('removeMediaFromEntry', this.currentDeleteItem.id);

            if (result.success) {
                // Remove from local array
                const removedItem = this.currentDeleteItem;
                this.mediaItems = this.mediaItems.filter(m => m.id !== this.currentDeleteItem.id);
                this.renderThumbnails();
                this.onDelete(removedItem);
                this.closeDeleteModal();
            } else {
                this.onError(result.error || 'Failed to remove from entry');
            }
        } catch (error) {
            this.onError('Failed to remove: ' + error.message);
        }
    }

    /**
     * Permanently delete image (removes from database and disk)
     */
    async confirmDeletePermanent() {
        if (!this.currentDeleteItem) return;

        try {
            const result = await this.callApi('deleteMedia', this.entryId, this.currentDeleteItem.id);

            if (result.success) {
                // Remove from local array
                const deletedItem = this.currentDeleteItem;
                this.mediaItems = this.mediaItems.filter(m => m.id !== this.currentDeleteItem.id);
                this.renderThumbnails();
                this.onDelete(deletedItem);
                this.closeDeleteModal();
            } else {
                this.onError(result.error || 'Failed to delete');
            }
        } catch (error) {
            this.onError('Failed to delete: ' + error.message);
        }
    }

    /**
     * Set the entry's assigned subjects (called from question_entry.js when subjects change)
     * @param {Array} subjects - Array of subject objects with id, name, path, dimension_id
     */
    setEntrySubjects(subjects) {
        this.entrySubjects = subjects || [];
    }

    /**
     * Show subject assignment modal for a media item
     * @param {Object} mediaItem - The media item to assign subjects to
     * @param {Function} onSave - Callback when assignment is saved
     */
    showSubjectAssignmentModal(mediaItem, onSave = null) {
        if (!mediaItem) return;

        this.currentSubjectAssignmentMedia = mediaItem;
        this.subjectAssignmentCallback = onSave;

        // Show image preview
        this.subjectPreview.innerHTML = `
            <img src="${mediaItem.thumbnail_url}" alt="${mediaItem.user_filename || mediaItem.original_filename}"
                 style="max-width: 150px; max-height: 100px; object-fit: contain; border-radius: 4px;">
            <span style="margin-top: 4px; font-size: 0.75rem; color: var(--text-muted);">
                ${mediaItem.user_filename || mediaItem.original_filename}
            </span>
        `;

        // Group subjects by dimension
        const subjectsByDimension = this.groupSubjectsByDimension(this.entrySubjects);
        const currentLinkedIds = mediaItem.linked_subject_ids || [];

        // Build checkbox list
        let listHtml = '';

        if (Object.keys(subjectsByDimension).length === 0) {
            listHtml = `
                <div class="media-subject-empty">
                    <p>No subjects assigned to this entry yet.</p>
                    <p>Please assign subjects to the entry first, then return to assign them to images.</p>
                </div>
            `;
            this.subjectSaveBtn.disabled = true;
        } else {
            for (const [dimensionName, subjects] of Object.entries(subjectsByDimension)) {
                listHtml += `<div class="media-subject-dimension">
                    <div class="media-subject-dimension-header">${dimensionName}</div>
                    <div class="media-subject-checkboxes">`;

                for (const subject of subjects) {
                    const isChecked = currentLinkedIds.includes(subject.id);
                    listHtml += `
                        <label class="media-subject-checkbox">
                            <input type="checkbox" value="${subject.id}" ${isChecked ? 'checked' : ''}>
                            <span class="media-subject-name">${subject.name}</span>
                        </label>
                    `;
                }

                listHtml += `</div></div>`;
            }
        }

        this.subjectList.innerHTML = listHtml;

        // Add change listeners to checkboxes
        this.subjectList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', () => this.updateSubjectSaveButton());
        });

        // --- Additional subjects section ---
        // Identify subjects in linked_subject_ids that are NOT entry subjects
        const entrySubjectIds = this.entrySubjects.map(s => s.id);
        const additionalLinkedIds = currentLinkedIds.filter(id => !entrySubjectIds.includes(id));

        // Build additional subjects from EntryState.subjects (full hierarchy)
        const additionalSubjects = [];
        if (additionalLinkedIds.length > 0 && typeof EntryState !== 'undefined') {
            for (const id of additionalLinkedIds) {
                const found = EntryState.subjects.find(s => s.id === id);
                additionalSubjects.push(found || { id, name: `Unknown Subject (ID: ${id})` });
            }
        }

        // Remove previously inserted search elements (divider, label, widget container)
        if (this._searchDivider) this._searchDivider.remove();
        if (this._searchLabel) this._searchLabel.remove();
        if (this._searchWidgetContainer) this._searchWidgetContainer.remove();

        // Add divider + search widget container
        this._searchDivider = document.createElement('div');
        this._searchDivider.style.cssText = 'border-top: 1px solid var(--border-color, #e5e7eb); margin: 16px 0 12px 0;';

        this._searchLabel = document.createElement('div');
        this._searchLabel.className = 'media-subject-hint';
        this._searchLabel.textContent = 'Search for additional subjects:';

        this._searchWidgetContainer = document.createElement('div');
        this._searchWidgetContainer.className = 'media-subject-search-widget';

        this.subjectList.parentNode.insertBefore(this._searchDivider, this.subjectList.nextSibling);
        this._searchDivider.after(this._searchLabel);
        this._searchLabel.after(this._searchWidgetContainer);

        // Destroy previous widget if any
        if (this._subjectSearchWidget) {
            this._subjectSearchWidget.destroy();
        }

        // Create widget - exclude entry subjects (already shown as checkboxes)
        const excludeIds = [...entrySubjectIds];
        this._subjectSearchWidget = new SubjectSearchSelect(this._searchWidgetContainer, {
            fuzzySearch: window.fuzzySearch,
            excludeIds: excludeIds,
            placeholder: 'Search for additional subjects...',
            onSubjectAdded: () => this.updateSubjectSaveButton(),
            onSubjectRemoved: () => this.updateSubjectSaveButton()
        });

        // Set pre-existing additional subjects
        if (additionalSubjects.length > 0) {
            this._subjectSearchWidget.setSelectedSubjects(additionalSubjects);
        }

        // Update save button state
        this.updateSubjectSaveButton();

        // Show modal
        this.subjectModal.style.display = 'flex';
    }

    /**
     * Group subjects by their dimension name
     */
    groupSubjectsByDimension(subjects) {
        const grouped = {};

        for (const subject of subjects) {
            // Find dimension name
            let dimensionName = 'General';
            if (subject.dimension_id && this.dimensions.length > 0) {
                const dim = this.dimensions.find(d => d.id === subject.dimension_id);
                if (dim) dimensionName = dim.name;
            }

            if (!grouped[dimensionName]) {
                grouped[dimensionName] = [];
            }
            grouped[dimensionName].push(subject);
        }

        return grouped;
    }

    /**
     * Update save button enabled state based on checkbox selection
     */
    updateSubjectSaveButton() {
        const checkedCount = this.subjectList.querySelectorAll('input[type="checkbox"]:checked').length;
        const searchCount = this._subjectSearchWidget ? this._subjectSearchWidget.getSelectedSubjects().length : 0;
        this.subjectSaveBtn.disabled = (checkedCount + searchCount) === 0;
    }

    /**
     * Get selected subject IDs from modal
     */
    getSelectedSubjectIds() {
        const checked = this.subjectList.querySelectorAll('input[type="checkbox"]:checked');
        const checkboxIds = Array.from(checked).map(cb => parseInt(cb.value));

        // Also include subjects from search widget
        const searchIds = this._subjectSearchWidget ? this._subjectSearchWidget.getSelectedIds() : [];

        return [...new Set([...checkboxIds, ...searchIds])];
    }

    /**
     * Save subject assignment
     */
    async saveSubjectAssignment() {
        if (!this.currentSubjectAssignmentMedia) return;

        const selectedIds = this.getSelectedSubjectIds();

        if (selectedIds.length === 0) {
            this.onError('Please select at least one subject');
            return;
        }

        try {
            // Note: api.updateMediaLinkedSubjects handles JSON.stringify internally
            const result = await this.callApi('updateMediaLinkedSubjects',
                this.currentSubjectAssignmentMedia.id,
                selectedIds
            );

            if (result.success) {
                // Update local media item
                const item = this.mediaItems.find(m => m.id === this.currentSubjectAssignmentMedia.id);
                if (item) {
                    item.linked_subject_ids = selectedIds;
                }

                // Re-render thumbnails
                this.renderThumbnails();

                // Call callback if provided
                if (this.subjectAssignmentCallback) {
                    this.subjectAssignmentCallback(this.currentSubjectAssignmentMedia, selectedIds);
                }

                // Notify parent that subject assignment changed
                if (this.onSubjectAssigned) {
                    this.onSubjectAssigned(this.currentSubjectAssignmentMedia, selectedIds);
                }

                // Close modal
                this.closeSubjectAssignmentModal();
            } else {
                this.onError(result.error || 'Failed to save subject assignment');
            }
        } catch (error) {
            this.onError('Failed to save: ' + error.message);
        }
    }

    /**
     * Close subject assignment modal
     */
    closeSubjectAssignmentModal() {
        this.subjectModal.style.display = 'none';
        this.currentSubjectAssignmentMedia = null;
        this.subjectAssignmentCallback = null;
        if (this._subjectSearchWidget) {
            this._subjectSearchWidget.destroy();
            this._subjectSearchWidget = null;
        }
    }

    /**
     * Check if any media items are missing subject assignments
     */
    hasUnassignedMedia() {
        return this.mediaItems.some(m => !m.linked_subject_ids || m.linked_subject_ids.length === 0);
    }

    /**
     * Get list of unassigned media items
     */
    getUnassignedMedia() {
        return this.mediaItems.filter(m => !m.linked_subject_ids || m.linked_subject_ids.length === 0);
    }

    /**
     * Sort media by filename
     */
    async sortByName() {
        if (this.mediaItems.length < 2) return;
        
        // Sort locally
        this.mediaItems.sort((a, b) => {
            const nameA = (a.user_filename || a.original_filename || '').toLowerCase();
            const nameB = (b.user_filename || b.original_filename || '').toLowerCase();
            return nameA.localeCompare(nameB);
        });
        
        // Update order in database
        const orderedIds = this.mediaItems.map(m => m.id);
        
        try {
            // Note: api.reorderMedia already handles JSON.stringify
            await this.callApi('reorderMedia', this.entryId, orderedIds);
            this.renderThumbnails();
        } catch (error) {
            this.onError('Failed to save order: ' + error.message);
        }
    }
    
    /**
     * Get current media items
     */
    getMediaItems() {
        return this.mediaItems;
    }
    
    /**
     * Clear all media (for new entry)
     */
    clear() {
        this.entryId = null;
        this.mediaItems = [];
        this.renderThumbnails();
    }
    
    /**
     * Destroy the component
     */
    destroy() {
        document.removeEventListener('paste', this.pasteHandler);
        this.container.innerHTML = '';
    }
}

// Export for use in question_entry.js
window.MediaUpload = MediaUpload;
