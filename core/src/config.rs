//! Pedal configuration, its wire encoding (7-bit safe, for SysEx) and its flash format.

use crate::{MAX_PEDALS, ShortMessage};

/// LED colour. Each channel is either fully on or off, which gives 7 colours plus off.
///
/// The discriminant is the bit pattern sent to the module's 74HC595:
/// bit 0 = red (QA), bit 1 = green (QB), bit 2 = blue (QC).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Color {
    /// The LED never lights.
    Off = 0b000,
    #[default]
    Red = 0b001,
    Green = 0b010,
    Yellow = 0b011,
    Blue = 0b100,
    Magenta = 0b101,
    Cyan = 0b110,
    White = 0b111,
}

impl Color {
    pub const ALL: [Color; 8] = [
        Color::Off,
        Color::Red,
        Color::Green,
        Color::Yellow,
        Color::Blue,
        Color::Magenta,
        Color::Cyan,
        Color::White,
    ];

    /// The 595 bits for this colour (bit 0 red, bit 1 green, bit 2 blue).
    pub const fn bits(self) -> u8 {
        self as u8
    }

    pub const fn from_bits(bits: u8) -> Option<Color> {
        if bits < 8 { Some(Color::ALL[bits as usize]) } else { None }
    }

    pub const fn name(self) -> &'static str {
        match self {
            Color::Off => "off",
            Color::Red => "red",
            Color::Green => "green",
            Color::Yellow => "yellow",
            Color::Blue => "blue",
            Color::Magenta => "magenta",
            Color::Cyan => "cyan",
            Color::White => "white",
        }
    }
}

/// How the pedal reacts to the (momentary) footswitch.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Mode {
    /// Active while the switch is held down. Sends the "on" message on press and the "off"
    /// message on release.
    #[default]
    Momentary = 0,
    /// Each press toggles the pedal. Sends "on" when it turns on, "off" when it turns off.
    Latch = 1,
}

impl Mode {
    pub const fn from_u8(v: u8) -> Option<Mode> {
        match v {
            0 => Some(Mode::Momentary),
            1 => Some(Mode::Latch),
            _ => None,
        }
    }
}

/// The MIDI message a pedal sends. Channels are 0–15 here (MIDI channel 1 is 0).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Message {
    /// Send nothing. The LED still follows the pedal state.
    None,
    /// Note On (velocity `velocity`) when the pedal turns on, Note Off when it turns off.
    Note { channel: u8, note: u8, velocity: u8 },
    /// Control Change with `on_value` when the pedal turns on, `off_value` when it turns off.
    ControlChange { channel: u8, controller: u8, on_value: u8, off_value: u8 },
    /// Program Change when the pedal turns on. Nothing when it turns off.
    ProgramChange { channel: u8, program: u8 },
}

impl Message {
    /// The message to send when the pedal turns on.
    pub fn on_message(&self) -> Option<ShortMessage> {
        match *self {
            Message::None => None,
            Message::Note { channel, note, velocity } => {
                // Velocity 0 would be read as a Note Off.
                Some(ShortMessage::new3(0x90 | (channel & 0x0F), note, velocity.max(1)))
            }
            Message::ControlChange { channel, controller, on_value, .. } => {
                Some(ShortMessage::new3(0xB0 | (channel & 0x0F), controller, on_value))
            }
            Message::ProgramChange { channel, program } => {
                Some(ShortMessage::new2(0xC0 | (channel & 0x0F), program))
            }
        }
    }

    /// The message to send when the pedal turns off.
    pub fn off_message(&self) -> Option<ShortMessage> {
        match *self {
            Message::None | Message::ProgramChange { .. } => None,
            Message::Note { channel, note, .. } => {
                Some(ShortMessage::new3(0x80 | (channel & 0x0F), note, 0))
            }
            Message::ControlChange { channel, controller, off_value, .. } => {
                Some(ShortMessage::new3(0xB0 | (channel & 0x0F), controller, off_value))
            }
        }
    }

    /// True if every field is in range (channel 0–15, data 0–127, note velocity 1–127).
    pub fn is_valid(&self) -> bool {
        match *self {
            Message::None => true,
            Message::Note { channel, note, velocity } => {
                channel < 16 && note < 128 && (1..128).contains(&velocity)
            }
            Message::ControlChange { channel, controller, on_value, off_value } => {
                channel < 16 && controller < 128 && on_value < 128 && off_value < 128
            }
            Message::ProgramChange { channel, program } => channel < 16 && program < 128,
        }
    }
}

/// Everything about one pedal.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct PedalConfig {
    pub mode: Mode,
    /// The LED colour while the pedal is on. The LED is off while the pedal is off.
    pub color: Color,
    pub message: Message,
}

impl PedalConfig {
    /// Encoded size in bytes. Every byte is 0–127, so it can go into a SysEx message as-is.
    pub const ENCODED_LEN: usize = 7;

    /// The factory default for pedal `index`: momentary, red, and CC 102 + index on channel 1,
    /// value 127 on / 0 off. CCs 102–119 are undefined in the MIDI spec, so they don't clash
    /// with anything a synth already listens to.
    pub const fn default_for(index: usize) -> Self {
        PedalConfig {
            mode: Mode::Momentary,
            color: Color::Red,
            message: Message::ControlChange {
                channel: 0,
                controller: 102 + index as u8,
                on_value: 127,
                off_value: 0,
            },
        }
    }

    pub fn is_valid(&self) -> bool {
        self.message.is_valid()
    }

    /// Layout: `[mode, color, kind, channel, a, b, c]`, where kind is 0 none, 1 note, 2 CC,
    /// 3 program change, and a/b/c are note/velocity/0, controller/on/off or program/0/0.
    pub fn encode(&self) -> [u8; Self::ENCODED_LEN] {
        let (kind, ch, a, b, c) = match self.message {
            Message::None => (0, 0, 0, 0, 0),
            Message::Note { channel, note, velocity } => (1, channel, note, velocity, 0),
            Message::ControlChange { channel, controller, on_value, off_value } => {
                (2, channel, controller, on_value, off_value)
            }
            Message::ProgramChange { channel, program } => (3, channel, program, 0, 0),
        };
        [self.mode as u8, self.color.bits(), kind, ch, a, b, c].map(|v| v & 0x7F)
    }

    /// Decodes [`encode`](Self::encode)'s output. Returns `None` if anything is out of range.
    pub fn decode(bytes: &[u8]) -> Option<Self> {
        let &[mode, color, kind, channel, a, b, c] = bytes.get(..Self::ENCODED_LEN)? else {
            return None;
        };
        let message = match kind {
            0 => Message::None,
            1 => Message::Note { channel, note: a, velocity: b },
            2 => Message::ControlChange { channel, controller: a, on_value: b, off_value: c },
            3 => Message::ProgramChange { channel, program: a },
            _ => return None,
        };
        let cfg = PedalConfig {
            mode: Mode::from_u8(mode)?,
            color: Color::from_bits(color)?,
            message,
        };
        cfg.is_valid().then_some(cfg)
    }
}

/// Settings that apply to the whole device.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct Settings {
    /// Read the footswitches the other way round. Use this if the switch's NO and NC pins turn
    /// out to be swapped, so the pedal reads as pressed while it is up.
    pub invert_switches: bool,
}

impl Settings {
    pub const ENCODED_LEN: usize = 1;

    pub fn encode(&self) -> [u8; Self::ENCODED_LEN] {
        [self.invert_switches as u8]
    }

    pub fn decode(bytes: &[u8]) -> Option<Self> {
        match bytes.first()? {
            0 => Some(Settings { invert_switches: false }),
            1 => Some(Settings { invert_switches: true }),
            _ => None,
        }
    }
}

/// The whole device configuration.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Config {
    pub settings: Settings,
    pub pedals: [PedalConfig; MAX_PEDALS],
}

impl Default for Config {
    fn default() -> Self {
        let mut pedals = [PedalConfig::default_for(0); MAX_PEDALS];
        let mut i = 0;
        while i < MAX_PEDALS {
            pedals[i] = PedalConfig::default_for(i);
            i += 1;
        }
        Config { settings: Settings::default(), pedals }
    }
}

const MAGIC: [u8; 4] = *b"FSWc";
const FORMAT_VERSION: u8 = 1;

impl Config {
    /// Size of the flash image: magic, format version, settings, pedals, checksum.
    pub const STORED_LEN: usize =
        MAGIC.len() + 1 + Settings::ENCODED_LEN + MAX_PEDALS * PedalConfig::ENCODED_LEN + 2;

    /// Serialises the config for flash. Bytes after `STORED_LEN` are left untouched.
    pub fn store(&self, out: &mut [u8]) {
        let out = &mut out[..Self::STORED_LEN];
        out[..4].copy_from_slice(&MAGIC);
        out[4] = FORMAT_VERSION;
        let mut pos = 5;
        out[pos..pos + Settings::ENCODED_LEN].copy_from_slice(&self.settings.encode());
        pos += Settings::ENCODED_LEN;
        for p in &self.pedals {
            out[pos..pos + PedalConfig::ENCODED_LEN].copy_from_slice(&p.encode());
            pos += PedalConfig::ENCODED_LEN;
        }
        let sum = fletcher16(&out[..pos]);
        out[pos..pos + 2].copy_from_slice(&sum.to_le_bytes());
    }

    /// Reads a config written by [`store`](Self::store). Returns `None` for erased flash, a
    /// different format version, a bad checksum or out-of-range values.
    pub fn load(bytes: &[u8]) -> Option<Self> {
        let bytes = bytes.get(..Self::STORED_LEN)?;
        if bytes[..4] != MAGIC || bytes[4] != FORMAT_VERSION {
            return None;
        }
        let body = Self::STORED_LEN - 2;
        if fletcher16(&bytes[..body]).to_le_bytes() != bytes[body..] {
            return None;
        }
        let mut pos = 5;
        let settings = Settings::decode(&bytes[pos..])?;
        pos += Settings::ENCODED_LEN;
        let mut cfg = Config { settings, ..Config::default() };
        for p in cfg.pedals.iter_mut() {
            *p = PedalConfig::decode(&bytes[pos..])?;
            pos += PedalConfig::ENCODED_LEN;
        }
        Some(cfg)
    }
}

fn fletcher16(data: &[u8]) -> u16 {
    let (mut a, mut b) = (0u16, 0u16);
    for &d in data {
        a = (a + d as u16) % 255;
        b = (b + a) % 255;
    }
    (b << 8) | a
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pedal_roundtrip() {
        let cases = [
            PedalConfig::default_for(3),
            PedalConfig {
                mode: Mode::Latch,
                color: Color::Cyan,
                message: Message::Note { channel: 9, note: 36, velocity: 100 },
            },
            PedalConfig {
                mode: Mode::Momentary,
                color: Color::Off,
                message: Message::ProgramChange { channel: 15, program: 127 },
            },
            PedalConfig { mode: Mode::Latch, color: Color::White, message: Message::None },
        ];
        for c in cases {
            let enc = c.encode();
            assert!(enc.iter().all(|&b| b < 0x80));
            assert_eq!(PedalConfig::decode(&enc), Some(c));
        }
    }

    #[test]
    fn pedal_decode_rejects_bad_values() {
        assert_eq!(PedalConfig::decode(&[2, 1, 2, 0, 1, 2, 3]), None); // mode
        assert_eq!(PedalConfig::decode(&[0, 8, 2, 0, 1, 2, 3]), None); // colour
        assert_eq!(PedalConfig::decode(&[0, 1, 4, 0, 1, 2, 3]), None); // kind
        assert_eq!(PedalConfig::decode(&[0, 1, 2, 16, 1, 2, 3]), None); // channel
        assert_eq!(PedalConfig::decode(&[0, 1, 1, 0, 60, 0, 0]), None); // velocity 0
        assert_eq!(PedalConfig::decode(&[0, 1, 2, 0, 1, 2]), None); // short
    }

    #[test]
    fn messages() {
        let n = Message::Note { channel: 1, note: 60, velocity: 90 };
        assert_eq!(n.on_message().unwrap().as_bytes(), &[0x91, 60, 90]);
        assert_eq!(n.off_message().unwrap().as_bytes(), &[0x81, 60, 0]);
        let c = Message::ControlChange { channel: 0, controller: 64, on_value: 127, off_value: 0 };
        assert_eq!(c.on_message().unwrap().as_bytes(), &[0xB0, 64, 127]);
        assert_eq!(c.off_message().unwrap().as_bytes(), &[0xB0, 64, 0]);
        let p = Message::ProgramChange { channel: 2, program: 5 };
        assert_eq!(p.on_message().unwrap().as_bytes(), &[0xC2, 5]);
        assert_eq!(p.off_message(), None);
        assert_eq!(Message::None.on_message(), None);
    }

    #[test]
    fn config_store_load() {
        let mut cfg = Config::default();
        cfg.settings.invert_switches = true;
        cfg.pedals[5].color = Color::Blue;
        cfg.pedals[5].mode = Mode::Latch;
        let mut buf = [0xFFu8; 256];
        cfg.store(&mut buf);
        assert_eq!(Config::load(&buf), Some(cfg));
        assert!(buf[Config::STORED_LEN..].iter().all(|&b| b == 0xFF));

        // Corruption is detected.
        buf[20] ^= 1;
        assert_eq!(Config::load(&buf), None);
        // Erased flash is not a config.
        assert_eq!(Config::load(&[0xFF; 256]), None);
    }

    #[test]
    fn defaults_are_red_momentary() {
        let cfg = Config::default();
        for (i, p) in cfg.pedals.iter().enumerate() {
            assert_eq!(p.color, Color::Red);
            assert_eq!(p.mode, Mode::Momentary);
            assert!(p.is_valid());
            assert_eq!(*p, PedalConfig::default_for(i));
        }
    }
}
