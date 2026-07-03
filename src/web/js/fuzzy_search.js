/**
 * WIMI Fuzzy Search Module
 * Phase 4 Stage 4 - Fuse.js wrapper for subject and tag searching
 *
 * Provides instant local fuzzy search by caching all subjects/tags
 * at page load and using Fuse.js for matching.
 *
 * Enhanced with alias support: subjects can have aliases (eponyms, acronyms,
 * alternate names, colloquial terms) that are searched with ~35% weight.
 */

// =========================================================================
// FuzzySearch Class
// =========================================================================

class FuzzySearch {
    constructor() {
        this.subjectIndex = null;
        this.tagIndex = null;
        this.subjects = [];
        this.tags = [];
        this.isInitialized = false;
        this.aliasesEnabled = false;

        // Fuse.js configuration for subjects (with alias support)
        // Weight distribution: name 50%, aliases 35%, path 15%
        this.subjectFuseOptions = {
            keys: [
                { name: 'name', weight: 0.5 },
                { name: 'aliasesString', weight: 0.35 },
                { name: 'path', weight: 0.15 }
            ],
            threshold: 0.4,           // 0 = exact match, 1 = match anything
            distance: 100,            // How far to search for fuzzy match
            minMatchCharLength: 2,
            includeScore: true,
            includeMatches: true,     // Include match indices for highlighting
            ignoreLocation: true,     // Search entire string, not just beginning
            findAllMatches: true
        };

        // Legacy config without aliases (used when aliasesString not present)
        this.subjectFuseOptionsLegacy = {
            keys: [
                { name: 'name', weight: 0.7 },
                { name: 'path', weight: 0.3 }
            ],
            threshold: 0.4,
            distance: 100,
            minMatchCharLength: 2,
            includeScore: true,
            includeMatches: true,
            ignoreLocation: true,
            findAllMatches: true
        };

        // Fuse.js configuration for tags
        this.tagFuseOptions = {
            keys: [
                { name: 'name', weight: 0.7 },
                { name: 'groupName', weight: 0.3 }
            ],
            threshold: 0.5,           // More lenient matching for tags
            distance: 100,
            minMatchCharLength: 2,
            includeScore: true,
            includeMatches: true,
            ignoreLocation: true,
            findAllMatches: true
        };
    }
    
    /**
     * Initialize the subject search index
     * @param {Array} subjects - Array of subject objects with id, name, path, and optionally aliasesString
     */
    initSubjectIndex(subjects) {
        this.subjects = subjects || [];

        // Check if subjects have alias data (aliasesString field)
        this.aliasesEnabled = this.subjects.some(s => s.aliasesString !== undefined);

        if (typeof Fuse !== 'undefined' && this.subjects.length > 0) {
            // Use alias-aware config if aliases are present
            const options = this.aliasesEnabled
                ? this.subjectFuseOptions
                : this.subjectFuseOptionsLegacy;

            this.subjectIndex = new Fuse(this.subjects, options);

            const aliasCount = this.subjects.filter(s => s.aliasesString).length;
            console.log(`✅ Subject index initialized with ${this.subjects.length} subjects` +
                (this.aliasesEnabled ? ` (${aliasCount} with aliases)` : ''));
        } else if (typeof Fuse === 'undefined') {
            console.warn('⚠️ Fuse.js not loaded, fuzzy search unavailable');
        }
    }
    
    /**
     * Initialize the tag search index
     * @param {Array} tagHierarchy - Array of tag groups with nested children
     */
    initTagIndex(tagHierarchy) {
        // Flatten tag hierarchy for searching
        this.tags = this._flattenTagHierarchy(tagHierarchy || []);
        
        if (typeof Fuse !== 'undefined' && this.tags.length > 0) {
            this.tagIndex = new Fuse(this.tags, this.tagFuseOptions);
            console.log(`✅ Tag index initialized with ${this.tags.length} tags`);
        }
    }
    
    /**
     * Flatten tag hierarchy into searchable array
     * Only includes leaf tags (not groups)
     * @param {Array} hierarchy - Nested tag hierarchy
     * @returns {Array} Flat array of searchable tags
     */
    _flattenTagHierarchy(hierarchy) {
        const flatTags = [];
        
        const processItem = (item, parentName = null) => {
            // Check if this is a group (has children) or a leaf tag
            const hasChildren = item.children && item.children.length > 0;
            const isGroup = item.is_group === true || hasChildren;
            
            if (isGroup) {
                // This is a group, process its children
                const children = item.children || [];
                for (const child of children) {
                    processItem(child, item.name);
                }
            } else {
                // This is a leaf tag, add it to the flat list
                // NOTE: description is carried for tooltip display only —
                // it is deliberately NOT part of the Fuse search keys.
                flatTags.push({
                    id: item.id,
                    name: item.name,
                    groupName: parentName || '',
                    color: item.color,
                    description: item.description || '',
                    fullPath: parentName ? `${parentName} > ${item.name}` : item.name
                });
            }
        };
        
        for (const item of hierarchy) {
            processItem(item);
        }
        
        console.log(`📋 Flattened ${flatTags.length} tags from hierarchy`);
        return flatTags;
    }
    
    /**
     * Search subjects with fuzzy matching
     * @param {string} query - Search query
     * @param {number} limit - Maximum results to return
     * @returns {Array} Array of matching subjects with scores and matchSource
     */
    searchSubjects(query, limit = 10) {
        if (!query || query.length < 2) {
            return [];
        }

        // If Fuse.js not available or no index, fall back to simple filter
        if (!this.subjectIndex) {
            return this._simpleSearchWithAliases(this.subjects, query, limit);
        }

        const results = this.subjectIndex.search(query, { limit });

        return results.map((result, index) => {
            // Determine which field matched (for display purposes)
            const matchSource = this._getMatchSource(result, query);

            return {
                ...result.item,
                score: result.score,
                matches: result.matches,
                matchSource: matchSource,
                matchedAlias: matchSource.type === 'alias' ? matchSource.value : null,
                isBestMatch: index === 0 && result.score < 0.3
            };
        });
    }

    /**
     * Determine which field matched in a search result
     * @param {object} result - Fuse.js search result
     * @param {string} query - Original search query
     * @returns {object} Match source info { type: 'name'|'alias'|'path', value: string }
     */
    _getMatchSource(result, query) {
        const lowerQuery = query.toLowerCase();
        const item = result.item;

        // Check matches array from Fuse.js to see which key matched best
        if (result.matches && result.matches.length > 0) {
            // Find the match with the best (lowest) score or most indices
            const matchedKeys = result.matches.map(m => m.key);

            // Priority: aliasesString > name > path
            if (matchedKeys.includes('aliasesString') && item.aliasesString) {
                // Find which specific alias matched
                const matchedAlias = this._findMatchedAlias(item, lowerQuery);
                if (matchedAlias) {
                    return { type: 'alias', value: matchedAlias };
                }
            }

            if (matchedKeys.includes('name')) {
                return { type: 'name', value: item.name };
            }

            if (matchedKeys.includes('path')) {
                return { type: 'path', value: item.path };
            }
        }

        // Fallback: check manually which field contains the query
        if (item.name && item.name.toLowerCase().includes(lowerQuery)) {
            return { type: 'name', value: item.name };
        }

        if (item.aliasesString) {
            const matchedAlias = this._findMatchedAlias(item, lowerQuery);
            if (matchedAlias) {
                return { type: 'alias', value: matchedAlias };
            }
        }

        if (item.path && item.path.toLowerCase().includes(lowerQuery)) {
            return { type: 'path', value: item.path };
        }

        return { type: 'name', value: item.name };
    }

    /**
     * Find which specific alias matched a query
     * @param {object} item - Subject item with aliases array
     * @param {string} lowerQuery - Lowercase search query
     * @returns {string|null} The matched alias name or null
     */
    _findMatchedAlias(item, lowerQuery) {
        if (!item.aliases || !Array.isArray(item.aliases)) {
            // Try parsing from aliasesString
            if (item.aliasesString) {
                const aliasNames = item.aliasesString.split(' | ').filter(a => a);
                for (const alias of aliasNames) {
                    if (alias.toLowerCase().includes(lowerQuery)) {
                        return alias;
                    }
                }
            }
            return null;
        }

        // Check each alias
        for (const alias of item.aliases) {
            const aliasName = alias.alias_name || alias.name || alias;
            if (typeof aliasName === 'string' && aliasName.toLowerCase().includes(lowerQuery)) {
                return aliasName;
            }
        }

        return null;
    }

    /**
     * Simple search fallback that includes alias matching
     * @param {Array} items - Items to search
     * @param {string} query - Search query
     * @param {number} limit - Maximum results
     * @returns {Array} Matching items with scores
     */
    _simpleSearchWithAliases(items, query, limit) {
        if (!query || !items) return [];

        const lowerQuery = query.toLowerCase();
        const queryWords = lowerQuery.split(/\s+/).filter(w => w.length > 0);

        const scored = items.map(item => {
            const name = (item.name || '').toLowerCase();
            const aliasesStr = (item.aliasesString || '').toLowerCase();
            const path = (item.path || '').toLowerCase();

            let score = 1;
            let matches = false;
            let matchSource = { type: 'name', value: item.name };

            // Exact name match - best score
            if (name === lowerQuery) {
                score = 0;
                matches = true;
                matchSource = { type: 'name', value: item.name };
            }
            // Exact alias match
            else if (aliasesStr && aliasesStr.split(' | ').some(a => a === lowerQuery)) {
                score = 0.05;
                matches = true;
                const matchedAlias = this._findMatchedAlias(item, lowerQuery);
                matchSource = { type: 'alias', value: matchedAlias || lowerQuery };
            }
            // Name starts with query
            else if (name.startsWith(lowerQuery)) {
                score = 0.1;
                matches = true;
            }
            // Alias starts with query
            else if (aliasesStr && aliasesStr.split(' | ').some(a => a.startsWith(lowerQuery))) {
                score = 0.15;
                matches = true;
                const matchedAlias = this._findMatchedAlias(item, lowerQuery);
                matchSource = { type: 'alias', value: matchedAlias || lowerQuery };
            }
            // Name contains query
            else if (name.includes(lowerQuery)) {
                score = 0.3;
                matches = true;
            }
            // Alias contains query
            else if (aliasesStr && aliasesStr.includes(lowerQuery)) {
                score = 0.35;
                matches = true;
                const matchedAlias = this._findMatchedAlias(item, lowerQuery);
                matchSource = { type: 'alias', value: matchedAlias || lowerQuery };
            }
            // Path contains query
            else if (path.includes(lowerQuery)) {
                score = 0.5;
                matches = true;
                matchSource = { type: 'path', value: item.path };
            }
            // Any word match
            else if (queryWords.some(w => name.includes(w) || aliasesStr.includes(w) || path.includes(w))) {
                score = 0.7;
                matches = true;
            }

            return { item, score, matches, matchSource };
        });

        return scored
            .filter(s => s.matches)
            .sort((a, b) => a.score - b.score)
            .slice(0, limit)
            .map((s, index) => ({
                ...s.item,
                score: s.score,
                matches: [],
                matchSource: s.matchSource,
                matchedAlias: s.matchSource.type === 'alias' ? s.matchSource.value : null,
                isBestMatch: index === 0 && s.score < 0.3
            }));
    }
    
    /**
     * Search tags with fuzzy matching
     * @param {string} query - Search query
     * @param {number} limit - Maximum results to return
     * @returns {Array} Array of matching tags with scores
     */
    searchTags(query, limit = 10) {
        if (!query || query.length < 2) {
            return [];
        }
        
        // If Fuse.js not available or no index, fall back to simple filter
        if (!this.tagIndex) {
            return this._simpleSearch(this.tags, query, 'name', limit);
        }
        
        const results = this.tagIndex.search(query, { limit });
        
        return results.map((result, index) => ({
            ...result.item,
            score: result.score,
            matches: result.matches,
            isBestMatch: index === 0 && result.score < 0.3
        }));
    }
    
    /**
     * Simple contains-based search fallback with basic scoring
     * @param {Array} items - Items to search
     * @param {string} query - Search query
     * @param {string} field - Field to search in
     * @param {number} limit - Maximum results
     * @returns {Array} Matching items with scores
     */
    _simpleSearch(items, query, field, limit) {
        if (!query || !items) return [];
        
        const lowerQuery = query.toLowerCase();
        const queryWords = lowerQuery.split(/\s+/).filter(w => w.length > 0);
        
        // Score each item
        const scored = items.map(item => {
            const value = (item[field] || '').toLowerCase();
            const groupName = (item.groupName || '').toLowerCase();
            
            let score = 1; // Default score (lower is better)
            let matches = false;
            
            // Exact match - best score
            if (value === lowerQuery) {
                score = 0;
                matches = true;
            }
            // Starts with query - very good score
            else if (value.startsWith(lowerQuery)) {
                score = 0.1;
                matches = true;
            }
            // Contains query as whole phrase - good score
            else if (value.includes(lowerQuery)) {
                score = 0.3;
                matches = true;
            }
            // Contains all query words (in any order)
            else if (queryWords.every(w => value.includes(w) || groupName.includes(w))) {
                score = 0.5;
                matches = true;
            }
            // Contains any query word
            else if (queryWords.some(w => value.includes(w) || groupName.includes(w))) {
                score = 0.7;
                matches = true;
            }
            
            return { item, score, matches };
        });
        
        // Filter to matches, sort by score, limit results
        return scored
            .filter(s => s.matches)
            .sort((a, b) => a.score - b.score)
            .slice(0, limit)
            .map((s, index) => ({
                ...s.item,
                score: s.score,
                matches: [],
                isBestMatch: index === 0 && s.score < 0.3
            }));
    }
    
    /**
     * Highlight matched portions of text
     * @param {string} text - Original text
     * @param {string} query - Search query
     * @returns {string} HTML string with <mark> tags around matches
     */
    highlightMatches(text, query) {
        if (!text || !query || query.length < 2) {
            return this._escapeHtml(text || '');
        }
        
        // Escape HTML first
        const escapedText = this._escapeHtml(text);
        const lowerText = text.toLowerCase();
        const lowerQuery = query.toLowerCase();
        
        // Find all occurrences of query characters in sequence
        const indices = this._findMatchIndices(lowerText, lowerQuery);
        
        if (indices.length === 0) {
            return escapedText;
        }
        
        // Build highlighted string
        let result = '';
        let lastIndex = 0;
        
        // Group consecutive indices into ranges
        const ranges = this._groupIndicesIntoRanges(indices);
        
        for (const range of ranges) {
            // Add text before this range
            result += this._escapeHtml(text.substring(lastIndex, range.start));
            // Add highlighted text
            result += `<mark>${this._escapeHtml(text.substring(range.start, range.end + 1))}</mark>`;
            lastIndex = range.end + 1;
        }
        
        // Add remaining text
        result += this._escapeHtml(text.substring(lastIndex));
        
        return result;
    }
    
    /**
     * Find indices where query characters match in text
     * @param {string} text - Text to search (lowercase)
     * @param {string} query - Query to find (lowercase)
     * @returns {Array} Array of matching indices
     */
    _findMatchIndices(text, query) {
        const indices = [];
        let textIndex = 0;
        let queryIndex = 0;
        
        // Split query into words for better matching
        const queryWords = query.split(/\s+/).filter(w => w.length > 0);
        
        for (const word of queryWords) {
            const wordStart = text.indexOf(word, textIndex);
            if (wordStart !== -1) {
                for (let i = 0; i < word.length; i++) {
                    indices.push(wordStart + i);
                }
                textIndex = wordStart + word.length;
            }
        }
        
        // If word-based matching failed, try character-by-character
        if (indices.length === 0) {
            textIndex = 0;
            for (const char of query) {
                if (char === ' ') continue;
                const charIndex = text.indexOf(char, textIndex);
                if (charIndex !== -1) {
                    indices.push(charIndex);
                    textIndex = charIndex + 1;
                }
            }
        }
        
        return indices.sort((a, b) => a - b);
    }
    
    /**
     * Group consecutive indices into ranges
     * @param {Array} indices - Sorted array of indices
     * @returns {Array} Array of {start, end} ranges
     */
    _groupIndicesIntoRanges(indices) {
        if (indices.length === 0) return [];
        
        const ranges = [];
        let rangeStart = indices[0];
        let rangeEnd = indices[0];
        
        for (let i = 1; i < indices.length; i++) {
            if (indices[i] === rangeEnd + 1) {
                // Consecutive, extend range
                rangeEnd = indices[i];
            } else {
                // Not consecutive, save current range and start new one
                ranges.push({ start: rangeStart, end: rangeEnd });
                rangeStart = indices[i];
                rangeEnd = indices[i];
            }
        }
        
        // Add final range
        ranges.push({ start: rangeStart, end: rangeEnd });
        
        return ranges;
    }
    
    /**
     * Escape HTML special characters
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    _escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * Check if an exact match exists (for determining whether to show "create" option)
     * Checks both subject names and aliases for subjects.
     * @param {string} query - Search query
     * @param {string} type - 'subject' or 'tag'
     * @returns {boolean} True if exact match exists
     */
    hasExactMatch(query, type = 'subject') {
        if (!query) return false;

        const lowerQuery = query.toLowerCase().trim();
        const items = type === 'subject' ? this.subjects : this.tags;

        return items.some(item => {
            // Check name
            if (item.name && item.name.toLowerCase().trim() === lowerQuery) {
                return true;
            }

            // For subjects, also check aliases
            if (type === 'subject' && item.aliasesString) {
                const aliases = item.aliasesString.split(' | ').map(a => a.toLowerCase().trim());
                if (aliases.includes(lowerQuery)) {
                    return true;
                }
            }

            return false;
        });
    }

    /**
     * Check if aliases are enabled in the current index
     * @returns {boolean} True if alias search is available
     */
    hasAliasSupport() {
        return this.aliasesEnabled;
    }
    
    /**
     * Get all subjects (for tree browser)
     * @returns {Array} All cached subjects
     */
    getAllSubjects() {
        return this.subjects;
    }
    
    /**
     * Get all tags (flattened)
     * @returns {Array} All cached tags
     */
    getAllTags() {
        return this.tags;
    }
    
    /**
     * Refresh subject index with new data
     * @param {Array} subjects - New subjects array
     */
    refreshSubjects(subjects) {
        this.initSubjectIndex(subjects);
    }
    
    /**
     * Refresh tag index with new data
     * @param {Array} tagHierarchy - New tag hierarchy
     */
    refreshTags(tagHierarchy) {
        this.initTagIndex(tagHierarchy);
    }
    
    /**
     * Check if search indexes are ready
     * @returns {boolean} True if ready for searching
     */
    isReady() {
        return this.subjectIndex !== null || this.tagIndex !== null;
    }
}

// =========================================================================
// Global Instance
// =========================================================================

// Create global fuzzy search instance
const fuzzySearch = new FuzzySearch();

// Make available globally
window.fuzzySearch = fuzzySearch;
window.FuzzySearch = FuzzySearch;
