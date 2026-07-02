# WIMI — Prioritized Task List

Transcribed from handwritten notes · Session: March 11, 2026 · **18 tasks identified across 4 pages**
**Progress: 11 of 18 completed (61%)**

---

## Priority Legend

- 🔴 **CRITICAL** — Bugs actively breaking core functionality
- 🟠 **HIGH** — Important bugs & core UX fixes
- 🔵 **MEDIUM** — Features & design decisions
- 🟢 **LOW** — Future enhancements

---

## Task Table

| # | Priority | Category | Task | Description | Source | Phase | Status |
|---|----------|----------|------|-------------|--------|-------|--------|
| 1 | 🔴 CRITICAL | Bug Fix | Edit Entry Image Bug | Browse Entries → Select Entry w/ existing images → Select edit entry → Select Notes & Media section → Images attached to entry are not viewable. Images should display in the editing view. | Image 3 | Current | ✅ Done |
| 2 | 🔴 CRITICAL | Bug Fix | Exam Countdown Off By One Day | Exam countdown timer is displaying 1 day off. Likely a timezone or date calculation boundary issue. | Image 3 | Current | ✅ Done |
| 3 | 🟠 HIGH | Bug Fix | Session Edit Modal — Flesh Out | Session edit modal needs to be fully implemented. Modal is incomplete and requires full build-out of fields and save logic. | Image 1 | Phase 7 | ✅ Done |
| 4 | 🟠 HIGH | Bug Fix | Session Edit Modal — Source Editing | Edit session modal should include source editing capability. Users need to modify the source associated with a session entry. | Image 4 | Phase 7 | ✅ Done |
| 5 | 🟠 HIGH | Bug Fix | Delete Exam After Suspending | Users should be able to delete an exam after it has been suspended. Current flow does not permit block deletion of suspended exams. | Image 3 | Current | ✅ Done |
| 7 | 🟠 HIGH | UX Fix | Subject Select → Auto-Focus Text Field | After selecting or deselecting a subject, the cursor should automatically be focused on the text/entry field to improve keyboard-driven workflow. | Image 4 | Current | ✅ Done |
| 8 | 🔵 MEDIUM | Feature | Pomodoro Timer — Complete Sooner Than Expected | Add ability to complete a Pomodoro timer session earlier than the scheduled end time. Allow manual early completion with session logging. | Image 3 | Phase 8 | ✅ Done |
| 9 | 🔵 MEDIUM | Feature | Pomodoro Timer — Hotkey for Pause/Start/Complete | Implement a keyboard hotkey to pause and start the Pomodoro timer. Improve accessibility and keyboard-first workflow. | Image 4 | Phase 8 | ✅ Done |
| 10 | 🔵 MEDIUM | Bug Fix | Pomodoro Timer — Auto-Start in Imported Sessions | Pomodoro timer starts automatically in imported sessions, which should not occur. Review and add user control or config toggle. | Image 4 | Phase 8 | ✅ Done |
| 11 | 🔵 MEDIUM | UX Fix | Pomodoro Timer Button — Full Button Click Area | Users should be able to click the entire button area to interact with the Pomodoro timer, not just the icon/symbol. Improve hit target. | Image 4 | Phase 8 | ✅ Done |
| 12 | 🔵 MEDIUM | Feature | Manage Previous Pomodoro Timed Study Sessions | Add UI to manage, review, and edit previously completed Pomodoro timed study sessions. | Image 3 | Phase 8 | ✅ Done |
| 13 | 🔵 MEDIUM | Design Decision | Reflection Box Placement — Before or After Mistake Categorization? | Decide whether the reflection box should appear before or after mistake categorization in the entry flow. Consider metacognitive research for optimal placement. | Image 4 | Phase 7 | Open |
| 14 | 🔵 MEDIUM | Feature | Verify Note & Image Suggestion Feature | Verify the Note and image suggestion functionality is working correctly end-to-end. Validate suggestions are relevant and accurate. | Image 4 | Phase 9 | Open |
| 15 | 🟢 LOW | Feature | Import Session Profile Management | Allow for users to edit already created import profiles. | Image 2 | Future | Open |
| 16 | 🟢 LOW | Feature | Add Image Column to Entry — Source for Image Entry | Add a column in the entry view that shows image data; allow users to divide/assign a source for each image attached to an entry. | Image 2 | Future | Open |
| 17 | 🟢 LOW | Feature | Track Correct Questions | With the ability to import sessions enmasse, users are able to track correct questions as well. Let's discuss implementation of this. | Image 2 | Future | Open |
| 18 | 🟢 LOW | Bug Fix | Heavily Nested Subject's Psuedonym display | As users try to search with psuedonyms in Section B of the entry form, subjects that are heavily nested do not have the pseudonym displayed result box. Have the pseudonym display below the subject name and above the hierarchical tree map of the subject| Image 2 | Future | Open |

---

## Ranking Methodology

Tasks are ranked by:
1. **Severity of user impact** — bugs that silently corrupt data (image cancel bug) or misrepresent critical info (countdown) rank highest
2. **Dependency on other work** — modal completions unlock downstream features
3. **Development phase alignment** — items in the current active phase are prioritized over future-phase features
4. **Effort-to-value ratio** — quick UX wins like cursor focus rank above complex architectural features
