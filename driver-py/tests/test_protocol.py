"""Protocol tests. The byte vectors come from the Rust ``footswitch-core`` encoder, so these
check that the port produces and reads exactly the same bytes."""

from footswitch import (
    Color, Command, ControlChange, DeviceInfo, Done, Mode, NoMessage, Note, PedalConfig,
    PedalStates, ProgramChange, Reply, Request, Settings, Status, decode_response,
)


def h(s: str) -> bytes:
    return bytes.fromhex(s)


def test_requests_encode_like_rust():
    cases = [
        (Request(Command.GET_INFO), "F0 7D 46 53 01 F7"),
        (Request(Command.GET_PEDAL, index=7), "F0 7D 46 53 02 07 F7"),
        (
            Request(Command.SET_PEDAL, index=15, config=PedalConfig(Mode.LATCH, Color.MAGENTA, Note(9, 38, 127))),
            "F0 7D 46 53 03 0F 01 05 01 09 26 7F 00 F7",
        ),
        (Request(Command.SET_PEDAL, index=2, config=PedalConfig.default_for(2)), "F0 7D 46 53 03 02 00 01 02 00 68 7F 00 F7"),
        (
            Request(Command.SET_PEDAL, index=0, config=PedalConfig(Mode.MOMENTARY, Color.OFF, ProgramChange(15, 127))),
            "F0 7D 46 53 03 00 00 00 03 0F 7F 00 00 F7",
        ),
        (
            Request(Command.SET_PEDAL, index=1, config=PedalConfig(Mode.LATCH, Color.WHITE, NoMessage())),
            "F0 7D 46 53 03 01 01 07 00 00 00 00 00 F7",
        ),
        (Request(Command.SET_SETTINGS, settings=Settings(invert_switches=True)), "F0 7D 46 53 05 01 F7"),
        (Request(Command.GET_STATE), "F0 7D 46 53 06 F7"),
        (Request(Command.SAVE), "F0 7D 46 53 07 F7"),
        (Request(Command.RESET_DEFAULTS), "F0 7D 46 53 08 F7"),
        (Request(Command.ENTER_BOOTLOADER), "F0 7D 46 53 09 F7"),
    ]
    for req, b in cases:
        assert req.encode() == h(b), req


def test_responses_decode_like_rust():
    ok = Status.OK
    assert decode_response(h("F0 7D 46 53 41 00 01 00 01 02 10 04 F7")) == Reply(
        Command.GET_INFO, ok, DeviceInfo(1, (0, 1, 2), 16, 4)
    )
    assert decode_response(h("F0 7D 46 53 42 00 02 00 01 02 00 68 7F 00 F7")) == Reply(
        Command.GET_PEDAL, ok, (2, PedalConfig.default_for(2))
    )
    assert decode_response(h("F0 7D 46 53 44 00 01 F7")) == Reply(Command.GET_SETTINGS, ok, Settings(True))
    assert decode_response(h("F0 7D 46 53 46 00 10 43 4B 02 7F 7F 03 F7")) == Reply(
        Command.GET_STATE, ok, PedalStates(16, 0xA5C3, 0xFFFF)
    )
    assert decode_response(h("F0 7D 46 53 47 00 F7")) == Reply(Command.SAVE, ok, Done())
    assert decode_response(h("F0 7D 46 53 43 03 F7")) == Reply(Command.SET_PEDAL, Status.BAD_INDEX, None)
    # A list of ints, as python-rtmidi delivers it.
    assert decode_response(list(h("F0 7D 46 53 47 00 F7"))).command == Command.SAVE


def test_not_ours_or_malformed():
    assert decode_response(h("F0 41 10 F7")) is None  # other manufacturer
    assert decode_response(h("F0 7D 46 53 01 F7")) is None  # a request
    assert decode_response(h("F0 7D 46 53 41 00 01 F7")) is None  # short payload
    assert decode_response(h("F0 7D 46 53 43 03 01 F7")) is None  # error with payload


def test_pedal_decode_rejects_bad_values():
    assert PedalConfig.decode(bytes([2, 1, 2, 0, 1, 2, 3])) is None  # mode
    assert PedalConfig.decode(bytes([0, 8, 2, 0, 1, 2, 3])) is None  # colour
    assert PedalConfig.decode(bytes([0, 1, 4, 0, 1, 2, 3])) is None  # kind
    assert PedalConfig.decode(bytes([0, 1, 2, 16, 1, 2, 3])) is None  # channel
    assert PedalConfig.decode(bytes([0, 1, 1, 0, 60, 0, 0])) is None  # velocity 0
    assert PedalConfig.decode(bytes([0, 1, 2, 0, 1, 2])) is None  # short
    cfg = PedalConfig(Mode.LATCH, Color.CYAN, Note(9, 36, 100))
    assert PedalConfig.decode(cfg.encode()) == cfg
    assert not PedalConfig(Mode.LATCH, Color.CYAN, ControlChange(0, 128, 0, 0)).is_valid()
