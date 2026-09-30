# Changelog

## Unreleased

### Added

- **Game icons:** item, skill and equipment-slot icons from the icon CDN (https://icons.scapekeeper.com). Skill sensors, **Last Loot** and **Last Collection Log** show the icon as their entity picture. Inventory, equipment, loot and death items have an `icon` attribute (the right stack for coins and other stackables), and **Equipment** has `slot_icons` with the empty-slot silhouettes. The new **Icon URL** option points at a mirror, or turns icons off when it is empty. Both example dashboards show the icons.
- **NOTICE and CITATION.cff:** the integration stays Apache-2.0; a `NOTICE` file (which redistributions and derivative works must keep, Apache-2.0 §4(d)) now asks for credit to RedFirebreak, and `CITATION.cff` gives the repository GitHub's "Cite this repository" button. The README has a License section.

### Fixed

- **Wrong PC clock:** a payload timestamp from a clock that ran ahead no longer freezes sensors or makes the account go offline while data is still arriving. Timestamps are capped at the time Home Assistant receives them, a snapshot is only compared with earlier snapshots from the same RuneLite client, and every payload keeps the account online. A future timestamp stored by an earlier version is dropped on startup.
- **Malformed payloads:** a section or field with the wrong type is skipped instead of causing a `500`. A payload without a usable player returns `400`. A payload the plugin resends after a real server error is now processed, instead of being reported as a duplicate and lost.
- **Second integration entry:** only one OSRS Data entry is allowed. A second entry used to break the first entry's paired clients (`401`, which disables the plugin connection). A duplicate left over from an older version is not loaded, and deleting it keeps your data.
- **Name changes:** a queued payload with an account's old name, delivered after the rename, no longer makes the old name point at the renamed account. That could merge a different player into it or create a duplicate device.
- **Event history:** history is stored per account instead of per display name, so two accounts that swap names keep separate history. Existing history is migrated on startup.
- **Filtered sections:** when the plugin's filters leave out inventory, equipment, health, prayer points, location or spellbook, the sensor keeps its last known value instead of showing an empty inventory or position 0, 0. A new `received` attribute shows whether the latest update contained the section.
- **Pairing:** failed pairing attempts are rate limited (10 per IP address per 10 minutes; `429` with `Retry-After`).
- **Presence timeout:** the periodic check that marks accounts offline now runs in Home Assistant's event loop instead of a worker thread. Recent Home Assistant versions log a thread-safety error for it ("calls async_dispatcher_send from a thread other than the event loop"), and accounts were not always marked offline.
