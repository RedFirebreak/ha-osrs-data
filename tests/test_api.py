"""Tests for the OSRS Data HTTP API endpoints."""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock homeassistant before imports
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Provide a minimal HomeAssistantView mock
_http_mod = sys.modules["homeassistant.components.http"]


class _MockView:
    """Minimal HomeAssistantView stand-in."""
    requires_auth = True

    def json(self, data, status_code=200, headers=None):
        from aiohttp.web import json_response
        return json_response(data, status=status_code, headers=headers)


_http_mod.HomeAssistantView = _MockView

# Force re-import of the api module
sys.modules.pop("custom_components.osrs_data.api", None)

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.api import (  # noqa: E402
    OsrsDeviceRevokeView,
    OsrsDevicesView,
    OsrsEventsView,
    OsrsPairCodeView,
    OsrsPairView,
)
from custom_components.osrs_data.account_store import AccountStore  # noqa: E402
from custom_components.osrs_data.const import (  # noqa: E402
    DATA_ACCOUNT_STORE,
    DATA_EVENT_DEDUPE_CACHE,
    DATA_HISTORY_STORE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    DOMAIN,
)
from custom_components.osrs_data.dedupe import EventDedupeCache  # noqa: E402
from custom_components.osrs_data.history import HistoryStore  # noqa: E402
from custom_components.osrs_data.pairing import PairingStore  # noqa: E402
from tests.test_parsers import FUZZ_BASE, FUZZ_PATHS, FUZZ_VALUES, fuzzed  # noqa: E402


# ── Sample payloads ──────────────────────────────────────────────────

BASE_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "PlayerOne",
        "accountType": "normal",
        "world": "302",
        "stats": {
            "skills": {
                "Attack": {"xp": 737627, "level": 60},
            }
        },
        "inventory": {
            "items": [
                {"name": "Shark", "gePrice": 800, "haPrice": 600, "quantity": 10},
            ]
        },
        "equipment": {
            "items": [
                {"name": "Fire cape", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "CAPE"},
            ]
        },
        "events": [],
    }
}


def _make_hass_with_pairing():
    """Create a mock hass with pairing store wired up."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    store = AccountStore()
    pairing_store = PairingStore()
    mock_storage = MagicMock()
    entry_id = "test_entry"
    hass.data = {
        DOMAIN: {
            entry_id: {
                DATA_ACCOUNT_STORE: store,
                DATA_HISTORY_STORE: HistoryStore(),
                DATA_EVENT_DEDUPE_CACHE: EventDedupeCache(),
                DATA_PAIRING_STORE: pairing_store,
                DATA_STORE: mock_storage,
            }
        }
    }
    return hass, store, pairing_store, mock_storage


def _make_json_request(hass, payload, headers=None):
    """Create a mock aiohttp request with JSON body."""
    request = MagicMock()
    request.app = {"hass": hass}
    request.headers = {"Content-Type": "application/json"}
    if headers:
        request.headers.update(headers)
    request.json = AsyncMock(return_value=payload)
    request.post = AsyncMock(return_value={})
    return request


# ── Pair endpoint tests ──────────────────────────────────────────────


class TestOsrsPairView:
    @pytest.mark.asyncio
    async def test_pair_valid_code(self):
        """Consuming a valid pairing code returns device token."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code("My Plugin")

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": code})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert "device_id" in body
        assert "token" in body

    @pytest.mark.asyncio
    async def test_pair_invalid_code(self):
        """Invalid pairing code returns 403."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": "000000"})
        result = await view.post(request)

        assert result.status == 403
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_pair_missing_code(self):
        """Missing code field returns 400."""
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsPairView()
        request = _make_json_request(hass, {})
        result = await view.post(request)

        assert result.status == 400
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_pair_code_consumed_once(self):
        """Code can only be used once."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()

        view = OsrsPairView()
        r1 = await view.post(_make_json_request(hass, {"code": code}))
        r2 = await view.post(_make_json_request(hass, {"code": code}))

        assert r1.status == 200
        assert r2.status == 403


# ── Events endpoint tests ───────────────────────────────────────────


class TestOsrsEventsView:
    @pytest.mark.asyncio
    async def test_events_with_valid_token(self):
        """Valid token allows event submission."""
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        request = _make_json_request(
            hass, BASE_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        hass.bus.async_fire.assert_called_once()

        # Account should be updated
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.account_type == "normal"

    @pytest.mark.asyncio
    async def test_events_missing_token(self):
        """Missing token returns 401."""
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsEventsView()
        request = _make_json_request(hass, BASE_PAYLOAD)
        result = await view.post(request)

        assert result.status == 401
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_events_invalid_token(self):
        """Invalid token returns 401 so the plugin disables the connection."""
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsEventsView()
        request = _make_json_request(
            hass, BASE_PAYLOAD, headers={"X-Osrs-Token": "bad_token"}
        )
        result = await view.post(request)

        assert result.status == 401
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_events_revoked_token(self):
        """Revoked token returns 401 so the plugin disables the connection."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]
        pairing_store.revoke_device(pair_result["device_id"])

        view = OsrsEventsView()
        request = _make_json_request(
            hass, BASE_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        result = await view.post(request)

        assert result.status == 401

    @pytest.mark.asyncio
    async def test_events_fires_ha_event(self):
        """Valid event submission fires HA event."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        request = _make_json_request(
            hass, BASE_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        await view.post(request)

        hass.bus.async_fire.assert_called_once()
        event_name, event_data = hass.bus.async_fire.call_args[0]
        assert event_name == "osrs_data_event"
        assert event_data["player_name"] == "PlayerOne"

    @pytest.mark.asyncio
    async def test_events_schedules_save(self):
        """Event submission schedules a save."""
        hass, _, pairing_store, mock_storage = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        request = _make_json_request(
            hass, BASE_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        await view.post(request)

        mock_storage.async_delay_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_identical_resend_fires_each_event_once(self):
        """A resent payload is processed again; its events are deduped by id."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]
        payload = {
            **BASE_PAYLOAD,
            "events": [{"type": "death", "eventId": "dup-1", "data": {"killerName": "Jad"}}],
        }

        view = OsrsEventsView()
        r1 = await view.post(
            _make_json_request(hass, payload, headers={"X-Osrs-Token": token})
        )
        r2 = await view.post(
            _make_json_request(hass, payload, headers={"X-Osrs-Token": token})
        )

        assert json.loads(r1.body) == {"ok": True}
        assert json.loads(r2.body) == {"ok": True}
        fired = [c.args[1] for c in hass.bus.async_fire.call_args_list]
        assert [f.get("event_type") for f in fired].count("DEATH") == 1

    @pytest.mark.asyncio
    async def test_identical_heartbeat_refreshes_presence(self):
        """Older plugins send no timestamp, so an idle heartbeat is identical."""
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        pair = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())
        view = OsrsEventsView()
        headers = {"X-Osrs-Token": pair["token"]}
        await view.post(_make_json_request(hass, BASE_PAYLOAD, headers=headers))
        acct = store.get_or_create(None, "PlayerOne")
        acct.last_seen = datetime.now(timezone.utc) - timedelta(minutes=5)

        await view.post(_make_json_request(hass, BASE_PAYLOAD, headers=headers))

        assert datetime.now(timezone.utc) - acct.last_seen < timedelta(minutes=1)


class TestEventsAccountHash:
    """accountHash keeps a renamed account on the same device/entities."""

    HASH = "c" * 56

    def _payload(self, name, account_hash=None, events=None):
        player = {"name": name, "world": "302"}
        if account_hash:
            player["accountHash"] = account_hash
        return {"player": player, "events": events or []}

    async def _post(self, hass, token, payload):
        view = OsrsEventsView()
        request = _make_json_request(hass, payload, headers={"X-Osrs-Token": token})
        return await view.post(request)

    @pytest.mark.asyncio
    async def test_rename_with_hash_keeps_account_and_history(self):
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        pair = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())
        token = pair["token"]
        history = hass.data[DOMAIN]["test_entry"][DATA_HISTORY_STORE]

        send = MagicMock()
        # Patch the view's own globals: other tests re-import the api module.
        with patch.dict(OsrsEventsView.post.__globals__, {"async_dispatcher_send": send}):
            # Legacy account created before the plugin sent hashes
            r = await self._post(hass, token, self._payload(
                "OldName", events=[{"type": "DEATH", "data": {"killerName": "Jad"}}]
            ))
            assert r.status == 200
            r = await self._post(hass, token, self._payload("OldName", self.HASH))
            assert r.status == 200
            r = await self._post(hass, token, self._payload(
                "NewName", self.HASH,
                events=[{"type": "DEATH", "data": {"killerName": "Zuk"}}],
            ))
            assert r.status == 200

        assert len(store.accounts) == 1
        acct = store.accounts[0]
        assert acct.account_hash == "oldname"
        assert acct.player_name == "NewName"
        assert acct.previous_names == ["OldName"]
        dispatched = {c.args[2] for c in send.call_args_list}
        assert dispatched == {"oldname"}
        # History is keyed by the account key, so the rename doesn't move it.
        deaths = history.get_or_create("oldname").get("DEATH")
        assert [d["data"]["killerName"] for d in deaths] == ["Jad", "Zuk"]
        assert set(history.to_dict()) == {"oldname"}

    @pytest.mark.asyncio
    async def test_name_swap_keeps_histories_apart(self):
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        token = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())["token"]
        history = hass.data[DOMAIN]["test_entry"][DATA_HISTORY_STORE]
        hash_a, hash_b = "a" * 56, "b" * 56
        for name, account_hash, ts, killer in (
            ("Alice", hash_a, 1_000, "a1"),
            ("Bob", hash_b, 1_000, "b1"),
            ("Bob", hash_a, 2_000, "a2"),    # A takes the name Bob ...
            ("Alice", hash_b, 2_000, "b2"),  # ... and B takes Alice
        ):
            payload = {
                **self._payload(name, account_hash),
                "timestamp": ts,
                "events": [{"type": "death", "eventId": killer, "data": {"killerName": killer}}],
            }
            assert (await self._post(hass, token, payload)).status == 200

        a = store.get_or_create(None, "?", plugin_hash=hash_a)
        b = store.get_or_create(None, "?", plugin_hash=hash_b)
        assert (a.player_name, b.player_name) == ("Bob", "Alice")

        def killers(acct):
            deaths = history.get_or_create(acct.account_hash).get("DEATH")
            return [d["data"]["killerName"] for d in deaths]

        assert killers(a) == ["a1", "a2"]
        assert killers(b) == ["b1", "b2"]

    async def _renamed_then_late_resend(self):
        """Rename OldName -> NewName, then deliver a queued OldName payload."""
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        token = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())["token"]
        for name, ts in (("OldName", 1_000), ("NewName", 3_000), ("OldName", 2_000)):
            payload = {**self._payload(name, self.HASH), "timestamp": ts}
            assert (await self._post(hass, token, payload)).status == 200
        acct = store.accounts[0]
        assert acct.player_name == "NewName"
        return hass, store, token, acct

    @pytest.mark.asyncio
    async def test_late_resend_old_name_without_hash_is_another_account(self):
        hass, store, token, acct = await self._renamed_then_late_resend()
        await self._post(hass, token, {**self._payload("OldName"), "timestamp": 4_000})
        assert acct.player_name == "NewName"
        assert len(store.accounts) == 2

    @pytest.mark.asyncio
    async def test_late_resend_current_name_without_hash_resolves_account(self):
        hass, store, token, acct = await self._renamed_then_late_resend()
        await self._post(hass, token, {**self._payload("NewName"), "timestamp": 4_000})
        assert store.accounts == [acct]

    @pytest.mark.asyncio
    async def test_late_resend_current_name_with_hash_resolves_account(self):
        hass, store, token, acct = await self._renamed_then_late_resend()
        await self._post(hass, token, {**self._payload("NewName", self.HASH), "timestamp": 4_000})
        assert store.accounts == [acct]
        assert store.get_or_create(None, "NewName") is acct

    @pytest.mark.asyncio
    async def test_payload_without_hash_unchanged(self):
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        pair = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())
        r = await self._post(hass, pair["token"], self._payload("PlayerOne"))
        assert r.status == 200
        acct = store.accounts[0]
        assert acct.account_hash == "playerone"
        assert acct.plugin_account_hash is None


# ── Devices endpoint tests ──────────────────────────────────────────


class TestOsrsDevicesView:
    @pytest.mark.asyncio
    async def test_list_devices_empty(self):
        hass, _, _, _ = _make_hass_with_pairing()
        view = OsrsDevicesView()
        request = _make_json_request(hass, {})
        result = await view.get(request)
        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert body["devices"] == []

    @pytest.mark.asyncio
    async def test_list_devices_with_paired(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code("My Device")
        pairing_store.consume_pairing_code(code)

        view = OsrsDevicesView()
        request = _make_json_request(hass, {})
        result = await view.get(request)

        body = json.loads(result.body)
        assert len(body["devices"]) == 1
        assert body["devices"][0]["name"] == "My Device"


class TestOsrsDeviceRevokeView:
    @pytest.mark.asyncio
    async def test_revoke_existing_device(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)

        view = OsrsDeviceRevokeView()
        request = _make_json_request(hass, {})
        result = await view.delete(request, pair_result["device_id"])

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_device(self):
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsDeviceRevokeView()
        request = _make_json_request(hass, {})
        result = await view.delete(request, "nonexistent_id")

        assert result.status == 404
        body = json.loads(result.body)
        assert body["ok"] is False


# ── Pair code generation endpoint tests ──────────────────────────────


class TestOsrsPairCodeView:
    @pytest.mark.asyncio
    async def test_generate_code_default_name(self):
        """Generating a code with no device_name uses the default."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()

        view = OsrsPairCodeView()
        request = _make_json_request(hass, {})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert "code" in body
        assert len(body["code"]) == 5
        assert body["code"].isdigit()
        assert "expires_in" in body

    @pytest.mark.asyncio
    async def test_generate_code_custom_name(self):
        """Generating a code with a custom device_name."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()

        view = OsrsPairCodeView()
        request = _make_json_request(hass, {"device_name": "My Laptop"})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert len(body["code"]) == 5

    @pytest.mark.asyncio
    async def test_generated_code_is_consumable(self):
        """A code generated via the API endpoint can be consumed to pair."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()

        # Generate code via the view
        view = OsrsPairCodeView()
        request = _make_json_request(hass, {"device_name": "Test Device"})
        result = await view.post(request)
        code = json.loads(result.body)["code"]

        # Now consume it via the pair view
        pair_view = OsrsPairView()
        pair_request = _make_json_request(hass, {"code": code})
        pair_result = await pair_view.post(pair_request)

        assert pair_result.status == 200
        pair_body = json.loads(pair_result.body)
        assert pair_body["ok"] is True
        assert "token" in pair_body

    @pytest.mark.asyncio
    async def test_generate_code_no_integration(self):
        """Returns 503 when no integration is configured."""
        hass = MagicMock()
        hass.data = {}

        view = OsrsPairCodeView()
        request = _make_json_request(hass, {})
        result = await view.post(request)

        assert result.status == 503


# ── Config-flow pending pairing tests ────────────────────────────────


class TestOsrsPairViewConfigFlowPending:
    """Test the pair endpoint with _pending_pairings (config flow codes)."""

    @pytest.mark.asyncio
    async def test_pair_via_pending_config_flow_code(self):
        """Code from a pending config flow is consumed correctly."""
        import time

        hass = MagicMock()
        hass.bus = MagicMock()

        # Simulate a config flow that stored a pending pairing
        temp_store = PairingStore()
        temp_store.inject_pending_code("112233", "Flow Device", time.time() + 300)

        hass.data = {
            DOMAIN: {
                "_pending_pairings": {
                    "flow_abc": {
                        "store": temp_store,
                        "result": None,
                    }
                }
            }
        }

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": "112233"})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert "token" in body
        assert "device_id" in body

        # The pending entry should have the result stored
        pending = hass.data[DOMAIN]["_pending_pairings"]["flow_abc"]
        assert pending["result"] is not None
        assert pending["result"]["device_id"] == body["device_id"]

    @pytest.mark.asyncio
    async def test_pair_via_pending_mirrors_to_live_store(self):
        """Pairing via temp store mirrors the device into the live entry store."""
        import time

        hass, _, live_pairing, _ = _make_hass_with_pairing()

        # Simulate a pending config-flow temp store
        temp_store = PairingStore()
        temp_store.inject_pending_code("556677", "Flow Laptop", time.time() + 300)
        hass.data[DOMAIN]["_pending_pairings"] = {
            "flow_mirror": {"store": temp_store, "result": None}
        }

        # Pair via the temp store code
        view = OsrsPairView()
        request = _make_json_request(hass, {"code": "556677"})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        token = body["token"]
        device_id = body["device_id"]

        # The device should now be in the LIVE store (mirrored)
        assert live_pairing.validate_token(token) == device_id

        # So the events endpoint should accept this token
        events_view = OsrsEventsView()
        event_request = _make_json_request(
            hass,
            {
                "player": {
                    "name": "TestPlayer",
                    "accountType": "normal",
                    "world": "302",
                    "stats": {"skills": {}},
                    "inventory": {"items": []},
                    "equipment": {"items": []},
                    "events": [],
                }
            },
            headers={"X-Osrs-Token": token},
        )
        event_result = await events_view.post(event_request)
        assert event_result.status == 200
        event_body = json.loads(event_result.body)
        assert event_body["ok"] is True

    @pytest.mark.asyncio
    async def test_pair_invalid_code_falls_through_to_entry(self):
        """Invalid code in pending falls through to per-entry store check."""
        import time

        hass, _, pairing_store, _ = _make_hass_with_pairing()

        # Add a pending config flow with a different code
        temp_store = PairingStore()
        temp_store.inject_pending_code("999999", "Flow", time.time() + 300)
        hass.data[DOMAIN]["_pending_pairings"] = {
            "flow_x": {"store": temp_store, "result": None}
        }

        # Create a code in the per-entry store
        entry_code = pairing_store.create_pairing_code("Entry Device")

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": entry_code})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True

    @pytest.mark.asyncio
    async def test_pair_no_entries_no_pending(self):
        """No entries and no pending pairings returns 503."""
        hass = MagicMock()
        hass.data = {DOMAIN: {}}

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": "000000"})
        result = await view.post(request)

        assert result.status == 503


# ── Plugin compatibility (HA Exporter #28–#35) ───────────────────────


def _paired(hass_tuple):
    hass, store, pairing_store, storage = hass_tuple
    pair = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())
    return hass, store, pairing_store, pair


async def _post_events(hass, token, payload, extra_headers=None):
    headers = {"X-Osrs-Token": token}
    if extra_headers:
        headers.update(extra_headers)
    request = _make_json_request(hass, payload, headers=headers)
    return await OsrsEventsView().post(request)


class TestBadInputIs4xx:
    """The plugin retries 5xx; bad input must be 4xx so it is dropped."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self):
        hass, _, _, pair = _paired(_make_hass_with_pairing())
        request = _make_json_request(hass, None, headers={"X-Osrs-Token": pair["token"]})
        request.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "x", 0))
        result = await OsrsEventsView().post(request)
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_list_body_returns_400(self):
        hass, _, _, pair = _paired(_make_hass_with_pairing())
        result = await _post_events(hass, pair["token"], [1, 2, 3])
        assert result.status == 400

    @pytest.mark.asyncio
    async def test_bad_event_does_not_fail_payload(self):
        hass, _, _, pair = _paired(_make_hass_with_pairing())
        payload = {
            "player": {"name": "PlayerOne"},
            "events": [
                {"type": 123, "data": {}},  # type isn't a string -> .upper() fails
                {"type": "death", "eventId": "ok-1", "data": {"killerName": "Jad"}},
            ],
        }
        result = await _post_events(hass, pair["token"], payload)
        assert result.status == 200
        fired = [c.args[1] for c in hass.bus.async_fire.call_args_list]
        assert any(f.get("event_type") == "DEATH" for f in fired)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", FUZZ_PATHS, ids=lambda p: ".".join(map(str, p)))
    async def test_wrong_types_never_return_5xx(self, path):
        for value in FUZZ_VALUES:
            hass, store, _, pair = _paired(_make_hass_with_pairing())
            result = await _post_events(hass, pair["token"], fuzzed(path, value))
            assert result.status == 200, (value, result.body)
            for acct in store.accounts:
                # What the sensors compute must work on whatever was stored.
                assert acct.total_level >= 0
                acct.combat_level  # noqa: B018

    @pytest.mark.asyncio
    async def test_unusable_player_returns_400(self):
        for bad in (7, True, ["P"], {"n": "P"}, "   "):
            hass, store, _, pair = _paired(_make_hass_with_pairing())
            result = await _post_events(hass, pair["token"], {"player": {"name": bad}})
            assert result.status == 400, bad
            assert store.accounts == []

    @pytest.mark.asyncio
    async def test_retry_after_failure_is_processed(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        payload = {
            "player": {"name": "PlayerOne"},
            "events": [{"type": "death", "eventId": "retry-1", "data": {"killerName": "Jad"}}],
            "timestamp": 1_000,
        }
        # A transient failure while handling the payload -> 500, so the
        # plugin retries it.
        hass.bus.async_fire.side_effect = [RuntimeError("bus unavailable")] + [None] * 10
        first = await _post_events(hass, pair["token"], payload)
        assert first.status == 500

        retry = await _post_events(hass, pair["token"], payload)

        assert retry.status == 200
        assert "duplicate" not in json.loads(retry.body)
        fired = [c.args[1] for c in hass.bus.async_fire.call_args_list]
        assert any(f.get("event_type") == "DEATH" for f in fired)
        assert store.get_or_create(None, "PlayerOne").event_totals["DEATH"]["count"] == 1

    @pytest.mark.asyncio
    async def test_pair_non_string_code_returns_400(self):
        hass, _, _, _ = _make_hass_with_pairing()
        request = _make_json_request(hass, {"code": 12345})
        result = await OsrsPairView().post(request)
        assert result.status == 400


class TestPairResponseName:
    @pytest.mark.asyncio
    async def test_pair_response_includes_location_name(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        hass.config.location_name = "My Home"
        code = pairing_store.create_pairing_code()
        result = await OsrsPairView().post(_make_json_request(hass, {"code": code}))
        body = json.loads(result.body)
        assert result.status == 200
        assert body["name"] == "My Home"

    @pytest.mark.asyncio
    async def test_pair_response_omits_blank_name(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        hass.config.location_name = "  "
        code = pairing_store.create_pairing_code()
        result = await OsrsPairView().post(_make_json_request(hass, {"code": code}))
        assert "name" not in json.loads(result.body)


class TestRetryAfter:
    @pytest.mark.asyncio
    async def test_events_503_has_retry_after(self):
        hass = MagicMock()
        hass.data = {}
        request = _make_json_request(hass, BASE_PAYLOAD, headers={"X-Osrs-Token": "x"})
        result = await OsrsEventsView().post(request)
        assert result.status == 503
        assert result.headers.get("Retry-After") == "60"

    @pytest.mark.asyncio
    async def test_pair_503_has_retry_after(self):
        hass = MagicMock()
        hass.data = {}
        result = await OsrsPairView().post(_make_json_request(hass, {"code": "12345"}))
        assert result.status == 503
        assert result.headers.get("Retry-After") == "60"


class TestPluginVersion:
    HEADER = "X-Osrs-Exporter-Version"

    @pytest.mark.asyncio
    async def test_version_recorded_on_device_and_account(self):
        hass, store, pairing_store, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], BASE_PAYLOAD, {self.HEADER: "1.4"})
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.plugin_version == "1.4"
        device = next(d for d in pairing_store.list_devices() if d["device_id"] == pair["device_id"])
        assert device["plugin_version"] == "1.4"
        assert device["last_seen"]

    @pytest.mark.asyncio
    async def test_version_capped(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], BASE_PAYLOAD, {self.HEADER: "9" * 100})
        assert len(store.get_or_create(None, "PlayerOne").plugin_version) == 32

    @pytest.mark.asyncio
    async def test_no_header_keeps_previous_version(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], BASE_PAYLOAD, {self.HEADER: "1.4"})
        payload = {**BASE_PAYLOAD, "tickDelay": 50}
        await _post_events(hass, pair["token"], payload)
        assert store.get_or_create(None, "PlayerOne").plugin_version == "1.4"


class TestStaleSnapshot:
    """Queued payloads resent late must not overwrite newer state."""

    def _payload(self, ts, world, events=None):
        return {
            "player": {"name": "PlayerOne", "world": world},
            "events": events or [],
            "timestamp": ts,
        }

    @pytest.mark.asyncio
    async def test_older_snapshot_ignored_but_events_fire(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(2_000, "302"))
        hass.bus.async_fire.reset_mock()
        old = self._payload(1_000, "999", [{"type": "death", "eventId": "late-1", "data": {}}])
        result = await _post_events(hass, pair["token"], old)
        assert result.status == 200
        assert store.get_or_create(None, "PlayerOne").world == "302"
        fired = [c.args[1] for c in hass.bus.async_fire.call_args_list]
        assert any(f.get("event_type") == "DEATH" for f in fired)

    @pytest.mark.asyncio
    async def test_newer_snapshot_applies(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(1_000, "302"))
        await _post_events(hass, pair["token"], self._payload(2_000, "303"))
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.world == "303"
        assert acct.last_payload_ts == 2_000

    @pytest.mark.asyncio
    async def test_payload_without_timestamp_always_applies(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(2_000, "302"))
        legacy = {"player": {"name": "PlayerOne", "world": "310"}, "events": []}
        await _post_events(hass, pair["token"], legacy)
        assert store.get_or_create(None, "PlayerOne").world == "310"


def _now_ms() -> int:
    return int(time.time() * 1000)


class TestSnapshotClockSkew:
    """Payload timestamps come from the player's PC clock, which can be wrong."""

    HOUR_MS = 3_600_000
    DAY_MS = 86_400_000

    def _payload(self, ts, world, events=None):
        return {
            "player": {"name": "PlayerOne", "world": world},
            "events": events or [],
            "timestamp": ts,
        }

    @pytest.mark.asyncio
    async def test_future_timestamp_does_not_freeze_snapshots(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(_now_ms() + self.DAY_MS, "302"))
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.last_payload_ts <= _now_ms()
        # The PC clock is corrected; its next snapshot carries the real time.
        await _post_events(hass, pair["token"], self._payload(_now_ms(), "303"))
        assert acct.world == "303"

    @pytest.mark.asyncio
    async def test_devices_with_skewed_clocks_apply_in_arrival_order(self):
        hass, store, pairing_store, fast = _paired(_make_hass_with_pairing())
        slow = pairing_store.consume_pairing_code(pairing_store.create_pairing_code())
        await _post_events(hass, fast["token"], self._payload(_now_ms() + self.HOUR_MS, "302"))
        await _post_events(hass, slow["token"], self._payload(_now_ms() - 60_000, "303"))
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.world == "303"
        # A device is still guarded against its own late resends.
        await _post_events(hass, slow["token"], self._payload(_now_ms() - 120_000, "304"))
        assert acct.world == "303"

    @pytest.mark.asyncio
    async def test_stale_resend_refreshes_presence(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(2_000, "302"))
        acct = store.get_or_create(None, "PlayerOne")
        acct.last_seen = datetime.now(timezone.utc) - timedelta(hours=1)
        acct.is_online = False
        acct.offline_reason = "timeout"

        result = await _post_events(hass, pair["token"], self._payload(1_000, "999"))

        assert result.status == 200
        assert acct.world == "302"  # the stale snapshot itself is still skipped
        assert acct.is_online is True
        assert acct.offline_reason == "online"
        assert datetime.now(timezone.utc) - acct.last_seen < timedelta(minutes=1)

    @pytest.mark.asyncio
    async def test_stale_resend_does_not_undo_logout(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(2_000, "302", [{"type": "LOGOUT"}]))
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.is_online is False

        await _post_events(hass, pair["token"], self._payload(1_000, "302"))

        assert acct.is_online is False
        assert acct.offline_reason == "logout"

    @pytest.mark.asyncio
    async def test_persisted_future_timestamp_cleared_on_load(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        store.load_dict([{
            "account_hash": "playerone",
            "player_name": "PlayerOne",
            "world": "302",
            "last_payload_ts": _now_ms() + self.DAY_MS,
        }])
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.last_payload_ts is None

        await _post_events(hass, pair["token"], self._payload(_now_ms(), "303"))
        assert acct.world == "303"

    @pytest.mark.asyncio
    async def test_device_timestamps_survive_restart(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._payload(2_000, "302"))

        restarted = AccountStore()
        restarted.load_dict(store.to_dict())
        hass.data[DOMAIN]["test_entry"][DATA_ACCOUNT_STORE] = restarted
        await _post_events(hass, pair["token"], self._payload(1_000, "999"))

        assert restarted.get_or_create(None, "PlayerOne").world == "302"


SECTIONS = ("inventory", "equipment", "health", "prayerPoints", "location", "spellbook")
SECTION_ATTRS = ("inventory", "equipment", "health", "prayer_points", "location", "spellbook")


class TestFilteredSections:
    """The plugin's per-connection filters can leave sections out."""

    def _full(self):
        payload = copy.deepcopy(FUZZ_BASE)
        payload["events"] = []
        del payload["timestamp"]
        return payload

    def _without_sections(self):
        payload = self._full()
        for section in SECTIONS:
            del payload["player"][section]
        payload["player"]["world"] = "303"
        return payload

    @pytest.mark.asyncio
    async def test_missing_sections_keep_last_known_values(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._full())
        acct = store.get_or_create(None, "PlayerOne")
        before = {attr: copy.deepcopy(getattr(acct, attr)) for attr in SECTION_ATTRS}
        assert acct.location == {"x": 3200, "y": 3200, "plane": 0}

        await _post_events(hass, pair["token"], self._without_sections())

        assert acct.world == "303"  # the snapshot itself was applied
        for attr, value in before.items():
            assert getattr(acct, attr) == value, attr
        assert acct.received_sections == set()

    @pytest.mark.asyncio
    async def test_sections_received_again(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._full())
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.received_sections == set(SECTIONS)
        await _post_events(hass, pair["token"], self._without_sections())
        await _post_events(hass, pair["token"], self._full())
        assert acct.received_sections == set(SECTIONS)

    @pytest.mark.asyncio
    async def test_empty_section_still_clears(self):
        hass, store, _, pair = _paired(_make_hass_with_pairing())
        await _post_events(hass, pair["token"], self._full())
        emptied = self._full()
        emptied["player"]["inventory"] = {"items": []}
        await _post_events(hass, pair["token"], emptied)
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.inventory == []
        assert "inventory" in acct.received_sections


class TestPairRateLimit:
    """/api/osrs-data/pair needs no auth, so failed codes are limited per IP."""

    IP = "203.0.113.7"

    def _request(self, hass, code, ip=IP):
        request = _make_json_request(hass, {"code": code})
        request.remote = ip
        return request

    async def _fail(self, hass, view, times, ip=IP):
        for _ in range(times):
            assert (await view.post(self._request(hass, "00000", ip))).status == 403

    @pytest.mark.asyncio
    async def test_eleventh_attempt_after_ten_failures_is_limited(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        view = OsrsPairView()
        await self._fail(hass, view, 10)

        # Even a valid code is refused while the IP is limited.
        code = pairing_store.create_pairing_code()
        result = await view.post(self._request(hass, code))

        assert result.status == 429
        body = json.loads(result.body)
        assert body["ok"] is False
        assert "Too many pairing attempts" in body["error"]
        assert 0 < int(result.headers["Retry-After"]) <= 600

    @pytest.mark.asyncio
    async def test_other_ip_is_not_limited(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        view = OsrsPairView()
        await self._fail(hass, view, 10)
        code = pairing_store.create_pairing_code()
        result = await view.post(self._request(hass, code, ip="198.51.100.1"))
        assert result.status == 200

    @pytest.mark.asyncio
    async def test_successful_pairings_are_not_counted(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        view = OsrsPairView()
        for _ in range(12):
            code = pairing_store.create_pairing_code()
            assert (await view.post(self._request(hass, code))).status == 200

    @pytest.mark.asyncio
    async def test_limit_expires_after_window(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        view = OsrsPairView()
        clock = [1_000.0]
        with patch("custom_components.osrs_data.pairing.time.monotonic", lambda: clock[0]):
            await self._fail(hass, view, 10)
            clock[0] += 599
            assert (await view.post(self._request(hass, "00000"))).status == 429
            clock[0] += 2
            code = pairing_store.create_pairing_code()
            assert (await view.post(self._request(hass, code))).status == 200
