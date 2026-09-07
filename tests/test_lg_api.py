from webos_companion import lg_api


def test_register_payload_unpaired_has_no_key():
    p = lg_api.register_payload(None)
    assert p["type"] == "register"
    assert p["id"] == "register_0"
    assert "client-key" not in p["payload"]
    assert "CONTROL_POWER" in p["payload"]["manifest"]["permissions"]


def test_register_payload_paired_includes_key():
    p = lg_api.register_payload("KEY123")
    assert p["payload"]["client-key"] == "KEY123"


def test_request_frame_shape():
    r = lg_api.request(lg_api.URI_SCREEN_OFF, {"x": 1}, "req_9")
    assert r == {
        "type": "request",
        "id": "req_9",
        "uri": "ssap://com.webos.service.tvpower/power/turnOffScreen",
        "payload": {"x": 1},
    }


def test_enable_wol_request_is_valid_json_dict():
    assert lg_api.ENABLE_WOL_REQUEST["type"] == "request"
    assert "settingsservice" in lg_api.ENABLE_WOL_REQUEST["payload"]["buttons"][0]["onClick"]
