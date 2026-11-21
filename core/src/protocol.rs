//! The configuration protocol: SysEx messages over the device's USB MIDI port.
//!
//! Request (host → device):  `F0 7D 46 53 <command> <payload…> F7`
//! Response (device → host): `F0 7D 46 53 <command | 0x40> <status> <payload…> F7`
//!
//! `7D` is the MIDI manufacturer ID reserved for non-commercial use, and `46 53` is "FS". Every
//! request gets exactly one response with the same command number. All payload bytes are 0–127.
//!
//! | Command | Request payload        | Response payload                                   |
//! |---------|------------------------|----------------------------------------------------|
//! | 01 GetInfo         | –           | protocol, fw major/minor/patch, max pedals, connected pedals |
//! | 02 GetPedal        | index       | index, pedal config (7 bytes, see [`PedalConfig::encode`]) |
//! | 03 SetPedal        | index, pedal config | –                                          |
//! | 04 GetSettings     | –           | settings (1 byte)                                  |
//! | 05 SetSettings     | settings    | –                                                  |
//! | 06 GetState        | –           | connected, active (3 bytes), pressed (3 bytes)     |
//! | 07 Save            | –           | – (writes the config to flash)                     |
//! | 08 ResetDefaults   | –           | – (in RAM; follow with Save to keep it)            |
//! | 09 EnterBootloader | –           | – (then reboots into the RP2040's USB bootloader)  |
//!
//! The 16-bit masks in GetState are sent as 3 bytes of 7, 7 and 2 bits, low bits first.
//! SetPedal and SetSettings take effect at once but are lost at power-off unless followed by
//! Save.

use crate::config::{PedalConfig, Settings};

pub const HEADER: [u8; 4] = [0xF0, 0x7D, 0x46, 0x53];
pub const SYSEX_END: u8 = 0xF7;
pub const PROTOCOL_VERSION: u8 = 1;
/// Upper bound on any request or response, including F0 and F7.
pub const MAX_MESSAGE_LEN: usize = 24;

const RESPONSE_FLAG: u8 = 0x40;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Command {
    GetInfo = 0x01,
    GetPedal = 0x02,
    SetPedal = 0x03,
    GetSettings = 0x04,
    SetSettings = 0x05,
    GetState = 0x06,
    Save = 0x07,
    ResetDefaults = 0x08,
    EnterBootloader = 0x09,
}

impl Command {
    pub const fn from_u8(v: u8) -> Option<Command> {
        Some(match v {
            0x01 => Command::GetInfo,
            0x02 => Command::GetPedal,
            0x03 => Command::SetPedal,
            0x04 => Command::GetSettings,
            0x05 => Command::SetSettings,
            0x06 => Command::GetState,
            0x07 => Command::Save,
            0x08 => Command::ResetDefaults,
            0x09 => Command::EnterBootloader,
            _ => return None,
        })
    }
}

/// Result code in every response.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Status {
    Ok = 0,
    UnknownCommand = 1,
    /// Payload too short, too long or with out-of-range values.
    Malformed = 2,
    /// Pedal index not below the device's maximum.
    BadIndex = 3,
    /// Writing the flash failed or read back wrong.
    FlashError = 4,
}

impl Status {
    pub const fn from_u8(v: u8) -> Option<Status> {
        Some(match v {
            0 => Status::Ok,
            1 => Status::UnknownCommand,
            2 => Status::Malformed,
            3 => Status::BadIndex,
            4 => Status::FlashError,
            _ => return None,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Request {
    GetInfo,
    GetPedal { index: u8 },
    SetPedal { index: u8, config: PedalConfig },
    GetSettings,
    SetSettings(Settings),
    GetState,
    Save,
    ResetDefaults,
    EnterBootloader,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct DeviceInfo {
    pub protocol_version: u8,
    /// Major, minor, patch. Each 0–127.
    pub firmware_version: [u8; 3],
    /// How many pedals the firmware can handle.
    pub max_pedals: u8,
    /// How many modules the last scan of the chain found.
    pub connected_pedals: u8,
}

/// Live pedal state. Bit `i` is pedal `i`.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct PedalStates {
    pub connected: u8,
    /// Pedal is on: held down (momentary) or latched on (latch). Its LED is lit.
    pub active: u16,
    /// The footswitch is physically held down (after debouncing).
    pub pressed: u16,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Response {
    Info(DeviceInfo),
    Pedal { index: u8, config: PedalConfig },
    Settings(Settings),
    State(PedalStates),
    /// Reply to a command that returns no data.
    Done,
}

/// Why a SysEx message could not be decoded as a request.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequestError {
    /// Not a message in this protocol (other manufacturer, or a response). Ignore it.
    NotOurs,
    /// Ours, but invalid. Reply with this status for `command`.
    Invalid { command: u8, status: Status },
}

/// A fixed-size output buffer for one SysEx message.
pub struct Buf {
    data: [u8; MAX_MESSAGE_LEN],
    len: usize,
}

impl Buf {
    fn new() -> Self {
        Buf { data: [0; MAX_MESSAGE_LEN], len: 0 }
    }

    fn push(&mut self, b: u8) {
        self.data[self.len] = b;
        self.len += 1;
    }

    fn extend(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.push(b);
        }
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.data[..self.len]
    }
}

fn u16_to_7bit(v: u16) -> [u8; 3] {
    [(v & 0x7F) as u8, ((v >> 7) & 0x7F) as u8, ((v >> 14) & 0x03) as u8]
}

fn u16_from_7bit(b: &[u8]) -> u16 {
    (b[0] as u16) | ((b[1] as u16) << 7) | ((b[2] as u16) << 14)
}

/// Strips header and F7. Returns the bytes in between, if this is one of our messages.
fn body(msg: &[u8]) -> Option<&[u8]> {
    let rest = msg.strip_prefix(&HEADER)?;
    let rest = rest.strip_suffix(&[SYSEX_END])?;
    // Every byte inside must be a data byte.
    rest.iter().all(|&b| b < 0x80).then_some(rest)
}

impl Request {
    pub fn command(&self) -> Command {
        match self {
            Request::GetInfo => Command::GetInfo,
            Request::GetPedal { .. } => Command::GetPedal,
            Request::SetPedal { .. } => Command::SetPedal,
            Request::GetSettings => Command::GetSettings,
            Request::SetSettings(_) => Command::SetSettings,
            Request::GetState => Command::GetState,
            Request::Save => Command::Save,
            Request::ResetDefaults => Command::ResetDefaults,
            Request::EnterBootloader => Command::EnterBootloader,
        }
    }

    /// The complete SysEx message, F0 to F7.
    pub fn encode(&self) -> Buf {
        let mut b = Buf::new();
        b.extend(&HEADER);
        b.push(self.command() as u8);
        match self {
            Request::GetPedal { index } => b.push(index & 0x7F),
            Request::SetPedal { index, config } => {
                b.push(index & 0x7F);
                b.extend(&config.encode());
            }
            Request::SetSettings(s) => b.extend(&s.encode()),
            _ => {}
        }
        b.push(SYSEX_END);
        b
    }

    /// Decodes a complete SysEx message, F0 to F7.
    pub fn decode(msg: &[u8]) -> Result<Request, RequestError> {
        let body = body(msg).ok_or(RequestError::NotOurs)?;
        let (&cmd, payload) = body.split_first().ok_or(RequestError::NotOurs)?;
        if cmd & RESPONSE_FLAG != 0 {
            return Err(RequestError::NotOurs);
        }
        let invalid = |status| RequestError::Invalid { command: cmd, status };
        let command = Command::from_u8(cmd).ok_or(invalid(Status::UnknownCommand))?;
        let expect_len = |n: usize| {
            if payload.len() == n { Ok(()) } else { Err(invalid(Status::Malformed)) }
        };
        Ok(match command {
            Command::GetInfo => expect_len(0).map(|_| Request::GetInfo)?,
            Command::GetPedal => {
                expect_len(1)?;
                Request::GetPedal { index: payload[0] }
            }
            Command::SetPedal => {
                expect_len(1 + PedalConfig::ENCODED_LEN)?;
                let config =
                    PedalConfig::decode(&payload[1..]).ok_or(invalid(Status::Malformed))?;
                Request::SetPedal { index: payload[0], config }
            }
            Command::GetSettings => expect_len(0).map(|_| Request::GetSettings)?,
            Command::SetSettings => {
                expect_len(Settings::ENCODED_LEN)?;
                Request::SetSettings(Settings::decode(payload).ok_or(invalid(Status::Malformed))?)
            }
            Command::GetState => expect_len(0).map(|_| Request::GetState)?,
            Command::Save => expect_len(0).map(|_| Request::Save)?,
            Command::ResetDefaults => expect_len(0).map(|_| Request::ResetDefaults)?,
            Command::EnterBootloader => expect_len(0).map(|_| Request::EnterBootloader)?,
        })
    }
}

/// Encodes the response to command byte `command`. An `Err` status carries no payload.
pub fn encode_response(command: u8, result: Result<&Response, Status>) -> Buf {
    let mut b = Buf::new();
    b.extend(&HEADER);
    b.push((command & 0x3F) | RESPONSE_FLAG);
    match result {
        Err(status) => b.push(status as u8),
        Ok(resp) => {
            b.push(Status::Ok as u8);
            match resp {
                Response::Info(i) => b.extend(&[
                    i.protocol_version & 0x7F,
                    i.firmware_version[0] & 0x7F,
                    i.firmware_version[1] & 0x7F,
                    i.firmware_version[2] & 0x7F,
                    i.max_pedals & 0x7F,
                    i.connected_pedals & 0x7F,
                ]),
                Response::Pedal { index, config } => {
                    b.push(index & 0x7F);
                    b.extend(&config.encode());
                }
                Response::Settings(s) => b.extend(&s.encode()),
                Response::State(s) => {
                    b.push(s.connected & 0x7F);
                    b.extend(&u16_to_7bit(s.active));
                    b.extend(&u16_to_7bit(s.pressed));
                }
                Response::Done => {}
            }
        }
    }
    b.push(SYSEX_END);
    b
}

/// A decoded response: which command it answers, and the result.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Reply {
    pub command: u8,
    pub result: Result<Response, Status>,
}

/// Decodes a complete SysEx response. Returns `None` if it isn't a well-formed response in
/// this protocol.
pub fn decode_response(msg: &[u8]) -> Option<Reply> {
    let body = body(msg)?;
    let (&cmd, rest) = body.split_first()?;
    if cmd & RESPONSE_FLAG == 0 {
        return None;
    }
    let command = cmd & !RESPONSE_FLAG;
    let (&status, p) = rest.split_first()?;
    let status = Status::from_u8(status)?;
    if status != Status::Ok {
        return p.is_empty().then_some(Reply { command, result: Err(status) });
    }
    let resp = match Command::from_u8(command) {
        Some(Command::GetInfo) if p.len() == 6 => Response::Info(DeviceInfo {
            protocol_version: p[0],
            firmware_version: [p[1], p[2], p[3]],
            max_pedals: p[4],
            connected_pedals: p[5],
        }),
        Some(Command::GetPedal) if p.len() == 1 + PedalConfig::ENCODED_LEN => {
            Response::Pedal { index: p[0], config: PedalConfig::decode(&p[1..])? }
        }
        Some(Command::GetSettings) if p.len() == Settings::ENCODED_LEN => {
            Response::Settings(Settings::decode(p)?)
        }
        Some(Command::GetState) if p.len() == 7 => Response::State(PedalStates {
            connected: p[0],
            active: u16_from_7bit(&p[1..4]),
            pressed: u16_from_7bit(&p[4..7]),
        }),
        Some(
            Command::SetPedal
            | Command::SetSettings
            | Command::Save
            | Command::ResetDefaults
            | Command::EnterBootloader,
        ) if p.is_empty() => Response::Done,
        _ => return None,
    };
    Some(Reply { command, result: Ok(resp) })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Color, Message, Mode};

    fn all_requests() -> [Request; 9] {
        [
            Request::GetInfo,
            Request::GetPedal { index: 7 },
            Request::SetPedal {
                index: 15,
                config: PedalConfig {
                    mode: Mode::Latch,
                    color: Color::Magenta,
                    message: Message::Note { channel: 9, note: 38, velocity: 127 },
                },
            },
            Request::GetSettings,
            Request::SetSettings(Settings { invert_switches: true }),
            Request::GetState,
            Request::Save,
            Request::ResetDefaults,
            Request::EnterBootloader,
        ]
    }

    #[test]
    fn request_roundtrip() {
        for r in all_requests() {
            let enc = r.encode();
            let bytes = enc.as_bytes();
            assert_eq!(bytes[0], 0xF0);
            assert_eq!(*bytes.last().unwrap(), 0xF7);
            assert!(bytes[1..bytes.len() - 1].iter().all(|&b| b < 0x80));
            assert_eq!(Request::decode(bytes), Ok(r));
        }
    }

    #[test]
    fn request_errors() {
        // Another manufacturer.
        assert_eq!(Request::decode(&[0xF0, 0x41, 0x10, 0xF7]), Err(RequestError::NotOurs));
        // Unknown command.
        assert_eq!(
            Request::decode(&[0xF0, 0x7D, 0x46, 0x53, 0x30, 0xF7]),
            Err(RequestError::Invalid { command: 0x30, status: Status::UnknownCommand })
        );
        // Missing payload.
        assert_eq!(
            Request::decode(&[0xF0, 0x7D, 0x46, 0x53, 0x02, 0xF7]),
            Err(RequestError::Invalid { command: 0x02, status: Status::Malformed })
        );
        // A response is not a request.
        let resp = encode_response(1, Ok(&Response::Done));
        assert_eq!(Request::decode(resp.as_bytes()), Err(RequestError::NotOurs));
    }

    #[test]
    fn response_roundtrip() {
        let cases = [
            (
                Command::GetInfo,
                Response::Info(DeviceInfo {
                    protocol_version: 1,
                    firmware_version: [0, 1, 2],
                    max_pedals: 16,
                    connected_pedals: 4,
                }),
            ),
            (
                Command::GetPedal,
                Response::Pedal { index: 2, config: PedalConfig::default_for(2) },
            ),
            (Command::GetSettings, Response::Settings(Settings { invert_switches: true })),
            (
                Command::GetState,
                Response::State(PedalStates { connected: 16, active: 0xA5C3, pressed: 0xFFFF }),
            ),
            (Command::Save, Response::Done),
        ];
        for (cmd, resp) in cases {
            let enc = encode_response(cmd as u8, Ok(&resp));
            assert!(enc.as_bytes().len() <= MAX_MESSAGE_LEN);
            assert_eq!(
                decode_response(enc.as_bytes()),
                Some(Reply { command: cmd as u8, result: Ok(resp) })
            );
        }
        let enc = encode_response(3, Err(Status::BadIndex));
        assert_eq!(
            decode_response(enc.as_bytes()),
            Some(Reply { command: 3, result: Err(Status::BadIndex) })
        );
    }

    #[test]
    fn longest_message_fits() {
        let r = all_requests()[2].encode();
        assert!(r.as_bytes().len() <= MAX_MESSAGE_LEN);
    }
}
