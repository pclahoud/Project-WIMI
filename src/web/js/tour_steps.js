/* GENERATED FILE - DO NOT EDIT BY HAND (issues #430, #428).
 *
 * The first-run tour's step text, collected out of the manual's chapters by
 * `scripts/check_manual_sync.py`. The single source for every string below is
 * a `<!-- tour ... -->` block in `docs/manual/NN_slug.md`, sitting beside the
 * section whose rule it compresses. To change a step, edit that block and run:
 *
 *     python scripts/check_manual_sync.py --write
 *
 * The same script with no arguments is a CI gate, so this file cannot drift
 * from the chapters. There is no allowlist: a difference is always a missing
 * --write and never a legitimate state.
 *
 * Why the step text is authored rather than sliced out of a chapter: #430
 * measured manual sections at 239-1,713 characters, and on the 1130x689
 * viewport this project measures against, a panel that size covers the thing
 * it is pointing at. So a step carries an authored short form -- the rule's
 * substance in one or two sentences, never a label a student clicks past.
 *
 * Each step carries:
 *
 *   page           one of dashboard, exam-wizard, tree-editor, session-setup, entry-form, entry-browser, analytics, calendar, settings
 *   anchor         what the step points at, in words. The data-testid
 *                  anchoring is #430's own work; this is the brief for it.
 *   text           the short form.
 *   chapter        the chapter slug, so the page is help_<chapter>.html
 *   chapter_title  that chapter's title
 *   section        the heading the block sits under
 *   link           a deep link to that section, for the step's "read more"
 *
 * Everything but page, anchor and text is DERIVED from where the block sits,
 * so a step cannot name a chapter it is not in, and a section renamed in the
 * markdown moves its own link with it.
 *
 * Steps are grouped by page and run in chapter order within a page. A page
 * with no steps is absent rather than empty: #430 reads this as
 * `(window.WIMI_TOUR_STEPS || {})[page] || []`, and an empty array drawn as a tour is the
 * two-empty-boxes-and-a-gap mistake in another file.
 *
 * 116 step(s) across 9 page(s).
 */
window.WIMI_TOUR_STEPS = {
  "dashboard": [
    {
      "page": "dashboard",
      "anchor": "exam-card-subjects",
      "text": "One subject is enough to save an entry, so you do not need the whole outline before you start logging. The entry form can create a subject too, without leaving the page.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Step 3. Put at least one subject in it",
      "link": "help_the_first_hour.html#step-3-put-at-least-one-subject-in-it"
    },
    {
      "page": "dashboard",
      "anchor": "dashboard-preview-top-mistake",
      "text": "Top mistake stays empty until you tag an entry with an error type, and tagging is optional. An empty card here is WIMI having nothing to count rather than a figure it failed to work out.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Step 6. Read the dashboard",
      "link": "help_the_first_hour.html#step-6-read-the-dashboard"
    },
    {
      "page": "dashboard",
      "anchor": "dashboard-preview-this-week",
      "text": "This week counts entries from practice in the last seven days, today included, by the session's Date Encountered rather than the day you typed them. Drafts count. The change beside it is against the seven days before.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "This week",
      "link": "help_the_first_hour.html#this-week"
    },
    {
      "page": "dashboard",
      "anchor": "dashboard-preview-streak",
      "text": "A streak day is a day a session is dated, with at least one entry logged from that session, so finishing an old block today does not extend it. At risk means yesterday counted and today has nothing yet.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Streak",
      "link": "help_the_first_hour.html#streak"
    },
    {
      "page": "dashboard",
      "anchor": "dashboard-create-first-exam",
      "text": "The order is a profile, then an exam, then at least one subject, then a session, then an entry, and each screen enforces the one before it rather than guessing. \"No session selected\" is a screen declining to invent what it is missing.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "What you cannot skip, and what the app does if you try",
      "link": "help_the_first_hour.html#what-you-cannot-skip-and-what-the-app-does-if-you-try",
      "fork": "has-exams",
      "fork_anchor": "exam-card"
    },
    {
      "page": "dashboard",
      "anchor": "exam-card-analytics",
      "text": "Analytics totals only the entries where a subject was the main one, while Browse, beside it, finds every entry that mentions it. So the two can give different numbers for the same subject and both be right.",
      "chapter": "two_screens_one_subject",
      "chapter_title": "Why two screens can disagree about one subject",
      "section": "The rule in one line",
      "link": "help_two_screens_one_subject.html#the-rule-in-one-line"
    },
    {
      "page": "dashboard",
      "anchor": "dashboard-preview-exam-filter",
      "text": "All Exams adds up every exam in this profile, suspended ones included, although only active exams are offered in this list. Pick one exam here to see its figures alone.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "The panel's exam list",
      "link": "help_reading_the_analytics.html#the-panel-s-exam-list"
    },
    {
      "page": "dashboard",
      "anchor": "dashboard-preview-report-link",
      "text": "The full report is always about one exam. With an exam picked in this panel it opens on that one; with All Exams it opens on the exam you created most recently, so its figures will not match the combined ones here.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Where View Full Report goes",
      "link": "help_reading_the_analytics.html#where-view-full-report-goes"
    },
    {
      "page": "dashboard",
      "anchor": "exam-card-delete",
      "text": "No archived subject is ever permanently removed. An exam is different: Delete Permanently, which appears only once the exam is suspended, takes its sessions and every entry with it and cannot be undone.",
      "chapter": "archive_and_restore",
      "chapter_title": "Archiving a subject, and getting it back",
      "section": "Permanent deletion does not exist",
      "link": "help_archive_and_restore.html#permanent-deletion-does-not-exist"
    },
    {
      "page": "dashboard",
      "anchor": "exam-card-suspend",
      "text": "Suspending deletes nothing: the exam keeps its sessions and entries, and Reactivate on its card undoes it. Quick Analytics stops offering it as a choice, but All Exams there still counts its entries.",
      "chapter": "archive_and_restore",
      "chapter_title": "Archiving a subject, and getting it back",
      "section": "Suspending an exam",
      "link": "help_archive_and_restore.html#suspending-an-exam"
    }
  ],
  "exam-wizard": [
    {
      "page": "exam-wizard",
      "anchor": "wizard-exam-name-input",
      "text": "Exam Name is the only field a simple exam requires. A multi-dimensional exam started from scratch also needs each of its axes named, which a template does for you. Everything else has a working default, so nothing has to be right before you can create the exam.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Step 2. Create an exam",
      "link": "help_the_first_hour.html#step-2-create-an-exam"
    },
    {
      "page": "exam-wizard",
      "anchor": "wizard-step1-template-filter-all",
      "text": "Only templates of the exam type you chose on the first step are listed, and All means all of that type. The medical exams and the CPA are Multi-Dimensional templates, so none of them appears while Simple is chosen: go Back and change the type to see them.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Which templates you are offered",
      "link": "help_the_first_hour.html#which-templates-you-are-offered"
    },
    {
      "page": "exam-wizard",
      "anchor": "wizard-exam-description-textarea",
      "text": "The Description is shown on the exam's card on the dashboard and on the Review step. Additional Notes is kept with the exam and shown nowhere but this wizard, when you reopen the exam with its Edit button.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Description and Additional Notes",
      "link": "help_the_first_hour.html#description-and-additional-notes"
    },
    {
      "page": "exam-wizard",
      "anchor": "template-card",
      "text": "A template brings the exam's axes and the names of its tree levels, and no subjects at all. Whichever you pick, your new exam starts with an empty subject tree that you fill yourself, and keeps the template's level names: nothing in WIMI renames a level afterwards.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Step 3. Put at least one subject in it",
      "link": "help_the_first_hour.html#step-3-put-at-least-one-subject-in-it"
    },
    {
      "page": "exam-wizard",
      "anchor": "wizard-step1-type-multi",
      "text": "Several axes describe the same pool of questions from different angles rather than dividing it between them, so each axis's weights run to about a hundred per cent on its own. WIMI never adds them together, and there is no combined figure anywhere in the app.",
      "chapter": "dimensions",
      "chapter_title": "Dimensions, and questions with several axes",
      "section": "The axes overlap, and that is the point",
      "link": "help_dimensions.html#the-axes-overlap-and-that-is-the-point"
    },
    {
      "page": "exam-wizard",
      "anchor": "wizard-exam-length",
      "text": "Filling this in is what lets a weight read as a number of questions as well as a percentage. Leaving it at \"Don't know yet\" is fine, and what is stored either way is a percentage of the exam.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "Percentages and question counts",
      "link": "help_weights.html#percentages-and-question-counts"
    },
    {
      "page": "exam-wizard",
      "anchor": "wizard-length-kind-range",
      "text": "On a variable-length exam every question count WIMI shows is worked out from Typical items alone, not Min or Max, and is shown to one decimal marked \"planning estimate\" rather than rounded to whole questions.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "Variable length counts are estimates",
      "link": "help_weights.html#variable-length-counts-are-estimates"
    },
    {
      "page": "exam-wizard",
      "anchor": "wizard-review",
      "text": "A new exam gets its own copy of the sixteen error types, seeded the first time you open its entry form. The copies are independent, so a definition you rewrite on one exam does not change it on another.",
      "chapter": "error_types",
      "chapter_title": "Error types: naming the mistake",
      "section": "Each exam has its own list",
      "link": "help_error_types.html#each-exam-has-its-own-list"
    }
  ],
  "tree-editor": [
    {
      "page": "tree-editor",
      "anchor": "tree-import-help",
      "text": "WIMI ships no exam outline and no model of its own: this button opens the import format guide, and Copy the whole guide inside it gives you the format to hand a chat assistant with your exam's published outline. Check the percentages it hands back, as an invented one looks like a published one.",
      "chapter": "outline_to_tree",
      "chapter_title": "Building your subject tree from a published outline",
      "section": "The one thing a model must not invent",
      "link": "help_outline_to_tree.html#the-one-thing-a-model-must-not-invent"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-row-level",
      "text": "A subject's level is stored on the subject rather than worked out from how deep it sits, so the same subject reads the same level everywhere it appears. Depth and level may disagree, and nothing is wrong when they do.",
      "chapter": "subject_hierarchies",
      "chapter_title": "Your subject tree and its levels",
      "section": "A subject's level is stored on the subject",
      "link": "help_subject_hierarchies.html#a-subject-s-level-is-stored-on-the-subject"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-add-child-level",
      "text": "Pre-filled with the level one below the parent's stored level, or the parent's own level when there is no next one. Most people accept it, and what you accept here is what is stored on the subject, so change it now if it is wrong.",
      "chapter": "subject_hierarchies",
      "chapter_title": "Your subject tree and its levels",
      "section": "The level WIMI suggests for a new child",
      "link": "help_subject_hierarchies.html#the-level-wimi-suggests-for-a-new-child"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-row-name",
      "text": "Double-click a subject's name, or press F2 on it, to rename it in place. Enter saves the new name, and so does clicking anywhere else. Renaming one appearance renames the subject everywhere it appears.",
      "chapter": "subject_hierarchies",
      "chapter_title": "Your subject tree and its levels",
      "section": "Renaming a subject",
      "link": "help_subject_hierarchies.html#renaming-a-subject"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-edit-name",
      "text": "This field has no Save button: the name is saved as soon as you leave the box or press Enter, so leaving it is not a way to back out. It renames the subject everywhere it appears.",
      "chapter": "subject_hierarchies",
      "chapter_title": "Your subject tree and its levels",
      "section": "The Name field in the details panel",
      "link": "help_subject_hierarchies.html#the-name-field-in-the-details-panel"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-search-input",
      "text": "The filter matches a subject's aliases as well as its name, so a row can match with nothing in its name highlighted. Rows above a match stay on screen to show where it sits, and the count beside the box counts matches, not rows.",
      "chapter": "subject_hierarchies",
      "chapter_title": "Your subject tree and its levels",
      "section": "Filtering the tree",
      "link": "help_subject_hierarchies.html#filtering-the-tree"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-row-shared-parents",
      "text": "A subject can have several parents, and every appearance is the same subject rather than a copy, so renaming it in one place renames it everywhere. Only the primary appearance carries its children, which is why a row marked \"also here\" is not an empty subject.",
      "chapter": "shared_subjects",
      "chapter_title": "Subjects that live in more than one place",
      "section": "What it looks like in the tree editor",
      "link": "help_shared_subjects.html#what-it-looks-like-in-the-tree-editor"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-parent-make-primary",
      "text": "Pressing a circle makes that parent primary. That changes the breadcrumb, which appearance in the tree carries the children, and the parent a new entry defaults to. It moves nothing, removes no parent, and does not change the parent any logged entry already records.",
      "chapter": "shared_subjects",
      "chapter_title": "Subjects that live in more than one place",
      "section": "What the primary parent is for",
      "link": "help_shared_subjects.html#what-the-primary-parent-is-for"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-weight-type",
      "text": "Absolute is a share of the whole exam. Relative is a share of this subject's parent, and the panel works the exam share out underneath it as Effective Weight. The same number typed into the field means a different thing in each mode.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "The weight panel tells you which kind of number you are typing",
      "link": "help_weights.html#the-weight-panel-tells-you-which-kind-of-number-you-are-typing"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-row-weight",
      "text": "A weight is a share of the whole exam at any depth, so a child can correctly carry a larger percentage than its parent, and WIMI never compares the two. The one exception is a figure marked (rel), which is that subject's share of its parent.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "So a child can be bigger than its parent",
      "link": "help_weights.html#so-a-child-can-be-bigger-than-its-parent"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-weight-range-total",
      "text": "Published blueprints routinely total more than 100%, because they classify the same questions in overlapping ways. WIMI reports your total and changes nothing, so a top-level total of 84\u2013153% is the document being itself rather than an error.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "WIMI reports your total and then leaves it alone",
      "link": "help_weights.html#wimi-reports-your-total-and-then-leaves-it-alone"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-weight-rebalance",
      "text": "This is the only control that writes a weight you did not type. It divides what is left of the 100% under the parent among siblings that are neither anchored nor locked, leaves exam percentages alone, and refuses on a top-level subject.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "What Rebalance siblings actually does",
      "link": "help_weights.html#what-rebalance-siblings-actually-does"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-weight-anchor",
      "text": "The box shows whether this value is anchored now, and Apply leaves it the way the box says. Anchored, Rebalance siblings never moves it; unticked, it joins the share a rebalance may divide. Applying a value never changes any other sibling.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "The Anchor box",
      "link": "help_weights.html#the-anchor-box"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-weight-confidence",
      "text": "This colour says where the weight came from, not how you are doing. Green is official, yellow derived from official, and orange everything else, including every imported weight. No count, chart or analysis in WIMI treats the three differently.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "The coloured badge in the weight panel",
      "link": "help_weights.html#the-coloured-badge-in-the-weight-panel"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-weight-unit-q",
      "text": "Q appears only on a Relative weight, on an exam whose length is set. A count typed here is a number of the parent's questions, not the exam's, and what WIMI saves is still a percentage of the parent.",
      "chapter": "weights",
      "chapter_title": "Weights: what a percentage means here",
      "section": "The `%` / `Q` toggle",
      "link": "help_weights.html#the-q-toggle"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-export",
      "text": "Export writes only the tree on screen and lists no dimensions, so importing the file back changes only the tree you have open and can never archive a dimension. Use it for one tree: to edit it, send it or keep a copy.",
      "chapter": "changing_your_tree",
      "chapter_title": "Changing your tree later",
      "section": "The two export buttons write different files",
      "link": "help_changing_your_tree.html#the-two-export-buttons-write-different-files"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-export-whole-exam",
      "text": "Export all writes every dimension of this exam into one file, and that list is read back as the whole exam. Re-importing it unchanged changes nothing, but delete a dimension from the file and the import archives it with its trees, unless entries are tagged in it.",
      "chapter": "changing_your_tree",
      "chapter_title": "Changing your tree later",
      "section": "The two export buttons write different files",
      "link": "help_changing_your_tree.html#the-two-export-buttons-write-different-files"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-import-preview-more",
      "text": "The preview draws four levels and about three hundred subjects, then counts the rest on lines like this one. Nothing is cut from the file: what is drawn plus what is counted is all of it, and Import takes all of it.",
      "chapter": "changing_your_tree",
      "chapter_title": "Changing your tree later",
      "section": "What the preview tells you",
      "link": "help_changing_your_tree.html#what-the-preview-tells-you"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-import-plan",
      "text": "Removed here means archived, by the same delete as the Delete button, so a removal comes back from Archived subjects. A large removed figure on what you meant as a small correction usually means the file has no ids: a renamed subject is then removed and added back.",
      "chapter": "changing_your_tree",
      "chapter_title": "Changing your tree later",
      "section": "What this import will do",
      "link": "help_changing_your_tree.html#what-this-import-will-do"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-import-scope-notice",
      "text": "A file that lists your exam's dimensions is read as the authority on which axes exist, so an axis it does not mention is archived with every subject tree in it, unless entries are tagged inside it. A new axis has none yet. Read this notice rather than pressing through it.",
      "chapter": "changing_your_tree",
      "chapter_title": "Changing your tree later",
      "section": "The expensive mistake, and it is one press away",
      "link": "help_changing_your_tree.html#the-expensive-mistake-and-it-is-one-press-away"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-import",
      "text": "An import is a merge behind a preview, and a subject carrying your entries is never removed by one. The same code works out the preview and performs the import, so the panel cannot show you one thing and do another.",
      "chapter": "changing_your_tree",
      "chapter_title": "Changing your tree later",
      "section": "Your entries outrank the blueprint",
      "link": "help_changing_your_tree.html#your-entries-outrank-the-blueprint"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-delete-confirm",
      "text": "Delete archives rather than erases. The subject, and anything the statement above lists as going with it, moves to Archived subjects at the foot of the tree, where Restore brings it back. That is so even when the statement does not mention archiving.",
      "chapter": "archive_and_restore",
      "chapter_title": "Archiving a subject, and getting it back",
      "section": "Archived, not erased",
      "link": "help_archive_and_restore.html#archived-not-erased"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-delete-promote",
      "text": "Ticked, these children move to the top level instead of being archived with their parent. Restoring the parent later does not file them back underneath: moving them was your choice, and restore leaves it alone.",
      "chapter": "archive_and_restore",
      "chapter_title": "Archiving a subject, and getting it back",
      "section": "Keeping the children",
      "link": "help_archive_and_restore.html#keeping-the-children"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-archived-panel",
      "text": "Deleting a subject archives it rather than erasing it, and this panel restores the whole deletion with its weights and its positions. It is hidden entirely when nothing is archived, which is usually why it cannot be found.",
      "chapter": "archive_and_restore",
      "chapter_title": "Archiving a subject, and getting it back",
      "section": "The Archived subjects panel",
      "link": "help_archive_and_restore.html#the-archived-subjects-panel"
    },
    {
      "page": "tree-editor",
      "anchor": "tree-archived-restore",
      "text": "Restore runs as soon as you press it, with no preview, and undoes the whole deletion in this row at once. Its message says if anything could not be brought back. A child you moved to the top level when deleting stays at the top level.",
      "chapter": "archive_and_restore",
      "chapter_title": "Archiving a subject, and getting it back",
      "section": "Restoring",
      "link": "help_archive_and_restore.html#restoring"
    }
  ],
  "session-setup": [
    {
      "page": "session-setup",
      "anchor": "session-add-source",
      "text": "Entries belong to a session, and a session is one sitting of practice questions, so the entry form will not open without one. The first time there is nothing in this list: + Add New beside the field is the way in.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Step 4. Start a session",
      "link": "help_the_first_hour.html#step-4-start-a-session"
    },
    {
      "page": "session-setup",
      "anchor": "session-date-encountered",
      "text": "This is when you sat the questions, not when you are typing them up, and it is the date every analytics screen and date filter keys on. Change it when you are logging a block from last week.",
      "chapter": "the_first_hour",
      "chapter_title": "Your first hour",
      "section": "Step 4. Start a session",
      "link": "help_the_first_hour.html#step-4-start-a-session"
    },
    {
      "page": "session-setup",
      "anchor": "session-questions-incorrect",
      "text": "This decides how many entry slots the next screen gives you, and the form counts \"Entry 3 of 12\" against it. If you miscounted, + Add Entries in the form's header asks for more.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "What this screen is",
      "link": "help_logging_a_mistake.html#what-this-screen-is"
    },
    {
      "page": "session-setup",
      "anchor": "session-card-continue",
      "text": "A session you left unfinished is not lost: reopening it takes you to its first unfinished entry rather than to the first one, so a half-written block is picked up where you stopped.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "What a draft is",
      "link": "help_logging_a_mistake.html#what-a-draft-is"
    },
    {
      "page": "session-setup",
      "anchor": "session-card-logged",
      "text": "Logged counts an entry once it is finished, not when its slot is first saved as a draft, so a block with a slot written for every mistake can still read 7/10. A session set up with 0 incorrect has nothing to log and reads Complete straight away.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "What Logged counts",
      "link": "help_logging_a_mistake.html#what-logged-counts"
    },
    {
      "page": "session-setup",
      "anchor": "session-card-review",
      "text": "Review opens the session in the ordinary entry form, not a read-only copy, so anything you change there is saved as usual. It starts at entry 1, where Continue starts at the first unfinished one.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Review opens the ordinary form",
      "link": "help_logging_a_mistake.html#review-opens-the-ordinary-form"
    },
    {
      "page": "session-setup",
      "anchor": "session-card-export-ids",
      "text": "Export IDs collects the Question ID / Reference you typed on each of this session's entries, so you can paste them into a question bank to redo them. An entry with none is skipped, and WIMI tells you how many were.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Export IDs",
      "link": "help_logging_a_mistake.html#export-ids"
    },
    {
      "page": "session-setup",
      "anchor": "session-edit-incorrect",
      "text": "Lowering this below the number of entries already logged does not hide the extra ones. WIMI asks you to tick that many, and Confirm Removal deletes them for good before the session is saved.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Changing a session's numbers",
      "link": "help_logging_a_mistake.html#changing-a-session-s-numbers"
    },
    {
      "page": "session-setup",
      "anchor": "session-card-delete",
      "text": "Delete removes the session and every entry in it, drafts included, and there is no undo. A note or image first added on one of those entries goes too, from every other entry that reuses it.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Deleting a session",
      "link": "help_logging_a_mistake.html#deleting-a-session"
    },
    {
      "page": "session-setup",
      "anchor": "session-duration",
      "text": "This starts filled in from Settings, Study Sessions, Default Work Round Duration, which is 60 minutes until you change it, not at No Limit. Leave it and the session starts with a round already running; pick No Limit for an untimed review.",
      "chapter": "the_session_timer",
      "chapter_title": "The session timer, rounds and breaks",
      "section": "The timer only exists if you asked for one",
      "link": "help_the_session_timer.html#the-timer-only-exists-if-you-asked-for-one"
    }
  ],
  "entry-form": [
    {
      "page": "entry-form",
      "anchor": "entry-form-reflection-editor",
      "text": "This field wants the mechanism of the miss, not the content you should have known. \"I knew this and read the stem too fast\" belongs here; the physiology belongs in the field below it.",
      "chapter": "the_premise",
      "chapter_title": "Why WIMI asks for a reason",
      "section": "Write the mechanism, not the content",
      "link": "help_the_premise.html#write-the-mechanism-not-the-content"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-tags-search-input",
      "text": "Error types are optional on purpose: a tag you clicked past records almost nothing, so an untagged entry with a clear written reason is worth more than a tagged one without. Tag when you already know which kind of mistake this was.",
      "chapter": "the_premise",
      "chapter_title": "Why WIMI asks for a reason",
      "section": "Why the tags are optional and the sentence is not",
      "link": "help_the_premise.html#why-the-tags-are-optional-and-the-sentence-is-not"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-tag-context",
      "text": "This records which of a shared subject's parents the entry rolls up through on the charts. Leave it alone and WIMI records the parent the pill is already showing you, so the mistake is counted once rather than under every parent at the same time.",
      "chapter": "parent_context",
      "chapter_title": "Choosing which parent an entry counts under",
      "section": "What WIMI records if you ignore it",
      "link": "help_parent_context.html#what-wimi-records-if-you-ignore-it"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-subject-rows",
      "text": "Primary is what the question tests and secondary is what it also touches. Only primary tags are counted on the charts, so a subject cannot climb them by being mentioned, and the entry browser finds an entry by either kind.",
      "chapter": "two_screens_one_subject",
      "chapter_title": "Why two screens can disagree about one subject",
      "section": "Where the two kinds of tag come from",
      "link": "help_two_screens_one_subject.html#where-the-two-kinds-of-tag-come-from"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-add-entries-button",
      "text": "+ Add Entries raises this session's Questions Incorrect by the number you give and reopens a finished session, and Logged on the session card counts against the new figure. Leaving the extra slots empty does not take it back; Edit on the session card lowers it.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Adding entries",
      "link": "help_logging_a_mistake.html#adding-entries"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-media-block",
      "text": "Pasting an image while the cursor is inside one of the written fields embeds it in your prose; the same keystroke anywhere else on the page makes a real attachment you can label and reuse. Both are legitimate and only the second is manageable afterwards.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Attaching an image",
      "link": "help_logging_a_mistake.html#attaching-an-image"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-media-attach-existing-button",
      "text": "+ Add existing lists only images whose own subjects include one of this entry's primary subjects: secondary subjects, parents and children do not count. For any other image, including one from another exam, use Browse Existing Images, which searches all your images by file name.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Reusing an image",
      "link": "help_logging_a_mistake.html#reusing-an-image"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-media-thumbnail-delete",
      "text": "Delete asks which you mean. Remove from Entry takes the image off this entry only and leaves it on every other entry using it. Delete Permanently removes it from every entry and from your library, and cannot be undone.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Removing an image",
      "link": "help_logging_a_mistake.html#removing-an-image"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-auto-save-indicator",
      "text": "WIMI writes the form to the database every thirty seconds while there is anything unsaved, and this indicator is the whole truth about it. A failed background save is silent, so if it reads \"Unsaved changes\" for a long while, press Save as Draft, which does report failures.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Autosave",
      "link": "help_logging_a_mistake.html#autosave"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-form",
      "text": "An entry missing any of these five is stored as a draft, and a draft still counts as a mistake on every analytics screen. Save as Draft does not force one and Save & Next does not clear one; they differ in what they check, not in what they store.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "What a draft is",
      "link": "help_logging_a_mistake.html#what-a-draft-is"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-save-next-button",
      "text": "This stays disabled until the five starred fields are filled and every attached image has a subject, and its label says which is holding it. The image rule holds back only this button: whether the entry is stored as a draft depends on the five fields alone.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "What holds Save & Next back",
      "link": "help_logging_a_mistake.html#what-holds-save-next-back"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-question-id-input",
      "text": "Type a reference you have used before in this exam and click away, and WIMI offers to copy the newest earlier entry's subjects and error types, and its correct answer and explanation where yours are empty. Your answer and reflection are never copied, and the match is exact: q15 is not Q15.",
      "chapter": "logging_a_mistake",
      "chapter_title": "Logging a mistake",
      "section": "Answering the same question twice",
      "link": "help_logging_a_mistake.html#answering-the-same-question-twice"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-notes-block",
      "text": "A note is for the thing that will still be true on a question you have not seen yet. Tag it with a subject and a later entry with that subject as a primary subject offers it back through + Add existing, which is the only subject-level view of your notes.",
      "chapter": "notes",
      "chapter_title": "Notes",
      "section": "Where a note turns up again",
      "link": "help_notes.html#where-a-note-turns-up-again"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-note-delete",
      "text": "On a note only this entry uses, Delete removes it for good after one question. On a note other entries share, you choose: Detach from this entry keeps it on them, Delete everywhere removes it from all. Deleting the entry a note was first written on deletes the note everywhere too.",
      "chapter": "notes",
      "chapter_title": "Notes",
      "section": "Clearing, editing and deleting",
      "link": "help_notes.html#clearing-editing-and-deleting"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-timer-pause-button",
      "text": "Leaving this page pauses the running round for you, and coming back to this session while WIMI is open resumes it, with the time away recorded as break time. So a round measures time spent here. A round you paused yourself stays paused when you come back.",
      "chapter": "the_session_timer",
      "chapter_title": "The session timer, rounds and breaks",
      "section": "Leaving the page pauses your round, and coming back resumes it",
      "link": "help_the_session_timer.html#leaving-the-page-pauses-your-round-and-coming-back-resumes-it"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-question-bank-button",
      "text": "This button puts a browser in the right half of WIMI's own window, so the question stays on screen while you write about it. Ctrl+B and View, Browser Pane do the same, and closing the pane keeps your page and your login rather than signing you out.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "Opening and closing it",
      "link": "help_question_bank_pane.html#opening-and-closing-it"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-question-bank-button",
      "text": "The named buttons in the pane's toolbar are your own question banks, one for every bank you have given a web address, most recently opened first. A bank gets its address in Settings, Question Banks, never at session setup.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "The shortcut buttons",
      "link": "help_question_bank_pane.html#the-shortcut-buttons"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-question-bank-button",
      "text": "A pop-up a site opens becomes a new tab in the pane, which is what single sign-on log-ins expect. The tab strip appears only once there are two tabs, and closing the last one closes the pane.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "Tabs",
      "link": "help_question_bank_pane.html#tabs"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-question-bank-button",
      "text": "The pane keeps its own logins, separate from your normal browser, so each question bank needs one sign-in here and then stays signed in across restarts. Those logins do not travel in a profile file.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "Logins survive restarts",
      "link": "help_question_bank_pane.html#logins-survive-restarts"
    },
    {
      "page": "entry-form",
      "anchor": "entry-form-question-bank-button",
      "text": "WIMI never reads the page in the pane. Nothing from a question or its explanation is copied into an entry, so what ends up in your entries is only what you typed.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "What the pane does not do",
      "link": "help_question_bank_pane.html#what-the-pane-does-not-do"
    },
    {
      "page": "entry-form",
      "anchor": "dictation-reflection-button",
      "text": "What you say is turned into text by a program on this computer, and the recording is deleted once it has been read; nothing is uploaded. The first press may offer a one-time download of about 190 MB, and only one of the two fields can record at a time.",
      "chapter": "dictation",
      "chapter_title": "Speaking instead of typing",
      "section": "It runs on this computer",
      "link": "help_dictation.html#it-runs-on-this-computer"
    }
  ],
  "entry-browser": [
    {
      "page": "entry-browser",
      "anchor": "browser-filter-subject",
      "text": "This page retrieves rather than counts, so filtering by a subject finds every entry that mentions it, including the ones where you only noted it as also tested. That is why a filter here can return eleven entries where a chart shows five.",
      "chapter": "two_screens_one_subject",
      "chapter_title": "Why two screens can disagree about one subject",
      "section": "So: eleven and five",
      "link": "help_two_screens_one_subject.html#so-eleven-and-five"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-drafts-toggle",
      "text": "An unfinished entry sits in this list beside the finished ones, and no setting hides it. You got the question wrong, so the mistake counts everywhere in WIMI except a weekly goal.",
      "chapter": "goals_and_drafts",
      "chapter_title": "Goals, and why drafts do not count toward them",
      "section": "Drafts count everywhere else",
      "link": "help_goals_and_drafts.html#drafts-count-everywhere-else"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-row-date",
      "text": "A card's date is the session's Date Encountered, when you sat the questions, not when you typed the entry. Click anywhere on a card to open the entry in full.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "What a card tells you",
      "link": "help_finding_an_entry.html#what-a-card-tells-you"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-search-input",
      "text": "Search is literal: what you type has to appear as a run of characters, with no fuzzy matching and no \"did you mean\". A bare word searches your reflection, your explanation, both answers and your subject names at once.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "The search box",
      "link": "help_finding_an_entry.html#the-search-box"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-search-help",
      "text": "A plain search does not look inside the notes you add with Add Note. Put notes: in front of a word to search them, or another prefix listed here to search one field only.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "Naming a field",
      "link": "help_finding_an_entry.html#naming-a-field"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-subject-apply",
      "text": "Each filter panel does nothing until you press its Apply button. Ticking boxes and closing the panel changes nothing, which is deliberate, because the subject tree is something you click around in before you have decided.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "The filters",
      "link": "help_finding_an_entry.html#the-filters"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-filter-tags",
      "text": "Ticking several error types finds entries carrying any one of them, not only entries carrying all of them, so a second tick widens the list rather than narrowing it.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "Tags",
      "link": "help_finding_an_entry.html#tags"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-filter-date",
      "text": "Dates here are the session's Date Encountered, when you sat the questions, not when you wrote the entry up. So Last 7 Days finds practice sat in those days, however late you logged it.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "Date",
      "link": "help_finding_an_entry.html#date"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-sort-trigger",
      "text": "The list opens in the order set under Settings, Entry Browser, which is newest first until you change it. Date order is the session's Date Encountered, and an entry with no difficulty sorts last in both difficulty orders.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "Sort",
      "link": "help_finding_an_entry.html#sort"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-subject-children-toggle",
      "text": "This widens a subject filter to everything beneath that subject, at any depth, and it is off by default. That is why filtering on a high-level subject you never tag directly can come back empty.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "What a subject filter actually returns",
      "link": "help_finding_an_entry.html#what-a-subject-filter-actually-returns"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-stats-summary",
      "text": "The count in the page header is the whole exam and does not move when you filter; the line under the list is what your filters match. A big number above a small one is the two answering different questions.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "The two counts on the page, and why they differ",
      "link": "help_finding_an_entry.html#the-two-counts-on-the-page-and-why-they-differ"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-header-export-ids",
      "text": "Export IDs puts a checkbox on every card so you can copy question references into a question bank's search. An entry with no question reference is skipped, and the export box says how many were.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "Collecting question numbers to redo",
      "link": "help_finding_an_entry.html#collecting-question-numbers-to-redo"
    },
    {
      "page": "entry-browser",
      "anchor": "browser-export-all-visible",
      "text": "Export All Visible takes only the entries loaded so far, not every entry your filters match. Press Load More until the list is complete before exporting a long one.",
      "chapter": "finding_an_entry",
      "chapter_title": "Finding an entry again",
      "section": "All Visible means loaded",
      "link": "help_finding_an_entry.html#all-visible-means-loaded"
    }
  ],
  "analytics": [
    {
      "page": "analytics",
      "anchor": "analytics-by-subject",
      "text": "Every total on this page counts only the subject you named as primary, so a subject cannot inflate its own figure through tags that merely mention it. The entry browser is the surface that includes every tag.",
      "chapter": "two_screens_one_subject",
      "chapter_title": "Why two screens can disagree about one subject",
      "section": "Why counting uses only the primary tag",
      "link": "help_two_screens_one_subject.html#why-counting-uses-only-the-primary-tag"
    },
    {
      "page": "analytics",
      "anchor": "analytics-sunburst-centre",
      "text": "The centre is a count of your entries and each arc counts the entries rolling up through one branch, so the arcs add up to more than the centre whenever a subject sits under several parents. Eleven entries can correctly draw arcs of 5, 6 and 3.",
      "chapter": "two_screens_one_subject",
      "chapter_title": "Why two screens can disagree about one subject",
      "section": "The sunburst's centre and its rings do not match either",
      "link": "help_two_screens_one_subject.html#the-sunburst-s-centre-and-its-rings-do-not-match-either"
    },
    {
      "page": "analytics",
      "anchor": "analytics-weekly-goal",
      "text": "A goal counts entries you logged between Monday and Sunday, while This week counts practice you sat in the last seven days. Catching up on an old block moves one and not the other, and both are right.",
      "chapter": "goals_and_drafts",
      "chapter_title": "Goals, and why drafts do not count toward them",
      "section": "The goal's week is not the dashboard's week",
      "link": "help_goals_and_drafts.html#the-goal-s-week-is-not-the-dashboard-s-week"
    },
    {
      "page": "analytics",
      "anchor": "analytics-exam-filter",
      "text": "Every card below this selector is about one exam, and two screens on different exams agree about nothing. It is the first thing to check when a figure here surprises you.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "The exam selector scopes everything",
      "link": "help_reading_the_analytics.html#the-exam-selector-scopes-everything"
    },
    {
      "page": "analytics",
      "anchor": "analytics-settings-btn",
      "text": "If a card you expect is missing, look in Settings, which this opens, before looking for a bug. Cards can be hidden for one exam, for every exam, or by Analytics Detail Level, whose Summary keeps only the four counts at the top, the sunburst and the mistake-type chart.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "When a card is missing",
      "link": "help_reading_the_analytics.html#when-a-card-is-missing"
    },
    {
      "page": "analytics",
      "anchor": "analytics-stat-avg-difficulty",
      "text": "This is the mean of the difficulty ratings you gave, over the entries where you gave one, and every one of those is a question you got wrong. It describes your mistakes rather than the exam.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Overview: the four cards at the top",
      "link": "help_reading_the_analytics.html#overview-the-four-cards-at-the-top"
    },
    {
      "page": "analytics",
      "anchor": "analytics-stat-this-week",
      "text": "This counts entries whose session is dated in the last seven days, today included, by Date Encountered rather than the day you typed them. It is a rolling week, not Monday to Sunday, and the number beside it is the change against the seven days before.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Overview: the four cards at the top",
      "link": "help_reading_the_analytics.html#overview-the-four-cards-at-the-top"
    },
    {
      "page": "analytics",
      "anchor": "analytics-by-mistake-type",
      "text": "This is a picture of your tagging rather than of your mistakes, because error types are optional and one entry can carry several. If it looks thin, that is a fact about how much you tagged.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "By Mistake Type: the error-type donut",
      "link": "help_reading_the_analytics.html#by-mistake-type-the-error-type-donut"
    },
    {
      "page": "analytics",
      "anchor": "analytics-cross-dim-legend",
      "text": "Colours run from none to the most mistakes in any cell on screen, so the reddest cell is the worst one here, not a fixed amount, and drilling down recolours everything. A grey cell, marked Insufficient data in this key, has no entries at all; no figure is being held back.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "The colours",
      "link": "help_reading_the_analytics.html#the-colours"
    },
    {
      "page": "analytics",
      "anchor": "analytics-current-streak",
      "text": "A streak day is a day with at least one entry in this exam, dated by its session's Date Encountered, not by when you typed it. Writing up last week's block can lengthen a streak, and an entry typed today into a session dated yesterday does not count for today.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "The streak cards",
      "link": "help_reading_the_analytics.html#the-streak-cards"
    },
    {
      "page": "analytics",
      "anchor": "analytics-interaction-effects",
      "text": "These compare only the exam's first two dimensions, whichever pair the heatmap shows. Expected is what a pairing would hold if the two axes were unrelated, and the severity word grades the gap as a percentage alone, so a pairing with one or two entries can read high.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Interaction effects",
      "link": "help_reading_the_analytics.html#interaction-effects"
    },
    {
      "page": "analytics",
      "anchor": "analytics-source-trend",
      "text": "Trend compares how many entries you logged from a bank per month, recently against earlier, over about six months, by the day you typed them. It is a count, not a rate: practising less from a bank reads as Better just as surely as missing less, and practising more reads as Worse.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Question banks compared",
      "link": "help_reading_the_analytics.html#question-banks-compared"
    },
    {
      "page": "analytics",
      "anchor": "analytics-weight-quadrant",
      "text": "Reduce Focus is not praise. It lists subjects light on the exam, under 10% at the middle of their band, where your share of mistakes is over 1.3 times that middle and outside the band: subjects you keep getting wrong. It ranks them below heavier subjects; it does not say you have learned them.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Quadrant Analysis",
      "link": "help_reading_the_analytics.html#quadrant-analysis"
    },
    {
      "page": "analytics",
      "anchor": "analytics-weight-recommendations",
      "text": "Consider reducing time is about exam weight, not about how long you study, which WIMI never sees. It is said of a light subject you get wrong far more often than its weight predicts, and means heavier subjects come first, not that this one is done.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Top Recommendations",
      "link": "help_reading_the_analytics.html#top-recommendations"
    },
    {
      "page": "analytics",
      "anchor": "analytics-weight-sources",
      "text": "These counts say where your subjects' weights came from, and nothing on this page uses them: an estimated or derived weight is compared exactly like an official one. A subject with no recorded source counts as derived.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Weight sources",
      "link": "help_reading_the_analytics.html#weight-sources"
    },
    {
      "page": "analytics",
      "anchor": "analytics-stat-total-entries",
      "text": "Every card on this page except Weekly Goal includes your unfinished drafts, because the mistake happened whether or not the reflection is finished. The weekly goal is the one surface in WIMI that leaves them out, and its card says how many are left.",
      "chapter": "reading_the_analytics",
      "chapter_title": "Reading the analytics dashboard",
      "section": "Drafts are in all of it",
      "link": "help_reading_the_analytics.html#drafts-are-in-all-of-it"
    }
  ],
  "calendar": [
    {
      "page": "calendar",
      "anchor": "cal-grid",
      "text": "Every session you have logged and every one you have planned, on one grid. Past sessions are solid, planned ones are dashed and say Planned. Arrow keys move between days; Enter opens a day.",
      "chapter": "planning_sessions",
      "chapter_title": "Planning sessions on the calendar",
      "section": "Getting there",
      "link": "help_planning_sessions.html#getting-there"
    },
    {
      "page": "calendar",
      "anchor": "cal-plan",
      "text": "Plan a session for a day you choose. The exam, the question bank, a start time, a duration and how many questions are all optional; a weekly repeat makes a series.",
      "chapter": "planning_sessions",
      "chapter_title": "Planning sessions on the calendar",
      "section": "Reading the grid",
      "link": "help_planning_sessions.html#reading-the-grid"
    },
    {
      "page": "calendar",
      "anchor": "cal-legend",
      "text": "One colour per exam. Give an exam its own colour in its wizard, or let the calendar choose one of four from your theme. Plans with no exam are grey.",
      "chapter": "planning_sessions",
      "chapter_title": "Planning sessions on the calendar",
      "section": "When a day passes",
      "link": "help_planning_sessions.html#when-a-day-passes"
    }
  ],
  "settings": [
    {
      "page": "settings",
      "anchor": "settings-question-banks",
      "text": "This panel is the only place a question bank's web address lives. The Add Question Source dialog at session setup never asks for one, so a source you made there has no address until you type it here.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "Giving a question bank an address",
      "link": "help_question_bank_pane.html#giving-a-question-bank-an-address"
    },
    {
      "page": "settings",
      "anchor": "settings-qbank-desktop",
      "text": "Desktop site makes the pane tell this bank's website it is an ordinary desktop browser, which some sign-in pages insist on, so leave it on unless the site misbehaves. Like the address beside it, it is saved the moment you change it, not by Save, and it applies to this computer only.",
      "chapter": "question_bank_pane",
      "chapter_title": "Your question bank beside the form",
      "section": "Desktop site",
      "link": "help_question_bank_pane.html#desktop-site"
    },
    {
      "page": "settings",
      "anchor": "settings-sync-enable",
      "text": "Ticking this links the profile to a folder there and then, without Save, and copies nothing into it yet. Nothing syncs by itself afterwards: your profile reaches the folder only when you press Send this device's copy, and the link belongs to this computer, not to the profile.",
      "chapter": "folder_sync",
      "chapter_title": "Keeping one profile on two computers",
      "section": "Setting it up",
      "link": "help_folder_sync.html#setting-it-up"
    },
    {
      "page": "settings",
      "anchor": "settings-save",
      "text": "Nothing you change here reaches the rest of WIMI until you press Save. The strip that appears is literally true: switch the theme and this page restyles itself while every other page stays as it was.",
      "chapter": "settings",
      "chapter_title": "Settings, and what each one changes",
      "section": "Nothing changes until you press Save",
      "link": "help_settings.html#nothing-changes-until-you-press-save"
    },
    {
      "page": "settings",
      "anchor": "settings-reset-defaults",
      "text": "This is not an undo. It writes the shipped default over everything the page's Save covers, on every panel, not only the one you are looking at. Controls that save themselves are left alone: per-exam analytics, each bank's address and Desktop site switch, Anki, and add-ons. So is your data.",
      "chapter": "settings",
      "chapter_title": "Settings, and what each one changes",
      "section": "Reset what Save covers is not an undo",
      "link": "help_settings.html#reset-what-save-covers-is-not-an-undo"
    },
    {
      "page": "settings",
      "anchor": "settings-appearance-primary-color-picker",
      "text": "Choose the theme first and the colour second, because picking a theme overwrites both of your colours with its own pair. Your colour then wins over the theme on every page, until you change theme again.",
      "chapter": "settings",
      "chapter_title": "Settings, and what each one changes",
      "section": "Your two colours",
      "link": "help_settings.html#your-two-colours"
    },
    {
      "page": "settings",
      "anchor": "settings-analytics-save-exam-config",
      "text": "These per-exam choices have their own Save button and are not covered by the page's Save. They are stored per exam, so one exam can have a busy dashboard and another a spare one.",
      "chapter": "settings",
      "chapter_title": "Settings, and what each one changes",
      "section": "Dashboard and Analytics",
      "link": "help_settings.html#dashboard-and-analytics"
    },
    {
      "page": "settings",
      "anchor": "settings-mcp-server-enabled",
      "text": "This switch and the port belong to this computer, not to your profile, so a profile exported or synced to another computer does not turn the server on there. Ticking it starts the server when you press Save, and WIMI starts it again each time it opens while the box stays ticked.",
      "chapter": "settings",
      "chapter_title": "Settings, and what each one changes",
      "section": "MCP Server",
      "link": "help_settings.html#mcp-server"
    },
    {
      "page": "settings",
      "anchor": "settings-profile-export",
      "text": "This is the only backup WIMI has. Nothing runs on a schedule and there is no Back up now anywhere, so a copy of your work exists exactly as often as you press this. Put a date in the filename and keep several.",
      "chapter": "where_your_work_lives",
      "chapter_title": "Where your work lives, and how to keep it",
      "section": "The safe copy is Export profile",
      "link": "help_where_your_work_lives.html#the-safe-copy-is-export-profile"
    },
    {
      "page": "settings",
      "anchor": "settings-addons-install",
      "text": "A plugin installed from a zip runs straight away. Nothing asks you to approve what it can do first, and a plugin already installed under the same name is replaced without asking. It works with the same access to your data that WIMI has, so export your profile before you install one.",
      "chapter": "plugins",
      "chapter_title": "Plugins",
      "section": "Installing one",
      "link": "help_plugins.html#installing-one"
    }
  ]
};
