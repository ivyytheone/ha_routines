# HA Routines

Recurring routines for Home Assistant without helpers or YAML automations. Each routine is configured through a UI wizard and exposes standard entities for dashboards (Mushroom, tile, button, entity cards).

## Quick Start

1. Copy `custom_components/ha_routines` into your Home Assistant `config` folder, or run `sync-ha_routines.ps1` from this dev environment.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and search for **HA Routines**.
4. Complete the hub setup, then click **Add routine** on the integration device page.
5. Walk through the three-step wizard: basic info, schedule, reminders.

No YAML configuration is required.

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

Copy the whole folder to your live instance:

```text
custom_components/ha_routines/
```

Ways to transfer:

1. **Samba / Studio Code Server / File editor:** paste the folder under `/config/custom_components/ha_routines`
2. **scp / SFTP** from this machine to the HA host
3. **HACS** (when published as a GitHub repo): install as a custom repository of type Integration

Then:

1. Restart Home Assistant
2. Settings > Devices & services > Add integration > **HA Routines**
3. Recreate routines in the wizard (runtime history does not migrate automatically unless you also copy `.storage/ha_routines_data` and matching config entries)

Dev Docker and production are separate installs. Syncing this repo does not push to your real HA unless you copy the folder yourself.

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
| `sensor.*_status` | Current state + attributes (next reminder, streaks, history) |
| `binary_sensor.*_completed_today` | On when completed today |
| `button.*_complete` | Mark completed |
| `button.*_snooze` | Snooze reminder |
| `button.*_skip_today` | Skip for today |

Status values: `pending`, `reminder_sent`, `snoozed`, `completed`, `skipped`, `missed`. UI shows translated labels (e.g. Klar / Done). Icons change per state via `icons.json`.

## Lovelace / Mushroom

Yes. These are normal HA entities (`sensor`, `binary_sensor`, `button`). Any card that can bind an entity_id works: Mushroom, Tile, Button, Entity, custom cards, etc.

Example (replace entity ids with yours from Developer tools > States):

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-template-card
    entity: sensor.pregabalin_status
    primary: Pregabalin
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
        entity: button.pregabalin_routine_done
        name: Klar
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.pregabalin_routine_done
      - type: custom:mushroom-entity-card
        entity: button.pregabalin_snooze
        name: Snooze
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.pregabalin_snooze
      - type: custom:mushroom-entity-card
        entity: button.pregabalin_skip_today
        name: Hoppa över
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.pregabalin_skip_today
```

Built-in Tile card works without HACS custom cards:

```yaml
type: tile
entity: sensor.pregabalin_status
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
Pending -> Reminder Sent | Snoozed | Completed | Skipped | Missed
Reminder Sent -> Completed | Snoozed | Skipped | Missed | Pending
Snoozed -> Reminder Sent | Snoozed (extend) | Completed | Skipped | Pending
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

## HACS Publishing

When this becomes a standalone repository, place `hacs.json` in the repository root. A template is included at `custom_components/ha_routines/hacs.json` for reference.

## Tests

Unit tests live under `tests/test_ha_routines/` and cover state machine, storage migration/trim, next-reminder calculation, DST edges, and restart day roll-over.
