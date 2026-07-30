# Portrait Status Strip Design

Status: approved by the user on 2026-07-21.

The portrait dashboard replaces the bottom completed-task summary with a compact
status strip. It has at most four left-to-right entries: active project
progress, unread completed projects, then failed projects. The strip has a
single top rule and contains no task title or completion summary.

An active project shows `current/total` only when its current turn has a
structured Codex `update_plan` call. `current` is the one-based first
`in_progress` plan item and `total` is the number of plan items. An active
project without an update plan displays the reusable running bitmap symbol, so
the display never invents a progress fraction.

Completed and failed projects display a reusable checkmark or cross bitmap
only when their thread ID is present in Codex Desktop's local unread-thread
list. Stopped and acknowledged projects have no bottom-strip entry.
The checkmark, cross, and running symbols are fixed 7x7 monochrome bitmap
patterns shared by every render; they do not depend on a Unicode font.

Only the 212x104 portrait layout changes. Its tasks region remains above the
status-strip rule. Landscape layouts, task titles, and quota rendering are not
changed.
