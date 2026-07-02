/**
 * WIMI Toast Notification Utility
 * Provides non-intrusive toast notifications for user feedback.
 */

class Toast {
    static container = null;
    static defaultDuration = 2500;

    /**
     * Initialize the toast container if it doesn't exist.
     */
    static init() {
        if (Toast.container) return;
        Toast.container = document.createElement('div');
        Toast.container.className = 'toast-container';
        document.body.appendChild(Toast.container);
    }

    /**
     * Show a toast notification.
     * @param {string} message - The message to display.
     * @param {Object} options - Optional configuration.
     * @param {number} options.duration - Duration in ms (default: 2500).
     * @param {string} options.type - Type of toast: 'info', 'success', 'warning', 'error' (default: 'info').
     */
    static show(message, options = {}) {
        Toast.init();

        const {
            duration = Toast.defaultDuration,
            type = 'info'
        } = options;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        // Add icon based on type
        const icons = {
            info: 'i',
            success: '✓',
            warning: '!',
            error: '✗'
        };

        const iconSpan = document.createElement('span');
        iconSpan.className = 'toast-icon';
        iconSpan.textContent = icons[type] || icons.info;

        const messageSpan = document.createElement('span');
        messageSpan.className = 'toast-message';
        messageSpan.textContent = message;

        toast.appendChild(iconSpan);
        toast.appendChild(messageSpan);

        Toast.container.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('toast-visible');
        });

        // Remove after duration
        setTimeout(() => {
            toast.classList.remove('toast-visible');
            toast.classList.add('toast-hiding');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    /**
     * Show an info toast.
     * @param {string} message - The message to display.
     * @param {number} duration - Duration in ms.
     */
    static info(message, duration) {
        Toast.show(message, { type: 'info', duration });
    }

    /**
     * Show a success toast.
     * @param {string} message - The message to display.
     * @param {number} duration - Duration in ms.
     */
    static success(message, duration) {
        Toast.show(message, { type: 'success', duration });
    }

    /**
     * Show a warning toast.
     * @param {string} message - The message to display.
     * @param {number} duration - Duration in ms.
     */
    static warning(message, duration) {
        Toast.show(message, { type: 'warning', duration });
    }

    /**
     * Show an error toast.
     * @param {string} message - The message to display.
     * @param {number} duration - Duration in ms.
     */
    static error(message, duration) {
        Toast.show(message, { type: 'error', duration });
    }
}

// Make Toast globally available
window.Toast = Toast;
