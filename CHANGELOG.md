# Changelog

## Unreleased

### Fixed

- **Wrong PC clock:** a payload timestamp from a clock that ran ahead no longer freezes sensors or makes the account go offline while data is still arriving. Timestamps are capped at the time Home Assistant receives them, a snapshot is only compared with earlier snapshots from the same RuneLite client, and every payload keeps the account online. A future timestamp stored by an earlier version is dropped on startup.
- **Malformed payloads:** a section or field with the wrong type is skipped instead of causing a `500`. A payload without a usable player returns `400`. A payload the plugin resends after a real server error is now processed, instead of being reported as a duplicate and lost.
- **Second integration entry:** only one OSRS Data entry is allowed. A second entry used to break the first entry's paired clients (`401`, which disables the plugin connection). A duplicate left over from an older version is not loaded, and deleting it keeps your data.
- **Name changes:** a queued payload with an account's old name, delivered after the rename, no longer makes the old name point at the renamed account. That could merge a different player into it or create a duplicate device.
- **Event history:** history is stored per account instead of per display name, so two accounts that swap names keep separate history. Existing history is migrated on startup.
- **Filtered sections:** when the plugin's filters leave out inventory, equipment, health, prayer points, location or spellbook, the sensor keeps its last known value instead of showing an empty inventory or position 0, 0. A new `received` attribute shows whether the latest update contained the section.
- **Pairing:** failed pairing attempts are rate limited (10 per IP address per 10 minutes; `429` with `Retry-After`).
