"""WebOS SSAP protocol constants.

The handshake manifest and the SSAP URIs below are taken from LGTV Companion by
Jörgen Persson (https://github.com/JPersson77/LGTVCompanion, MIT) —
``Common/lg_api.h``, ``LG_HANDSHAKE_*_V3`` / ``JSON_*``. Kept as data so the
pairing payload stays byte-compatible with what the TVs already accept.
"""

from __future__ import annotations

import json

# Permissions from LG_HANDSHAKE_NOTPAIRED_V3 in Common/lg_api.h (order preserved).
_PERMISSIONS = [
    "LAUNCH",
    "LAUNCH_WEBAPP",
    "APP_TO_APP",
    "CLOSE",
    "TEST_OPEN",
    "TEST_PROTECTED",
    "CONTROL_AUDIO",
    "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK",
    "CONTROL_INPUT_MEDIA_RECORDING",
    "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_TV",
    "CONTROL_POWER",
    "CONTROL_TV_SCREEN",
    "READ_APP_STATUS",
    "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST",
    "READ_NETWORK_STATE",
    "READ_RUNNING_APPS",
    "READ_TV_CHANNEL_LIST",
    "WRITE_NOTIFICATION_TOAST",
    "READ_POWER_STATE",
    "READ_COUNTRY_INFO",
    "READ_SETTINGS",
    "CONTROL_INPUT_TEXT",
    "CONTROL_MOUSE_AND_KEYBOARD",
    "WRITE_SETTINGS",
    "WRITE_NOTIFICATION_ALERT",
    "READ_INSTALLED_APPS",
    "READ_RUNNING_APPS",
    "READ_UPDATE_INFO",
]

REGISTER_ID = "register_0"

# SSAP request URIs (from Common/lg_api.h).
URI_SCREEN_ON = "ssap://com.webos.service.tvpower/power/turnOnScreen"
URI_SCREEN_OFF = "ssap://com.webos.service.tvpower/power/turnOffScreen"
URI_POWER_OFF = "ssap://system/turnOff"
URI_GET_POWER_STATE = "ssap://com.webos.service.tvpower/power/getPowerState"

# Luna alert used by the upstream client to turn on the TV's own Wake-on-LAN
# setting right after pairing (JSON_LUNA_SET_WOL).
ENABLE_WOL_REQUEST = json.loads(
    '{"id":"luna_request","payload":{"buttons":[{"label":"","onClick":'
    '"luna://com.webos.settingsservice/setSystemSettings","params":{"category":'
    '"network","settings":{"wolwowlOnOff":"true"}}}],"message":" ","onclose":'
    '{"params":{"category":"network","settings":{"wolwowlOnOff":"true"}},"uri":'
    '"luna://com.webos.settingsservice/setSystemSettings"},"onfail":{"params":'
    '{"category":"network","settings":{"wolwowlOnOff":"true"}},"uri":'
    '"luna://com.webos.settingsservice/setSystemSettings"}},"type":"request",'
    '"uri":"ssap://system.notifications/createAlert"}'
)


def register_payload(client_key: str | None) -> dict:
    """Build the ``type: register`` handshake frame (paired if a key is given)."""
    payload: dict = {"forcePairing": False, "pairingType": "PROMPT"}
    if client_key:
        payload["client-key"] = client_key
    payload["manifest"] = {"manifestVersion": 1, "permissions": list(_PERMISSIONS)}
    return {"type": "register", "id": REGISTER_ID, "payload": payload}


def request(uri: str, payload: dict | None = None, req_id: str = "") -> dict:
    """Build a ``type: request`` frame."""
    return {
        "type": "request",
        "id": req_id,
        "uri": uri,
        "payload": payload or {},
    }
