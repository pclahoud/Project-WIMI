/**
 * Render one manual chapter from the markdown embedded in its page (#428).
 *
 * The chapter's text arrives as a <script type="text/markdown"> block written
 * by `scripts/check_manual_sync.py` from `docs/manual/NN_slug.md`. It is
 * embedded rather than fetched for the reason the tree editor's import guide
 * is: a PyInstaller build ships no `docs/`, and pages load from `file://`
 * where Chromium treats each origin as opaque, so there is no `fetch()` to
 * fall back on either.
 *
 * Why this is a second markdown renderer in the tree
 * --------------------------------------------------
 * `parseMarkdown` in `import_export.js` already renders markdown, and this
 * deliberately does not reuse it. That function lives in the tree editor's
 * import/export module -- 2,000 lines that reach for `TreeState` and the
 * import bridge slots -- so a help page cannot load it without loading the
 * tree editor's machinery, and lifting it out would edit a file with a live
 * consumer (the Import Format Help modal) whose only failure mode is a modal
 * that renders nothing.
 *
 * The cost of the duplication is bounded, and it is bounded on purpose: the
 * CHAPTERS are not duplicated, only the rendering, and
 * `tests/test_manual_chapters.py` asserts every chapter stays inside what
 * this function supports. That test is the contract. It exists because the
 * failure mode of a regex renderer is never an error -- it is the wrong thing
 * drawn in the shipped app, where nobody is looking, which is exactly how
 * `parseMarkdown`'s three known limits survived.
 *
 * What is supported: h2-h6 with anchor ids, paragraphs, unordered lists
 * (nested), ordered lists (keeping the number the source starts at), bold,
 * italic, inline code, fenced code blocks, horizontal rules, and links to
 * other pages in the app.
 *
 * What is NOT supported, each refused by the test rather than rendered
 * wrong: tables, blockquotes, images, and links out to the web -- the last
 * because this view has no address bar, so an external link would navigate
 * the application window away from WIMI.
 *
 * HTML comments are STRIPPED, and that is a measurement rather than a courtesy
 * -----------------------------------------------------------------------------
 * A chapter may carry an HTML comment, and the tour's short forms (#430) are
 * written as one. Without `helpStripComments` below, such a comment reaches the
 * student as ORDINARY VISIBLE PROSE: nothing here matched it, so it fell
 * through to the paragraph branch, `helpEscapeHtml` turned its `<` into `&lt;`,
 * and it was drawn as a paragraph of its own. Measured in a real QtWebEngine on
 * 2026-10-07, chapter 1 with one comment planted in it:
 *
 *     embed_has_marker      true    (the <script> embed keeps it verbatim)
 *     innertext_has_marker  true    <-- a student reads it
 *     comment_nodes         0       (it is a <p>, not a DOM comment)
 *
 * and the page showed, between a heading and its first paragraph:
 *
 *     <!-- tour page: entry-form anchor: the "Why did you get this wrong?"
 *     editor text: ... -->
 *
 * So the strip is what makes a generator-only marker possible at all.
 */

/**
 * Escape text that is about to be interpolated into markup.
 */
function helpEscapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/**
 * A stable id for a heading, so `help_weights.html#rescaling` can name a
 * place inside a chapter.
 */
function helpSlugify(text) {
    return String(text)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

/**
 * Inline markup, applied to one already-escaped run of text.
 *
 * Escaping happens first and on the whole line, so a `<` in prose is safe
 * before any of these patterns run. Code spans are handled before emphasis
 * so `**` inside a code span is left alone.
 */
function helpRenderInline(text) {
    var out = helpEscapeHtml(text);
    out = out.replace(/`([^`]+)`/g, function (match, code) {
        return '<code>' + code + '</code>';
    });
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Requires a non-space character at each end, so `2 * 3` is not italics.
    out = out.replace(/\*([^\s*](?:[^*]*[^\s*])?)\*/g, '<em>$1</em>');
    out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>');
    return out;
}

/**
 * Render a chapter's markdown to HTML.
 *
 * `skipLeadingTitle` defaults to true: the page's own `<h1>` is written into
 * the markup by the generator, because `tests/test_heading_order.py` reads
 * markup and a heading that only exists after a script has run is invisible
 * to it (#317's lesson). So the source's `# Title` line is dropped here
 * rather than rendered into a second h1.
 */
function renderHelpMarkdown(markdown, options) {
    var settings = options || {};
    var skipLeadingTitle = settings.skipLeadingTitle !== false;
    var lines = helpStripComments(
        String(markdown).replace(/\r\n/g, '\n').split('\n')
    );
    var html = [];
    var usedIds = {};
    var titleSkipped = false;
    var index = 0;

    function uniqueId(text) {
        var base = helpSlugify(text) || 'section';
        var id = base;
        var counter = 2;
        while (usedIds[id]) {
            id = base + '-' + counter;
            counter += 1;
        }
        usedIds[id] = true;
        return id;
    }

    while (index < lines.length) {
        var line = lines[index];

        // Fenced code block.
        var fence = /^```(\w*)\s*$/.exec(line);
        if (fence) {
            var code = [];
            index += 1;
            while (index < lines.length && !/^```\s*$/.test(lines[index])) {
                code.push(lines[index]);
                index += 1;
            }
            index += 1;  // the closing fence
            var langClass = fence[1] ? ' class="language-' + fence[1] + '"' : '';
            html.push(
                '<pre' + langClass + '><code>' +
                helpEscapeHtml(code.join('\n')) +
                '</code></pre>'
            );
            continue;
        }

        var heading = /^(#{1,6}) +(.*\S)\s*$/.exec(line);
        if (heading) {
            index += 1;
            var level = heading[1].length;
            if (level === 1 && skipLeadingTitle && !titleSkipped) {
                titleSkipped = true;
                continue;
            }
            var id = uniqueId(heading[2]);
            html.push(
                '<h' + level + ' id="' + id + '">' +
                helpRenderInline(heading[2]) +
                '</h' + level + '>'
            );
            continue;
        }

        if (/^-{3,}\s*$/.test(line)) {
            html.push('<hr>');
            index += 1;
            continue;
        }

        // Unordered list, with nesting by two-space indent.
        //
        // A wrapped bullet continues onto the next line, which chapters do all
        // the time because prose is wrapped at 80 columns. Without the
        // continuation branch below, the run ENDS at the first wrapped line
        // and its remainder becomes a stray paragraph after a one-item list --
        // measured on this manual's own second chapter, which rendered 17
        // <ul> elements for six lists. Nothing errors; it simply reads wrong.
        //
        // A blank line still ends a run, so bullets separated by blank lines
        // become separate lists. That is a visual difference of one margin and
        // is left alone deliberately rather than modelled.
        if (/^\s*[-*] +\S/.test(line)) {
            var items = [];
            while (index < lines.length) {
                var current = lines[index];
                var bullet = /^(\s*)[-*] +(.*)$/.exec(current);
                if (bullet) {
                    items.push({
                        level: Math.floor(bullet[1].length / 2),
                        text: bullet[2]
                    });
                    index += 1;
                    continue;
                }
                if (helpContinuesAnItem(current) && items.length) {
                    items[items.length - 1].text += ' ' + current.trim();
                    index += 1;
                    continue;
                }
                break;
            }
            html.push(helpRenderList(items, 0, { index: 0 }));
            continue;
        }

        // Ordered list. The number the source starts at is kept, which is one
        // of `parseMarkdown`'s three documented limits (it renumbers every
        // run from 1).
        if (/^\s*\d+\. +\S/.test(line)) {
            var ordered = [];
            var start = parseInt(/^\s*(\d+)\./.exec(line)[1], 10);
            while (index < lines.length) {
                var numbered = /^\s*\d+\. +(.*)$/.exec(lines[index]);
                if (numbered) {
                    ordered.push(numbered[1]);
                    index += 1;
                    continue;
                }
                if (helpContinuesAnItem(lines[index]) && ordered.length) {
                    ordered[ordered.length - 1] += ' ' + lines[index].trim();
                    index += 1;
                    continue;
                }
                break;
            }
            html.push(
                '<ol start="' + start + '">' +
                ordered.map(function (item) {
                    return '<li>' + helpRenderInline(item) + '</li>';
                }).join('') +
                '</ol>'
            );
            continue;
        }

        if (line.trim() === '') {
            index += 1;
            continue;
        }

        // A paragraph: consecutive lines that start nothing else.
        var paragraph = [];
        while (index < lines.length) {
            var next = lines[index];
            if (
                next.trim() === '' ||
                /^```/.test(next) ||
                /^#{1,6} +/.test(next) ||
                /^-{3,}\s*$/.test(next) ||
                /^\s*[-*] +\S/.test(next) ||
                /^\s*\d+\. +\S/.test(next)
            ) {
                break;
            }
            paragraph.push(next.trim());
            index += 1;
        }
        html.push('<p>' + helpRenderInline(paragraph.join(' ')) + '</p>');
    }

    return html.join('\n');
}

/**
 * Blank out every HTML comment, so nothing inside one can be drawn.
 *
 * Takes and returns an array of lines, keeping the array the same length: a
 * comment on its own lines leaves empty lines behind, and an empty line is
 * exactly what the renderer already skips. REMOVING the lines instead would
 * join the paragraph above a comment to the paragraph below it, which is a
 * silent change to a chapter nobody edited.
 *
 * A comment spans lines, because a tour short form is written over several
 * (#430). The scan therefore carries `inComment` across iterations rather than
 * matching a pattern per line.
 *
 * Inside a fenced code block nothing is stripped. A chapter may show a file
 * verbatim -- `03_outline_to_tree.md` ships a 58-line prompt that has to reach
 * the page byte-identical -- so a `<!--` in a fence is content, not a comment.
 */
function helpStripComments(lines) {
    var out = [];
    var inFence = false;
    var inComment = false;
    for (var i = 0; i < lines.length; i += 1) {
        var line = lines[i];
        if (!inComment && /^```/.test(line)) {
            inFence = !inFence;
            out.push(line);
            continue;
        }
        if (inFence) {
            out.push(line);
            continue;
        }
        var rest = line;
        var kept = '';
        while (rest.length) {
            if (inComment) {
                var close = rest.indexOf('-->');
                if (close === -1) {
                    rest = '';
                } else {
                    rest = rest.slice(close + 3);
                    inComment = false;
                }
            } else {
                var open = rest.indexOf('<!--');
                if (open === -1) {
                    kept += rest;
                    rest = '';
                } else {
                    kept += rest.slice(0, open);
                    rest = rest.slice(open + 4);
                    inComment = true;
                }
            }
        }
        out.push(kept);
    }
    return out;
}

/**
 * Is this line the continuation of the list item above it?
 *
 * Anything that opens a block of its own is not: another bullet, a number, a
 * heading, a fence, a rule, or a blank line. Everything else inside a list run
 * is the wrapped remainder of the item before it.
 */
function helpContinuesAnItem(line) {
    if (!line || line.trim() === '') {
        return false;
    }
    return !(
        /^```/.test(line) ||
        /^#{1,6} +/.test(line) ||
        /^-{3,}\s*$/.test(line) ||
        /^\s*[-*] +\S/.test(line) ||
        /^\s*\d+\. +\S/.test(line)
    );
}

/**
 * Turn a flat list of `{level, text}` bullets into nested <ul> markup.
 *
 * `cursor` is an object so the recursion shares one position; a plain number
 * would be copied into each call and the nesting would repeat items.
 */
function helpRenderList(items, level, cursor) {
    var parts = [];
    while (cursor.index < items.length) {
        var item = items[cursor.index];
        if (item.level < level) {
            break;
        }
        if (item.level > level) {
            // A deeper bullet belongs inside the item just emitted. When there
            // is no such item -- a run that opens already indented -- it
            // becomes a list of its own rather than slicing markup that is not
            // there.
            var nested = helpRenderList(items, item.level, cursor);
            if (parts.length) {
                parts[parts.length - 1] = parts[parts.length - 1]
                    .replace(/<\/li>$/, nested + '</li>');
            } else {
                parts.push('<li>' + nested + '</li>');
            }
            continue;
        }
        cursor.index += 1;
        parts.push('<li>' + helpRenderInline(item.text) + '</li>');
    }
    return '<ul>' + parts.join('') + '</ul>';
}

/**
 * Scroll to `location.hash` once the chapter exists.
 *
 * DEFENSIVE, AND MEASURED TO BE SO -- do not describe it as load-bearing.
 *
 * The reasoning that produced it is sound: a fragment names a heading that
 * does not exist while the document is parsed, because at that moment the only
 * thing in the body is the holding paragraph. The reasoning is also not
 * sufficient, because Chromium defers and retries its own fragment scroll
 * until the document has finished loading, and the render above happens on
 * `DOMContentLoaded` -- i.e. before that retry. Measured on 2026-10-06 by
 * deleting the one call to this function and re-running
 * `tests/wimi_test/scenarios/test_manual_renders_in_the_app.py`, which still
 * passed: `help_the_premise.html#if-you-do-only-one-thing` landed on the
 * heading with no help from here.
 *
 * It is kept rather than deleted because the condition it covers is one line
 * away: the moment rendering becomes asynchronous -- an `await`, a bridge
 * call, a chapter split across requests -- the native retry has already
 * happened and every deep link silently lands at the top of the page. What
 * must not happen is a future reader finding this and concluding deep links
 * are tested through it; the scenario asserts the outcome and does not isolate
 * the mechanism, and it says so.
 */
function helpApplyHashTarget() {
    var hash = window.location.hash;
    if (!hash || hash.length < 2) {
        return;
    }
    var target = null;
    try {
        target = document.getElementById(decodeURIComponent(hash.slice(1)));
    } catch (error) {
        target = document.getElementById(hash.slice(1));
    }
    if (target && typeof target.scrollIntoView === 'function') {
        target.scrollIntoView();
    }
}

/**
 * Render the embedded chapter into the page.
 */
function initHelpChapter() {
    var body = document.getElementById('help-chapter-body');
    if (!body) {
        return;
    }
    var source = document.getElementById('help-chapter-source');
    var markdown = source ? source.textContent : '';
    if (!markdown || !markdown.trim()) {
        // Honest rather than silent: the page cannot show a chapter it does
        // not have, and the holding line must not keep claiming it is coming.
        body.innerHTML =
            '<p class="help-body-error">This chapter did not load. Its text is ' +
            'generated into this page from <code>docs/manual/</code> by ' +
            '<code>scripts/check_manual_sync.py</code>.</p>';
        return;
    }
    body.innerHTML = renderHelpMarkdown(markdown.trim());
    helpApplyHashTarget();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initHelpChapter);
} else {
    initHelpChapter();
}
