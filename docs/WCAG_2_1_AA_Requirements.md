# WCAG 2.1 Level AA Requirements (Checklist)

WCAG 2.1 Level AA compliance means:
- All Level A success criteria are met, AND
- All Level AA success criteria are met.

This file lists the WCAG 2.1 success criteria required for Level AA, organized by principle.

## 1. Perceivable

### 1.1 Text Alternatives
- 1.1.1 (A) Non-text Content: Provide text alternatives for non-text content.

### 1.2 Time-based Media
- 1.2.1 (A) Audio-only and Video-only (Prerecorded): Provide alternatives.
- 1.2.2 (A) Captions (Prerecorded): Provide captions for prerecorded video with audio.
- 1.2.3 (A) Audio Description or Media Alternative (Prerecorded): Provide audio description or a full text alternative.
- 1.2.4 (AA) Captions (Live): Provide captions for live audio in synchronized media.
- 1.2.5 (AA) Audio Description (Prerecorded): Provide audio description for prerecorded video.

### 1.3 Adaptable
- 1.3.1 (A) Info and Relationships: Semantics/structure programmatically determinable.
- 1.3.2 (A) Meaningful Sequence: Correct reading/interaction order.
- 1.3.3 (A) Sensory Characteristics: Don’t rely only on shape/size/visual location/sound.
- 1.3.4 (AA) Orientation: Content not restricted to a single orientation.
- 1.3.5 (AA) Identify Input Purpose: Autocomplete semantics for common user data.

### 1.4 Distinguishable
- 1.4.1 (A) Use of Color: Color not the only means of conveying information.
- 1.4.2 (A) Audio Control: Provide a way to stop/pause/adjust audio that plays automatically.
- 1.4.3 (AA) Contrast (Minimum): Text contrast at least 4.5:1 (normal text) / 3:1 (large text).
- 1.4.4 (AA) Resize Text: Text can be resized up to 200% without loss.
- 1.4.5 (AA) Images of Text: Avoid images of text (with limited exceptions).
- 1.4.10 (AA) Reflow: Content reflows without 2D scrolling at 320 CSS px width.
- 1.4.11 (AA) Non-text Contrast: UI components/graphics needed for understanding meet contrast requirements.
- 1.4.12 (AA) Text Spacing: No loss of content/functionality when users adjust spacing.
- 1.4.13 (AA) Content on Hover or Focus: Dismissible, hoverable, persistent.

## 2. Operable

### 2.1 Keyboard Accessible
- 2.1.1 (A) Keyboard: All functionality via keyboard.
- 2.1.2 (A) No Keyboard Trap: Focus can be moved away.
- 2.1.4 (A) Character Key Shortcuts: Provide a way to turn off/remap single-key shortcuts.

### 2.2 Enough Time
- 2.2.1 (A) Timing Adjustable: Users can extend/turn off time limits (exceptions apply).
- 2.2.2 (A) Pause, Stop, Hide: Users can pause/stop moving/blinking/auto-updating content.

### 2.3 Seizures and Physical Reactions
- 2.3.1 (A) Three Flashes or Below Threshold: Avoid flashing above thresholds.

### 2.4 Navigable
- 2.4.1 (A) Bypass Blocks: Provide a way to skip repeated content.
- 2.4.2 (A) Page Titled: Pages have descriptive titles.
- 2.4.3 (A) Focus Order: Focus moves in a meaningful order.
- 2.4.4 (A) Link Purpose (In Context): Link purpose clear from link text/context.
- 2.4.5 (AA) Multiple Ways: More than one way to find pages (exceptions apply).
- 2.4.6 (AA) Headings and Labels: Describe topic/purpose.
- 2.4.7 (AA) Focus Visible: Keyboard focus indicator is visible.

### 2.5 Input Modalities
- 2.5.1 (A) Pointer Gestures: Multi-point/path gestures have simple alternatives.
- 2.5.2 (A) Pointer Cancellation: Down-event doesn’t trigger irreversible actions.
- 2.5.3 (A) Label in Name: Accessible name contains visible label text.
- 2.5.4 (A) Motion Actuation: Motion-based actions have alternatives.

## 3. Understandable

### 3.1 Readable
- 3.1.1 (A) Language of Page: Default language programmatically set.
- 3.1.2 (AA) Language of Parts: Language changes programmatically indicated.

### 3.2 Predictable
- 3.2.1 (A) On Focus: Focus doesn’t trigger unexpected context changes.
- 3.2.2 (A) On Input: Input doesn’t trigger unexpected context changes.
- 3.2.3 (AA) Consistent Navigation: Repeated navigation is consistent.
- 3.2.4 (AA) Consistent Identification: Components identified consistently.

### 3.3 Input Assistance
- 3.3.1 (A) Error Identification: Errors are identified.
- 3.3.2 (A) Labels or Instructions: Provide labels/instructions.
- 3.3.3 (AA) Error Suggestion: Suggest corrections when possible.
- 3.3.4 (AA) Error Prevention (Legal, Financial, Data): Prevent/confirm/review for critical submissions.

## 4. Robust

### 4.1 Compatible
- 4.1.1 (A) Parsing: Markup is well-formed enough for assistive tech.
- 4.1.2 (A) Name, Role, Value: UI components expose accessible name/role/state/value.
- 4.1.3 (AA) Status Messages: Status updates announced without moving focus.

## Notes
- This is a practical checklist; interpretation still requires testing with assistive technologies.
- Automated tools (like axe) cover only a subset of these requirements; manual verification is required.
