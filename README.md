# HA Routines

Recurring routines for Home Assistant without helpers or YAML automations. Each routine is configured through a UI wizard and exposes standard entities for dashboards (Mushroom, tile, button, entity cards).

This project is built primarily for personal use. It is still straightforward to configure for your own routines, phones, and dashboards. If something breaks or is unclear, open a GitHub issue. You can also reach me at jbc@ivyydev.se or https://ivyydev.se/.

## Quick Start (HACS)

1. In Home Assistant, open **HACS**.
2. Open the menu (three dots) → **Custom repositories**.
3. Add:
   - Repository: `https://github.com/ivyytheone/ha_routines`
   - Category: **Integration**
4. Find **HA Routines** in HACS and install it.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration** and search for **HA Routines**.
7. Complete the hub setup, then click **Add routine** and walk through the wizard (name, doses/schedule, reminders).

No YAML configuration is required.

### Manual install (without HACS)

Copy this repository into `/config/custom_components/ha_routines` (integration files are at the repo root), restart Home Assistant, then add the integration as above.

## How It Works

```text
Hub config entry (ha_routines)
  -> RoutinesCoordinator loads Store (runtime state, history)
  -> Each routine is a config subentry (static schedule/reminder config)
  -> RoutineScheduler fires reminders (DST-safe, restart-aware)
  -> Platforms expose sensor, binary_sensor, and button entities per routine
  -> Optional actionable notifications via configured notify service
```

Runtime state (completion, snooze, streaks, missed counts) lives in Home Assistant storage via `Store()`. Routine configuration lives in each subentry's `data` field.

## Run Modes

### Local dev reload (this repo)

```powershell
.\sync-ha_routines.ps1
```

This verifies the integration files and restarts the Docker container. Files are edited in-place under `custom_components/ha_routines`.

### Production / real Home Assistant

Preferred: install via HACS (see Quick Start).

Manual copy also works: place the integration files under `/config/custom_components/ha_routines`, restart, then add the integration and recreate routines in the wizard. Runtime history does not migrate unless you also copy `.storage/ha_routines_data` and matching config entries.

Dev Docker and production are separate installs. Syncing this repo does not push to your real HA unless you install or copy the files yourself.

### Quality checks

From the workspace root:

```powershell
python -m compileall custom_components/ha_routines
python -m ruff check custom_components/ha_routines --config custom_components/ha_routines/quality/pyproject.toml
python -m mypy --config-file custom_components/ha_routines/quality/pyproject.toml custom_components/ha_routines
python -m pytest tests/test_ha_routines -q --import-mode=importlib
```

## Entities per routine

| Entity | Purpose |
|--------|---------|
| `sensor.*_status` | Current state (`pending`, `partial`, `completed`, …) |
| `sensor.*_dose_progress` | Dose progress today (`1/2`, attributes `doses_taken` / `doses_total`) |
| `binary_sensor.*_completed_today` | On when all doses are completed today |
| `button.*_complete` | Mark current dose completed |
| `button.*_snooze` | Snooze reminder |
| `button.*_skip_today` | Skip for today |

Status values: `pending`, `reminder_sent`, `snoozed`, `partial`, `completed`, `skipped`, `missed`.

After the first dose of a multi-dose day, status becomes **Dos tagen** (`partial`) instead of jumping back to only **Väntar**. Use `dose_progress` on dashboards for `1 av 2`-style cards.

### Dose windows

In the schedule step, set **doses per day** (1-3) and reminder times per dose. Times inside one dose are retries until that dose is marked taken. Example:

- Dose 1: `08:30,09:00,09:30`
- Dose 2: `11:30,12:00,12:30`

### Notification dashboard tap

In the reminders step, enable **Open dashboard on notification tap**, pick a dashboard (and optional view path), or set a custom path like `/dashboard-medicin/0`. A normal tap on the Companion notification opens that path; long-press still shows Tagit / Snooze.

## Lovelace / Mushroom

Yes. These are normal HA entities (`sensor`, `binary_sensor`, `button`). Any card that can bind an entity_id works: Mushroom, Tile, Button, Entity, custom cards, etc.

Example (replace entity ids with yours from Developer tools > States):

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-template-card
    entity: sensor.medication_status
    primary: medication
    secondary: "{{ states(entity) }}"
    icon: >
      {% set s = states(entity) %}
      {% if s == 'completed' %}mdi:check-circle
      {% elif s == 'reminder_sent' %}mdi:bell-ring
      {% elif s == 'snoozed' %}mdi:alarm-snooze
      {% elif s == 'missed' %}mdi:alert-circle
      {% else %}mdi:timer-sand{% endif %}
    icon_color: >
      {% set s = states(entity) %}
      {% if s == 'completed' %}green
      {% elif s == 'reminder_sent' %}orange
      {% elif s == 'snoozed' %}amber
      {% elif s == 'missed' %}red
      {% else %}grey{% endif %}
  - type: horizontal-stack
    cards:
      - type: custom:mushroom-entity-card
        entity: button.medication_routine_done
        name: Klar
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.medication_routine_done
      - type: custom:mushroom-entity-card
        entity: button.medication_snooze
        name: Snooze
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.medication_snooze
      - type: custom:mushroom-entity-card
        entity: button.medication_skip_today
        name: Hoppa över
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.medication_skip_today
```

Built-in Tile card works without HACS custom cards:

```yaml
type: tile
entity: sensor.medication_status
features_position: bottom
vertical: false
```

The default device page list stays plain HA chrome. Fancy colors live on your dashboard cards, not on that built-in entity list.

## Brand / logo

`brand/icon.png` and `brand/logo.png` ship with the integration (HA 2024.2+ / inline brands). After restart they show in Settings > Devices & services for **HA Routines**.

Per-routine device icons still use the MDI you pick in the wizard. Replacing those with a custom PNG per routine is not supported the same way; use Lovelace cards for custom visuals.

## Services

| Service | Effect |
|---------|--------|
| `ha_routines.complete` | Complete (`routine_id` required) |
| `ha_routines.snooze` | Snooze (`routine_id`, optional `minutes`) |
| `ha_routines.skip_today` | Skip today |
| `ha_routines.reset` | Reset to pending |
| `ha_routines.trigger_reminder` | Force reminder (+ notify if configured) |

## Events

- `routine_completed`
- `routine_skipped`
- `routine_snoozed`
- `routine_reminder_sent`

## Output Structure

### Storage file

`.storage/ha_routines_data` (managed by Home Assistant):

```json
{
  "version": 1,
  "routines": {
    "<subentry_id>": {
      "routine_id": "<subentry_id>",
      "state": "pending",
      "last_completed_at": null,
      "next_reminder_at": null,
      "reminder_count": 0,
      "current_streak": 0,
      "longest_streak": 0,
      "missed_count": 0,
      "snoozed_until": null,
      "completion_history": [],
      "missed_history": [],
      "skipped_history": [],
      "completed_today": false,
      "skipped_today": false,
      "cycle_date": "2026-07-17",
      "last_reminder_at": null
    }
  }
}
```

### Subentry config (per routine)

Stored in the config entry subentry `data` field via the config flow wizard. Pick a Companion `notify.*` entity in the reminders step to enable actionable reminders.

## State Machine

```text
Pending -> Reminder Sent | Snoozed | Partial | Completed | Skipped | Missed
Reminder Sent -> Completed | Partial | Snoozed | Skipped | Missed | Pending
Snoozed -> Reminder Sent | Snoozed (extend) | Partial | Completed | Skipped | Pending
Partial -> Reminder Sent | Snoozed | Partial | Completed | Skipped | Missed | Pending
Completed | Skipped | Missed -> Pending (next cycle)
```

## Reset / Cleanup

Remove the integration from **Settings > Devices & services > HA Routines > Delete**.

This removes config entries, subentries, entities, and the `.storage/ha_routines_data` file.

Extra cleanup (keeps `.env` / secrets untouched; this integration has none): delete leftover `custom_components/ha_routines` if you uninstall permanently.

## Restore

Restore `.storage/ha_routines_data` from backup together with `.storage/core.config_entries` if you need to recover routine history after a full config restore.

## Scheduling

The integration schedules reminders itself using `async_track_point_in_utc_time` and Home Assistant's configured timezone. After restart it reconciles past-due reminders and day roll-overs. No YAML automations are required.

## Install with HACS

This repository is HACS-ready. Integration files live at the repository root with `"content_in_root": true` in `hacs.json`.

1. HACS → menu (⋮) → **Custom repositories**
2. Repository URL: `https://github.com/ivyytheone/ha_routines`
3. Category: **Integration**
4. Add the repository, then install **HA Routines**
5. Restart Home Assistant
6. Settings → Devices & services → Add integration → **HA Routines**

Updates: when a new version is on GitHub, use HACS → HA Routines → **Update**, then restart if prompted.

### Support

This integration is maintained mainly for the author's own Home Assistant setup. You are welcome to use and adapt it. There is no SLA.

- Bugs, ideas, or questions: open an issue on https://github.com/ivyytheone/ha_routines/issues
- Contact: jbc@ivyydev.se
- Website: https://ivyydev.se/

## Tests

Unit tests for this integration live in the development workspace under `tests/test_ha_routines/` (state machine, storage, scheduler, DST, restart roll-over). They are not shipped inside the HACS package.
