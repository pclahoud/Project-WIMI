/**
 * WIMI Theme System
 * Theme definitions, CSS variable application, and settings loader.
 * Extracted from api.js — standalone, depends only on window.api.
 */

/**
 * Lighten / darken a hex color by adjusting each RGB channel.
 * Positive amount lightens, negative darkens.
 */
function _wimiAdjustColor(hex, amount) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    r = Math.max(0, Math.min(255, r + amount));
    g = Math.max(0, Math.min(255, g + amount));
    b = Math.max(0, Math.min(255, b + amount));
    return '#' + [r, g, b].map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
}

// =========================================================================
// Theme Definitions
// =========================================================================

window.WIMI_THEMES = {
    default: {
        label: 'Default (Light)',
        primaryColorHex: '#2563eb',
        secondaryColorHex: '#64748b',
        variables: {}
    },

    midnight: {
        label: 'Midnight (Dark)',
        primaryColorHex: '#60a5fa',
        secondaryColorHex: '#94a3b8',
        variables: {
            '--color-gray-50':  '#1e293b',
            '--color-gray-100': '#1e293b',
            '--color-gray-200': '#334155',
            '--color-gray-300': '#475569',
            '--color-gray-400': '#64748b',
            '--color-gray-500': '#94a3b8',
            '--color-gray-600': '#cbd5e1',
            '--color-gray-700': '#e2e8f0',
            '--color-gray-800': '#f1f5f9',
            '--color-gray-900': '#f8fafc',
            '--color-white':    '#0f172a',
            '--text-primary':   '#f8fafc',
            '--text-secondary': '#cbd5e1',
            '--text-muted':     '#64748b',
            '--text-inverse':   '#0f172a',
            '--bg-primary':   '#0f172a',
            '--bg-secondary': '#1e293b',
            '--bg-tertiary':  '#1e293b',
            '--border-color':  '#334155',
            '--border-light':  '#334155',
            '--border-medium': '#475569',
            '--border-dark':   '#64748b',
            '--shadow-sm': '0 1px 2px 0 rgb(0 0 0 / 0.3)',
            '--shadow-md': '0 4px 6px -1px rgb(0 0 0 / 0.4), 0 2px 4px -2px rgb(0 0 0 / 0.3)',
            '--shadow-lg': '0 10px 15px -3px rgb(0 0 0 / 0.4), 0 4px 6px -4px rgb(0 0 0 / 0.3)',
            '--shadow-xl': '0 20px 25px -5px rgb(0 0 0 / 0.4), 0 8px 10px -6px rgb(0 0 0 / 0.3)',
            '--color-primary':       '#60a5fa',
            '--color-primary-hover': '#3b82f6',
            '--color-primary-light': '#93c5fd',
            '--color-primary-bg':    '#1e3a5f',
            '--color-secondary':       '#94a3b8',
            '--color-secondary-hover': '#cbd5e1',
            '--color-success':    '#34d399',
            '--color-success-bg': '#064e3b',
            '--color-warning':    '#fbbf24',
            '--color-warning-bg': '#451a03',
            '--color-error':      '#f87171',
            '--color-error-bg':   '#450a0a',
            '--color-info':       '#22d3ee',
            '--color-info-bg':    '#083344'
        }
    },

    warm_study: {
        label: 'Warm Study (Sepia)',
        primaryColorHex: '#b45309',
        secondaryColorHex: '#92400e',
        variables: {
            '--color-gray-50':  '#faf6f1',
            '--color-gray-100': '#f5ebe0',
            '--color-gray-200': '#e8dcc8',
            '--color-gray-300': '#d5c4a1',
            '--color-gray-400': '#a89070',
            '--color-gray-500': '#7c6f5e',
            '--color-gray-600': '#5c4f3d',
            '--color-gray-700': '#3d3425',
            '--color-gray-800': '#2a2318',
            '--color-gray-900': '#1a1610',
            '--color-white':    '#fefcf8',
            '--text-primary':   '#1a1610',
            '--text-secondary': '#5c4f3d',
            '--text-muted':     '#a89070',
            '--text-inverse':   '#fefcf8',
            '--bg-primary':   '#fefcf8',
            '--bg-secondary': '#faf6f1',
            '--bg-tertiary':  '#f5ebe0',
            '--border-color':  '#e8dcc8',
            '--border-light':  '#e8dcc8',
            '--border-medium': '#d5c4a1',
            '--border-dark':   '#a89070',
            '--shadow-sm': '0 1px 2px 0 rgb(120 80 20 / 0.08)',
            '--shadow-md': '0 4px 6px -1px rgb(120 80 20 / 0.1), 0 2px 4px -2px rgb(120 80 20 / 0.08)',
            '--shadow-lg': '0 10px 15px -3px rgb(120 80 20 / 0.1), 0 4px 6px -4px rgb(120 80 20 / 0.08)',
            '--shadow-xl': '0 20px 25px -5px rgb(120 80 20 / 0.1), 0 8px 10px -6px rgb(120 80 20 / 0.08)',
            '--color-primary':       '#b45309',
            '--color-primary-hover': '#92400e',
            '--color-primary-light': '#d97706',
            '--color-primary-bg':    '#fef3c7',
            '--color-secondary':       '#92400e',
            '--color-secondary-hover': '#78350f'
        }
    },

    forest: {
        label: 'Forest (Earthy Green)',
        primaryColorHex: '#059669',
        secondaryColorHex: '#6b7280',
        variables: {
            '--color-gray-50':  '#f5f9f7',
            '--color-gray-100': '#ecf3ef',
            '--color-gray-200': '#d5e2db',
            '--color-gray-300': '#b0c7bb',
            '--color-gray-400': '#82a394',
            '--color-gray-500': '#5e7e6f',
            '--color-gray-600': '#435a4e',
            '--color-gray-700': '#2f4038',
            '--color-gray-800': '#1d2b24',
            '--color-gray-900': '#0f1a14',
            '--color-white':    '#fbfdfb',
            '--text-primary':   '#0f1a14',
            '--text-secondary': '#435a4e',
            '--text-muted':     '#82a394',
            '--text-inverse':   '#fbfdfb',
            '--bg-primary':   '#fbfdfb',
            '--bg-secondary': '#f5f9f7',
            '--bg-tertiary':  '#ecf3ef',
            '--border-color':  '#d5e2db',
            '--border-light':  '#d5e2db',
            '--border-medium': '#b0c7bb',
            '--border-dark':   '#82a394',
            '--shadow-sm': '0 1px 2px 0 rgb(15 60 30 / 0.06)',
            '--shadow-md': '0 4px 6px -1px rgb(15 60 30 / 0.08), 0 2px 4px -2px rgb(15 60 30 / 0.06)',
            '--shadow-lg': '0 10px 15px -3px rgb(15 60 30 / 0.08), 0 4px 6px -4px rgb(15 60 30 / 0.06)',
            '--shadow-xl': '0 20px 25px -5px rgb(15 60 30 / 0.08), 0 8px 10px -6px rgb(15 60 30 / 0.06)',
            '--color-primary':       '#059669',
            '--color-primary-hover': '#047857',
            '--color-primary-light': '#10b981',
            '--color-primary-bg':    '#d1fae5',
            '--color-secondary':       '#6b7280',
            '--color-secondary-hover': '#4b5563',
            '--color-success':    '#059669',
            '--color-success-bg': '#d1fae5'
        }
    },

    nord: {
        label: 'Nord (Arctic)',
        primaryColorHex: '#5e81ac',
        secondaryColorHex: '#81a1c1',
        variables: {
            '--color-gray-50':  '#eceff4',
            '--color-gray-100': '#e5e9f0',
            '--color-gray-200': '#d8dee9',
            '--color-gray-300': '#b8c4d4',
            '--color-gray-400': '#7b8fa4',
            '--color-gray-500': '#616e7c',
            '--color-gray-600': '#4c566a',
            '--color-gray-700': '#3b4252',
            '--color-gray-800': '#2e3440',
            '--color-gray-900': '#242933',
            '--color-white':    '#f8fafc',
            '--text-primary':   '#2e3440',
            '--text-secondary': '#4c566a',
            '--text-muted':     '#7b8fa4',
            '--text-inverse':   '#eceff4',
            '--bg-primary':   '#f8fafc',
            '--bg-secondary': '#eceff4',
            '--bg-tertiary':  '#e5e9f0',
            '--border-color':  '#d8dee9',
            '--border-light':  '#d8dee9',
            '--border-medium': '#b8c4d4',
            '--border-dark':   '#7b8fa4',
            '--shadow-sm': '0 1px 2px 0 rgb(46 52 64 / 0.06)',
            '--shadow-md': '0 4px 6px -1px rgb(46 52 64 / 0.08), 0 2px 4px -2px rgb(46 52 64 / 0.06)',
            '--shadow-lg': '0 10px 15px -3px rgb(46 52 64 / 0.08), 0 4px 6px -4px rgb(46 52 64 / 0.06)',
            '--shadow-xl': '0 20px 25px -5px rgb(46 52 64 / 0.08), 0 8px 10px -6px rgb(46 52 64 / 0.06)',
            '--color-primary':       '#5e81ac',
            '--color-primary-hover': '#4c6e96',
            '--color-primary-light': '#81a1c1',
            '--color-primary-bg':    '#dfe8f1',
            '--color-secondary':       '#81a1c1',
            '--color-secondary-hover': '#6d8faf',
            '--color-success':    '#a3be8c',
            '--color-success-bg': '#edf3e8',
            '--color-warning':    '#ebcb8b',
            '--color-warning-bg': '#faf4e6',
            '--color-error':      '#bf616a',
            '--color-error-bg':   '#f5e0e2',
            '--color-info':       '#88c0d0',
            '--color-info-bg':    '#e3f1f5'
        }
    },

    high_contrast: {
        label: 'High Contrast',
        primaryColorHex: '#3391ff',
        secondaryColorHex: '#b0b0b0',
        variables: {
            '--color-gray-50':  '#1a1a1a',
            '--color-gray-100': '#1a1a1a',
            '--color-gray-200': '#333333',
            '--color-gray-300': '#4d4d4d',
            '--color-gray-400': '#808080',
            '--color-gray-500': '#b0b0b0',
            '--color-gray-600': '#d0d0d0',
            '--color-gray-700': '#e8e8e8',
            '--color-gray-800': '#f2f2f2',
            '--color-gray-900': '#ffffff',
            '--color-white':    '#000000',
            '--text-primary':   '#ffffff',
            '--text-secondary': '#d0d0d0',
            '--text-muted':     '#808080',
            '--text-inverse':   '#000000',
            '--bg-primary':   '#000000',
            '--bg-secondary': '#1a1a1a',
            '--bg-tertiary':  '#1a1a1a',
            '--border-color':  '#4d4d4d',
            '--border-light':  '#333333',
            '--border-medium': '#4d4d4d',
            '--border-dark':   '#808080',
            '--shadow-sm': '0 1px 2px 0 rgb(0 0 0 / 0.5)',
            '--shadow-md': '0 4px 6px -1px rgb(0 0 0 / 0.6), 0 2px 4px -2px rgb(0 0 0 / 0.5)',
            '--shadow-lg': '0 10px 15px -3px rgb(0 0 0 / 0.6), 0 4px 6px -4px rgb(0 0 0 / 0.5)',
            '--shadow-xl': '0 20px 25px -5px rgb(0 0 0 / 0.6), 0 8px 10px -6px rgb(0 0 0 / 0.5)',
            '--color-primary':       '#3391ff',
            '--color-primary-hover': '#66b0ff',
            '--color-primary-light': '#66b0ff',
            '--color-primary-bg':    '#0a2a4d',
            '--color-secondary':       '#b0b0b0',
            '--color-secondary-hover': '#d0d0d0',
            '--color-success':    '#00ff88',
            '--color-success-bg': '#003d1f',
            '--color-warning':    '#ffcc00',
            '--color-warning-bg': '#4d3d00',
            '--color-error':      '#ff4444',
            '--color-error-bg':   '#4d0000',
            '--color-info':       '#00e5ff',
            '--color-info-bg':    '#003d44'
        }
    }
};

/**
 * Collect all CSS variable names used across every theme.
 * Cached after first call.
 */
function _wimiGetAllThemeVarNames() {
    if (window._wimiAllThemeVarNames) return window._wimiAllThemeVarNames;
    var names = new Set();
    for (var key in window.WIMI_THEMES) {
        var theme = window.WIMI_THEMES[key];
        for (var varName in theme.variables) {
            names.add(varName);
        }
    }
    window._wimiAllThemeVarNames = Array.from(names);
    return window._wimiAllThemeVarNames;
}

/**
 * Apply a theme's CSS variable overrides to :root.
 * @param {string} themeName - Key in WIMI_THEMES
 */
function _wimiApplyThemeVariables(themeName) {
    var root = document.documentElement.style;
    var allVars = _wimiGetAllThemeVarNames();
    var theme = window.WIMI_THEMES[themeName] || window.WIMI_THEMES.default;

    for (var i = 0; i < allVars.length; i++) {
        root.removeProperty(allVars[i]);
    }

    for (var varName in theme.variables) {
        root.setProperty(varName, theme.variables[varName]);
    }
}

/**
 * Apply persisted visual settings on every page load.
 */
(async function() {
    try {
        await api.ready();
        var prefs = await api.getUserPreferences();
        window.wimiPreferences = prefs;

        var root = document.documentElement.style;
        var themeName = prefs.theme_name || 'default';
        var theme = window.WIMI_THEMES[themeName] || window.WIMI_THEMES.default;

        _wimiApplyThemeVariables(themeName);

        // Always apply saved color preferences — ensures consistency
        // regardless of whether they match the current theme's defaults
        if (prefs.primary_color_hex) {
            root.setProperty('--color-primary', prefs.primary_color_hex);
            root.setProperty('--color-primary-hover', _wimiAdjustColor(prefs.primary_color_hex, -25));
            root.setProperty('--color-primary-light', _wimiAdjustColor(prefs.primary_color_hex, 20));
            root.setProperty('--color-primary-bg', _wimiAdjustColor(prefs.primary_color_hex, 180));
        }

        if (prefs.secondary_color_hex) {
            root.setProperty('--color-secondary', prefs.secondary_color_hex);
            root.setProperty('--color-secondary-hover', _wimiAdjustColor(prefs.secondary_color_hex, -25));
        }

        if (prefs.font_size_scale != null && prefs.font_size_scale !== 1.0) {
            root.fontSize = (prefs.font_size_scale * 16) + 'px';
        }

        // Apply UI density — including comfortable (reset to CSS defaults)
        if (prefs.ui_density === 'compact') {
            root.setProperty('--space-sm', '0.25rem');
            root.setProperty('--space-md', '0.75rem');
            root.setProperty('--space-lg', '1rem');
            root.setProperty('--space-xl', '1.5rem');
        } else if (prefs.ui_density === 'spacious') {
            root.setProperty('--space-sm', '0.75rem');
            root.setProperty('--space-md', '1.25rem');
            root.setProperty('--space-lg', '2rem');
            root.setProperty('--space-xl', '2.5rem');
        } else {
            root.removeProperty('--space-sm');
            root.removeProperty('--space-md');
            root.removeProperty('--space-lg');
            root.removeProperty('--space-xl');
        }

        if (prefs.show_animations === false) {
            var style = document.createElement('style');
            style.id = 'wimi-no-animations';
            style.textContent = '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }';
            document.head.appendChild(style);
        }
    } catch (e) {
        console.warn('Settings load failed:', e);
    }
})();
