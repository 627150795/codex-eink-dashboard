# Event-Driven E-Ink Refresh Design

Status: approved by the user on 2026-07-22.

## Goal

When the visible Codex dashboard state changes, begin a screen update as soon
as the local Codex data is written instead of waiting for the next 30/60-second
poll. A visible state is limited to task start, plan-step progress, completion,
failure, unread status, and quota values.

The screen continues to use the existing full-frame BLE protocol. It does not
attempt unsupported partial panel refreshes or firmware changes.

## Event sources and scheduling

The background service watches the local Codex session tree, session index,
and unread-thread state file. The thread-state and activity databases are read
during collection but are not watched, because the local quota reader writes
both databases. A
change to any watched source signals one pending render. Events are coalesced
for the configured short quiet period so one Codex update that writes several
files creates at most one frame attempt.

After the quiet period, the service collects the latest view and compares its
frame hash with the last successful frame. An unchanged frame performs no BLE
scan, connection, or write. A changed frame uses the existing serialized BLE
upload path. Events arriving while an upload is in progress remain pending and
are evaluated immediately after that upload completes.

The existing 30-second active and 60-second idle checks remain as a fallback
for missed file-system notifications and for quota changes that have no local
file event.

## Task naming

Each displayed task uses only its existing Codex sidebar title: the current
thread title from Codex local metadata. The service must not synthesize a name
from the user prompt, working-directory name, or thread ID. If Codex has not
yet supplied a title, the fixed label `未命名任务` is shown until it does.

Subagent threads remain excluded.

## Verification

Tests cover title selection without generated English fallbacks, coalescing of
bursty watcher events, prompt handling of an event while idle, preservation of
an event received during an upload, and the unchanged-frame no-BLE path. A
manual background-service check records the time from a local state-file
change to the `uploaded` log entry.
