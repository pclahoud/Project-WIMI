/**
 * Error Logger for PyQt6 WebEngine Student App
 * Captures and manages JavaScript errors with Python bridge integration
 */

class ErrorLogger {
    constructor(options = {}) {
        this.options = {
            maxErrors: options.maxErrors || 1000,
            enableConsoleCapture: options.enableConsoleCapture !== false,
            enableWindowErrorCapture: options.enableWindowErrorCapture !== false,
            enableUnhandledRejectionCapture: options.enableUnhandledRejectionCapture !== false,
            enableStackTrace: options.enableStackTrace !== false,
            enableBreadcrumbs: options.enableBreadcrumbs !== false,
            maxBreadcrumbs: options.maxBreadcrumbs || 50,
            pythonBridge: options.pythonBridge || null,
            dedupWindow: options.dedupWindow || 5000, // 5 seconds
            sanitizeFields: options.sanitizeFields || ['password', 'token', 'key', 'secret', 'ssn', 'creditCard'],
            ...options
        };
        
        this.errors = [];
        this.breadcrumbs = [];
        this.errorHashes = new Map();
        this.sessionId = this.generateSessionId();
        this.userId = null;
        this.username = null;
        
        this.stats = {
            total: 0,
            byLevel: {},
            byCategory: {},
            recovered: 0
        };
        
        this.initialize();
    }
    
    initialize() {
        // Capture global errors
        if (this.options.enableWindowErrorCapture) {
            this.captureWindowErrors();
        }
        
        // Capture unhandled promise rejections
        if (this.options.enableUnhandledRejectionCapture) {
            this.captureUnhandledRejections();
        }
        
        // Capture console methods
        if (this.options.enableConsoleCapture) {
            this.captureConsole();
        }
        
        // Capture breadcrumbs
        if (this.options.enableBreadcrumbs) {
            this.captureBreadcrumbs();
        }
        
        // Setup Python bridge if available
        this.setupPythonBridge();
    }
    
    generateSessionId() {
        return `js_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }
    
    captureWindowErrors() {
        const originalError = window.onerror;
        window.onerror = (message, source, lineno, colno, error) => {
            this.log({
                level: 'ERROR',
                message: message,
                category: 'javascript',
                stack: error ? error.stack : `at ${source}:${lineno}:${colno}`,
                context: {
                    source: source,
                    lineno: lineno,
                    colno: colno,
                    userAgent: navigator.userAgent,
                    url: window.location.href
                }
            });
            
            if (originalError) {
                return originalError(message, source, lineno, colno, error);
            }
            return true;
        };
    }
    
    captureUnhandledRejections() {
        window.addEventListener('unhandledrejection', (event) => {
            this.log({
                level: 'ERROR',
                message: `Unhandled Promise Rejection: ${event.reason}`,
                category: 'promise',
                stack: event.reason && event.reason.stack,
                context: {
                    promise: event.promise,
                    reason: event.reason,
                    url: window.location.href
                }
            });
        });
    }
    
    captureConsole() {
        const methods = ['error', 'warn'];
        methods.forEach(method => {
            const original = console[method];
            console[method] = (...args) => {
                const level = method === 'error' ? 'ERROR' : 'WARNING';
                this.log({
                    level: level,
                    message: args.map(arg => 
                        typeof arg === 'object' ? JSON.stringify(arg) : String(arg)
                    ).join(' '),
                    category: 'console',
                    context: {
                        method: method,
                        url: window.location.href
                    }
                });
                original.apply(console, args);
            };
        });
    }
    
    captureBreadcrumbs() {
        // Capture clicks
        document.addEventListener('click', (event) => {
            const target = event.target;
            const breadcrumb = {
                type: 'click',
                timestamp: Date.now(),
                target: {
                    tagName: target.tagName,
                    id: target.id,
                    className: target.className,
                    text: target.textContent?.substring(0, 50)
                }
            };
            this.addBreadcrumb(breadcrumb);
        }, true);
        
        // Capture navigation
        const originalPushState = history.pushState;
        history.pushState = (...args) => {
            this.addBreadcrumb({
                type: 'navigation',
                timestamp: Date.now(),
                from: window.location.href,
                to: args[2]
            });
            return originalPushState.apply(history, args);
        };
        
        // Capture AJAX requests
        const originalFetch = window.fetch;
        window.fetch = (...args) => {
            const breadcrumb = {
                type: 'fetch',
                timestamp: Date.now(),
                url: args[0],
                method: args[1]?.method || 'GET'
            };
            this.addBreadcrumb(breadcrumb);
            
            return originalFetch.apply(window, args).catch(error => {
                this.log({
                    level: 'ERROR',
                    message: `Fetch failed: ${error.message}`,
                    category: 'network',
                    context: {
                        url: args[0],
                        error: error.message
                    }
                });
                throw error;
            });
        };
        
        // Capture XMLHttpRequest
        const originalOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._errorLogger = {
                method: method,
                url: url
            };
            return originalOpen.apply(this, arguments);
        };
        
        const originalSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function() {
            const xhr = this;
            if (xhr._errorLogger) {
                const breadcrumb = {
                    type: 'xhr',
                    timestamp: Date.now(),
                    url: xhr._errorLogger.url,
                    method: xhr._errorLogger.method
                };
                window.errorLogger.addBreadcrumb(breadcrumb);
                
                xhr.addEventListener('error', () => {
                    window.errorLogger.log({
                        level: 'ERROR',
                        message: `XHR failed: ${xhr._errorLogger.url}`,
                        category: 'network',
                        context: {
                            url: xhr._errorLogger.url,
                            method: xhr._errorLogger.method,
                            status: xhr.status,
                            statusText: xhr.statusText
                        }
                    });
                });
            }
            return originalSend.apply(this, arguments);
        };
    }
    
    addBreadcrumb(breadcrumb) {
        this.breadcrumbs.push(breadcrumb);
        if (this.breadcrumbs.length > this.options.maxBreadcrumbs) {
            this.breadcrumbs.shift();
        }
    }
    
    setupPythonBridge() {
        // Check if PyQt bridge is available
        if (window.pyqt_bridge || window.qt) {
            this.pythonBridge = window.pyqt_bridge || window.qt.webChannelTransport;
        } else if (this.options.pythonBridge) {
            this.pythonBridge = this.options.pythonBridge;
        }
    }
    
    log(error) {
        // Generate error ID
        const errorId = this.generateErrorId(error.message);
        
        // Check for deduplication
        const hash = this.hashError(error.message, error.category);
        if (this.shouldDeduplicate(hash)) {
            return errorId;
        }
        
        // Create error entry
        const entry = {
            id: errorId,
            timestamp: Date.now(),
            level: error.level || 'ERROR',
            category: error.category || 'custom',
            message: this.sanitizeMessage(error.message),
            stack: error.stack || this.getStackTrace(),
            context: {
                ...error.context,
                sessionId: this.sessionId,
                userId: this.userId,
                username: this.username,
                environment: 'javascript',
                breadcrumbs: this.breadcrumbs.slice(-10),
                url: window.location.href,
                userAgent: navigator.userAgent
            },
            count: 1
        };
        
        // Add to local storage
        this.errors.push(entry);
        if (this.errors.length > this.options.maxErrors) {
            this.errors.shift();
        }
        
        // Update stats
        this.updateStats(entry);
        
        // Send to Python if bridge available
        if (this.pythonBridge) {
            this.sendToPython(entry);
        }
        
        // Emit event for UI updates
        this.emit('error', entry);
        
        return errorId;
    }
    
    generateErrorId(message) {
        const hash = this.hashString(`${message}${Date.now()}${Math.random()}`);
        return hash.substring(0, 16);
    }
    
    hashError(message, category) {
        return this.hashString(`${category}:${message}`);
    }
    
    hashString(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        return Math.abs(hash).toString(36);
    }
    
    shouldDeduplicate(hash) {
        const now = Date.now();
        if (this.errorHashes.has(hash)) {
            const lastSeen = this.errorHashes.get(hash);
            if (now - lastSeen < this.options.dedupWindow) {
                return true;
            }
        }
        this.errorHashes.set(hash, now);
        
        // Clean old hashes
        for (const [h, time] of this.errorHashes.entries()) {
            if (now - time > this.options.dedupWindow * 2) {
                this.errorHashes.delete(h);
            }
        }
        
        return false;
    }
    
    sanitizeMessage(message) {
        let sanitized = String(message);
        this.options.sanitizeFields.forEach(field => {
            const regex = new RegExp(`(${field})[\\s:=]+"?([^"\\s]+)"?`, 'gi');
            sanitized = sanitized.replace(regex, '$1=[REDACTED]');
        });
        return sanitized;
    }
    
    getStackTrace() {
        if (!this.options.enableStackTrace) return null;
        
        const stack = new Error().stack;
        if (!stack) return null;
        
        // Remove error logger frames from stack
        const lines = stack.split('\n');
        const filtered = lines.filter(line => 
            !line.includes('ErrorLogger') && 
            !line.includes('at log') &&
            !line.includes('at captureWindowErrors')
        );
        
        return filtered.join('\n');
    }
    
    updateStats(entry) {
        this.stats.total++;
        this.stats.byLevel[entry.level] = (this.stats.byLevel[entry.level] || 0) + 1;
        this.stats.byCategory[entry.category] = (this.stats.byCategory[entry.category] || 0) + 1;
    }
    
    sendToPython(entry) {
        try {
            const data = JSON.stringify(entry);
            if (this.pythonBridge && this.pythonBridge.log_js_error) {
                this.pythonBridge.log_js_error(data);
            } else if (this.pythonBridge && this.pythonBridge.postMessage) {
                this.pythonBridge.postMessage({
                    type: 'error',
                    data: data
                });
            }
        } catch (e) {
            console.error('Failed to send error to Python:', e);
        }
    }
    
    emit(event, data) {
        // Emit custom event for UI components
        window.dispatchEvent(new CustomEvent(`errorlogger:${event}`, { detail: data }));
    }
    
    // Public API
    setUser(userId, username) {
        this.userId = userId;
        this.username = username;
    }
    
    trace(message, context) {
        return this.log({ level: 'TRACE', message, context });
    }
    
    debug(message, context) {
        return this.log({ level: 'DEBUG', message, context });
    }
    
    info(message, context) {
        return this.log({ level: 'INFO', message, context });
    }
    
    warning(message, context) {
        return this.log({ level: 'WARNING', message, context });
    }
    
    error(message, context, stack) {
        return this.log({ level: 'ERROR', message, context, stack });
    }
    
    critical(message, context, stack) {
        return this.log({ level: 'CRITICAL', message, context, stack });
    }
    
    fatal(message, context, stack) {
        return this.log({ level: 'FATAL', message, context, stack });
    }
    
    getErrors(filter = {}) {
        let filtered = [...this.errors];
        
        if (filter.level) {
            filtered = filtered.filter(e => e.level === filter.level);
        }
        if (filter.category) {
            filtered = filtered.filter(e => e.category === filter.category);
        }
        if (filter.search) {
            const search = filter.search.toLowerCase();
            filtered = filtered.filter(e => 
                e.message.toLowerCase().includes(search)
            );
        }
        
        return filtered.reverse();
    }
    
    clearErrors() {
        this.errors = [];
        this.stats = {
            total: 0,
            byLevel: {},
            byCategory: {},
            recovered: 0
        };
        this.emit('clear', {});
    }
    
    exportErrors(format = 'json') {
        const errors = this.getErrors();
        
        if (format === 'json') {
            return JSON.stringify(errors, null, 2);
        } else if (format === 'csv') {
            const headers = ['timestamp', 'level', 'category', 'message'];
            const rows = errors.map(e => 
                [e.timestamp, e.level, e.category, e.message].join(',')
            );
            return [headers.join(','), ...rows].join('\n');
        }
        
        return errors;
    }
    
    getStatistics() {
        return {
            ...this.stats,
            errors: this.errors.length,
            maxErrors: this.options.maxErrors,
            sessionId: this.sessionId,
            breadcrumbs: this.breadcrumbs.length
        };
    }
}

// Initialize global error logger if not in a module environment
if (typeof module === 'undefined') {
    window.ErrorLogger = ErrorLogger;
}
