/**
 * Image Browser Component for WIMI
 * Searchable image browser for selecting existing images
 */

class ImageBrowser {
    /**
     * Create an ImageBrowser component
     * @param {Object} options - Configuration options
     * @param {Function} options.onSelect - Callback when image is selected
     * @param {Function} options.onClose - Callback when browser is closed
     */
    constructor(options = {}) {
        this.onSelect = options.onSelect || (() => {});
        this.onClose = options.onClose || (() => {});

        this.isOpen = false;
        this.searchQuery = '';
        this.searchTimeout = null;
        this.mediaItems = [];

        this.modal = null;
        this.searchInput = null;
        this.grid = null;
        this.loadingIndicator = null;
    }

    /**
     * Open the image browser modal
     * @param {number} [subjectId] - Optional subject ID to filter by
     */
    async open(subjectId = null) {
        if (this.isOpen) return;

        this.isOpen = true;
        this.render();
        this.setupEventListeners();

        // Load initial images
        if (subjectId) {
            await this.loadBySubject(subjectId);
        } else {
            await this.loadImages();
        }
    }

    /**
     * Close the image browser modal
     */
    close() {
        if (!this.isOpen) return;

        this.isOpen = false;
        if (this.modal) {
            this.modal.remove();
            this.modal = null;
        }
        document.body.style.overflow = '';
        this.onClose();
    }

    /**
     * Render the modal HTML
     */
    render() {
        this.modal = document.createElement('div');
        this.modal.className = 'image-browser-modal';
        this.modal.dataset.testid = 'entry-form-image-browser-modal';
        this.modal.innerHTML = `
            <div class="image-browser-backdrop"></div>
            <div class="image-browser-container">
                <div class="image-browser-header">
                    <h3>Select Image</h3>
                    <button type="button" class="image-browser-close" aria-label="Close" data-testid="entry-form-image-browser-close-button">&times;</button>
                </div>
                <div class="image-browser-search">
                    <input type="text"
                           class="image-browser-search-input"
                           placeholder="Search images by name..."
                           autocomplete="off"
                           data-testid="entry-form-image-browser-search-input">
                    <span class="image-browser-search-icon">🔍</span>
                </div>
                <div class="image-browser-loading" style="display: none;">
                    <span class="spinner"></span>
                    <span>Loading images...</span>
                </div>
                <div class="image-browser-grid" data-testid="entry-form-image-browser-grid"></div>
                <div class="image-browser-empty" style="display: none;">
                    <span class="empty-icon">📷</span>
                    <span class="empty-text">No images found</span>
                </div>
                <div class="image-browser-footer">
                    <span class="image-browser-count">0 images</span>
                    <button type="button" class="btn btn-secondary btn-sm image-browser-cancel" data-testid="entry-form-image-browser-cancel-button">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(this.modal);
        document.body.style.overflow = 'hidden';

        // Cache DOM elements
        this.searchInput = this.modal.querySelector('.image-browser-search-input');
        this.grid = this.modal.querySelector('.image-browser-grid');
        this.loadingIndicator = this.modal.querySelector('.image-browser-loading');
        this.emptyState = this.modal.querySelector('.image-browser-empty');
        this.countLabel = this.modal.querySelector('.image-browser-count');

        // Focus search input
        setTimeout(() => this.searchInput?.focus(), 100);
    }

    /**
     * Set up event listeners
     */
    setupEventListeners() {
        // Close button
        this.modal.querySelector('.image-browser-close')?.addEventListener('click', () => this.close());
        this.modal.querySelector('.image-browser-cancel')?.addEventListener('click', () => this.close());

        // Backdrop click
        this.modal.querySelector('.image-browser-backdrop')?.addEventListener('click', () => this.close());

        // Escape key
        this.escapeHandler = (e) => {
            if (e.key === 'Escape') this.close();
        };
        document.addEventListener('keydown', this.escapeHandler);

        // Search input
        this.searchInput?.addEventListener('input', (e) => {
            this.searchQuery = e.target.value;
            this.debouncedSearch();
        });
    }

    /**
     * Debounced search
     */
    debouncedSearch() {
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        this.searchTimeout = setTimeout(() => {
            this.loadImages();
        }, 300);
    }

    /**
     * Load images from API
     */
    async loadImages() {
        this.setLoading(true);

        try {
            this.mediaItems = await window.api.searchMedia(
                this.searchQuery,
                50
            );
            this.renderGrid();
        } catch (error) {
            console.error('Failed to load images:', error);
            this.mediaItems = [];
            this.renderGrid();
        }

        this.setLoading(false);
    }

    /**
     * Load images by subject
     */
    async loadBySubject(subjectId) {
        this.setLoading(true);

        try {
            this.mediaItems = await window.api.getMediaBySubject(
                subjectId,
                20
            );
            this.renderGrid();
        } catch (error) {
            console.error('Failed to load images by subject:', error);
            this.mediaItems = [];
            this.renderGrid();
        }

        this.setLoading(false);
    }

    /**
     * Set loading state
     */
    setLoading(isLoading) {
        if (this.loadingIndicator) {
            this.loadingIndicator.style.display = isLoading ? 'flex' : 'none';
        }
        if (this.grid) {
            this.grid.style.display = isLoading ? 'none' : 'grid';
        }
    }

    /**
     * Render the image grid
     */
    renderGrid() {
        if (!this.grid) return;

        this.grid.innerHTML = '';

        // Update count
        if (this.countLabel) {
            this.countLabel.textContent = `${this.mediaItems.length} image${this.mediaItems.length !== 1 ? 's' : ''}`;
        }

        // Show empty state if no images
        if (this.mediaItems.length === 0) {
            this.emptyState.style.display = 'flex';
            this.grid.style.display = 'none';
            return;
        }

        this.emptyState.style.display = 'none';
        this.grid.style.display = 'grid';

        this.mediaItems.forEach((item) => {
            const card = document.createElement('div');
            card.className = 'image-browser-card';
            card.dataset.mediaId = item.id;
            card.dataset.testid = `entry-form-image-browser-card-${item.id}`;

            const displayName = item.user_filename || item.original_filename || 'Untitled';
            const truncatedName = displayName.length > 20
                ? displayName.substring(0, 17) + '...'
                : displayName;

            const examLabel = item.exam_names && item.exam_names.length > 0
                ? item.exam_names.join(', ')
                : '';

            card.innerHTML = `
                <div class="image-browser-thumb">
                    <img src="${item.thumbnail_url}" alt="${displayName}" loading="lazy">
                </div>
                <div class="image-browser-name" title="${displayName}">${truncatedName}</div>
                ${examLabel ? `<div class="image-browser-exam" title="${examLabel}">${examLabel}</div>` : ''}
            `;

            card.addEventListener('click', () => {
                this.selectImage(item);
            });

            this.grid.appendChild(card);
        });
    }

    /**
     * Handle image selection
     */
    selectImage(mediaItem) {
        this.onSelect(mediaItem);
        this.close();
    }

    /**
     * Destroy the component and clean up
     */
    destroy() {
        if (this.escapeHandler) {
            document.removeEventListener('keydown', this.escapeHandler);
        }
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }
        this.close();
    }
}

// Export for use in other modules
window.ImageBrowser = ImageBrowser;
