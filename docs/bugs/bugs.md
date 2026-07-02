# Bug Report: UI Overflow in Subject Hierarchy

## Description
When a subject has a long hierarchical path (e.g., `Male & Transgender Reproductive System > Neoplasms > penile malignant neoplasms > Carcinoma of the penis`), the text container does not expand to accommodate the full length. Consequently, the alias match text (e.g., `(matched: Penile cancer)`) is pushed outside the visible container and becomes invisible to the user.

## Steps to Reproduce
1. Navigate to the sidebar or navigation menu containing subject hierarchies.
2. Locate a subject with a deep hierarchy (4+ levels).
3. Observe the text alignment.
4. Note that the alias match is cut off or pushed off-screen.

## Expected Behavior
The container should either expand horizontally to fit the text or truncate the hierarchy with an ellipsis (`...`) while keeping the alias match visible. The alias match should always be visible within the UI bounds.

## Actual Behavior
The container remains a fixed width. As the hierarchy text grows, it overflows the container, pushing the alias match `(matched: Penile cancer)` off the right edge of the screen, making it impossible to see.

## Severity
Medium (Usability Issue)

# Bug Report: Question Review Timer does not stop when user selects the complete review button

## Description
When the user gets to the last question to review and selects the 'Complete Review' button, the study timer still runs.

## Steps to Reproduce
1. Create a review session with a study timer.
2. Go to the last question and select the 'Complete Review' button.
3. Return to review questions, timer is still running from the previous study session. 

## Expected behavior
The study session that is running when the user selects the 'Complete Review' button should be stopped and marked as complete.

## Actual Behavior
The study session timer that was previously running prior to selecting the 'Complete Review' button is still running.

## Severity
Medium
