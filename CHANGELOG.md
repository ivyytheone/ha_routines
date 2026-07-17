# Changelog

All notable changes to HA Routines are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.11] - 2026-07-17

### Fixed

- HACS structure compliance: set `content_in_root` in `hacs.json` so the integration files at the repository root are accepted

## [0.2.10] - 2026-07-17

### Changed

- Repo prepared for public HACS install: `.gitignore`, removed tracked `__pycache__`, `hacs.json` without `zip_release`, correct GitHub documentation URLs

## [0.2.9] - 2026-07-17

### Changed

- Snooze works from **pending** (before the reminder) and can be pressed again while already snoozed to extend the delay
- Invalid button/service transitions raise a clearer Home Assistant error instead of a raw `ValueError`

## [0.2.8] - 2026-07-17

### Changed

- Integration page add button label is now **Add routine** / **Lägg till rutin** instead of the generic "Add service"

## [0.2.7] - 2026-07-17

### Added

- State-aware icons via `icons.json` (status, done-today, buttons)
- Friendly status labels (EN/SV) instead of raw enum values like `completed`
- Brand assets under `brand/` (`icon.png`, `logo.png`) for the integration list and device page
- Lovelace examples (Mushroom / tile) in README

### Changed

- Status sensor uses `SensorDeviceClass.ENUM` so Home Assistant and custom cards can treat states correctly
- Entity icons no longer inherit one shared MDI from the routine subentry

## [0.2.6] - 2026-07-17

### Added

- Full reconfigure wizard for existing routines (name, schedule/times, reminders, notify target) with current values prefilled; next reminder is recalculated after save

## [0.2.5] - 2026-07-17

### Fixed

- iOS actionable buttons: always send via `notify.mobile_app_*` with short action keys (`HAR_TAGIT` / `HAR_SNOOZE`), `action_data.routine_id`, and `push.sound` (no Android-only fields that can break iOS parsing)

## [0.2.4] - 2026-07-17

### Added

- Actionable reminder buttons: **Tagit** and **Snooze** (with emoji labels)
- Feedback notification after Tagit ("Jag har nu tagit ...")
- Multi-dose days: completing 08:00 still schedules 12:00 the same day
- Random snooze between 4 and 10 minutes

### Changed

- Complete button renamed to **Routine done**
- Reminder notifications use the legacy mobile_app notify path so iOS/Android action buttons appear

## [0.2.3] - 2026-07-17

### Fixed

- Notifications to Companion `notify.*` entities no longer call a non-existent `notify.<name>` service; they resolve the legacy mobile_app notify service (action buttons included)
- Failed notifies no longer flip status to `reminder_sent`; the routine stays pending and retries
- Routine entities are linked with `config_subentry_id` so **Delete** on a routine removes its devices/entities cleanly

## [0.2.2] - 2026-07-17

### Changed

- Notify target in the routine wizard is now an entity picker listing Companion `notify.*` devices instead of a free-text field

## [0.2.1] - 2026-07-17

### Fixed

- Day-based routines now fire from **schedule times** (wizard step 2), not only the separate reminder-times field that often stayed at `08:00`
- Reminder step prefills times from the schedule step so the two fields no longer diverge silently

## [0.2.0] - 2026-07-17

### Added

- Full state machine actions: complete, snooze, skip today, missed, reset, trigger reminder, next cycle
- Completion/missed/skipped history with configurable trim (default 365)
- Streak tracking (current and longest)
- DST-safe async scheduler with restart reconciliation
- Status sensor, completed-today binary sensor, complete/snooze/skip buttons per routine
- Actionable mobile notifications (Complete / Snooze / Skip Today)
- Services: `ha_routines.complete`, `snooze`, `skip_today`, `reset`, `trigger_reminder`
- Events: `routine_completed`, `routine_skipped`, `routine_snoozed`, `routine_reminder_sent`
- Schedule helpers for daily, weekly, monthly, interval hours, and days-after-completion
- Unit tests under `tests/test_ha_routines/` for state machine, storage, scheduler, DST, and restart roll-over

### Changed

- Integration version bumped from 0.1.0 skeleton to usable runtime

## [0.1.0] - 2026-07-17

### Added

- Initial project skeleton under `custom_components/ha_routines`
- Hub config entry with Config Subentries for per-routine setup wizard
- Typed models, state machine definitions, and Store-based runtime storage
- Base `RoutinesCoordinator` with subentry sync and persist stubs
- Platform stubs for sensor, binary_sensor, and button entities
- English translations for hub and routine subentry config flows
- Ruff and mypy quality configuration
- `sync-ha_routines.ps1` for local Home Assistant deployment

[0.2.6]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.6
[0.2.5]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.5
[0.2.4]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.4
[0.2.3]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.3
[0.2.2]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.2
[0.2.1]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.1
[0.2.0]: https://github.com/home-assistant/ha_routines/releases/tag/v0.2.0
[0.1.0]: https://github.com/home-assistant/ha_routines/releases/tag/v0.1.0
