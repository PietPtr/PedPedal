//! USB-MIDI 1.0 event packets.
//!
//! USB MIDI carries MIDI in 4-byte packets: a header byte (cable number in the high nibble,
//! Code Index Number in the low nibble) and up to 3 MIDI bytes. Everything here uses cable 0.

use crate::ShortMessage;

/// The packet for a channel message (Note On/Off, CC, Program Change, …).
pub fn short_message_packet(m: &ShortMessage) -> [u8; 4] {
    // For channel voice messages the CIN equals the status byte's high nibble.
    let cin = m.status() >> 4;
    let b = m.as_bytes();
    [cin, b[0], b.get(1).copied().unwrap_or(0), b.get(2).copied().unwrap_or(0)]
}

/// Splits a complete SysEx message (F0 … F7) into USB-MIDI packets.
pub fn sysex_packets(msg: &[u8]) -> SysexPackets<'_> {
    SysexPackets { data: msg, pos: 0 }
}

pub struct SysexPackets<'a> {
    data: &'a [u8],
    pos: usize,
}

impl Iterator for SysexPackets<'_> {
    type Item = [u8; 4];

    fn next(&mut self) -> Option<[u8; 4]> {
        let rest = &self.data[self.pos..];
        let (cin, n) = match rest.len() {
            0 => return None,
            1 => (0x5, 1), // SysEx ends with 1 byte
            2 => (0x6, 2), // SysEx ends with 2 bytes
            3 => (0x7, 3), // SysEx ends with 3 bytes
            _ => (0x4, 3), // SysEx starts or continues
        };
        let mut p = [cin, 0, 0, 0];
        p[1..1 + n].copy_from_slice(&rest[..n]);
        self.pos += n;
        Some(p)
    }
}

/// Collects incoming USB-MIDI packets into complete SysEx messages. Other messages are ignored.
/// Messages longer than `N` bytes are dropped.
pub struct SysexAssembler<const N: usize> {
    buf: [u8; N],
    len: usize,
    state: State,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum State {
    Idle,
    Collecting,
    /// Too long; skip until F7.
    Overflow,
}

impl<const N: usize> Default for SysexAssembler<N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<const N: usize> SysexAssembler<N> {
    pub const fn new() -> Self {
        SysexAssembler { buf: [0; N], len: 0, state: State::Idle }
    }

    /// Feeds one packet. Returns the message (F0 … F7) when this packet completes one.
    pub fn push_packet(&mut self, p: [u8; 4]) -> Option<&[u8]> {
        let n = match p[0] & 0x0F {
            0x4 | 0x7 => 3,
            0x6 => 2,
            0x5 => 1,
            _ => return None,
        };
        for &b in &p[1..1 + n] {
            if self.feed(b) {
                return Some(&self.buf[..self.len]);
            }
        }
        None
    }

    /// Returns true when `b` completed a message.
    fn feed(&mut self, b: u8) -> bool {
        match b {
            0xF0 => {
                self.len = 0;
                self.state = State::Collecting;
                self.push(b);
                false
            }
            0xF7 => {
                if self.state == State::Collecting {
                    self.push(b);
                }
                // push() switches to Overflow if the F7 itself didn't fit.
                let complete = self.state == State::Collecting;
                self.state = State::Idle;
                complete
            }
            _ if b >= 0x80 => {
                // Any other status byte aborts a SysEx message.
                self.state = State::Idle;
                false
            }
            _ => {
                if self.state == State::Collecting {
                    self.push(b);
                }
                false
            }
        }
    }

    fn push(&mut self, b: u8) {
        if self.len < N {
            self.buf[self.len] = b;
            self.len += 1;
        } else {
            self.state = State::Overflow;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::vec::Vec;

    fn roundtrip(msg: &[u8]) -> Option<Vec<u8>> {
        let mut asm = SysexAssembler::<16>::new();
        let mut out = None;
        for p in sysex_packets(msg) {
            if let Some(m) = asm.push_packet(p) {
                out = Some(m.to_vec());
            }
        }
        out
    }

    #[test]
    fn sysex_split_and_join() {
        for len in 2usize..=16 {
            let mut msg: Vec<u8> = (0..len as u8).map(|i| i & 0x7F).collect();
            msg[0] = 0xF0;
            *msg.last_mut().unwrap() = 0xF7;
            let packets: Vec<_> = sysex_packets(&msg).collect();
            assert_eq!(packets.len(), len.div_ceil(3));
            assert_eq!(roundtrip(&msg), Some(msg));
        }
    }

    #[test]
    fn sysex_packet_cins() {
        let p: Vec<_> = sysex_packets(&[0xF0, 1, 2, 3, 0xF7]).collect();
        assert_eq!(p, [[0x4, 0xF0, 1, 2], [0x6, 3, 0xF7, 0]]);
        let p: Vec<_> = sysex_packets(&[0xF0, 1, 0xF7]).collect();
        assert_eq!(p, [[0x7, 0xF0, 1, 0xF7]]);
    }

    #[test]
    fn too_long_is_dropped_and_next_works() {
        let mut long = vec_msg(30);
        let short = vec_msg(5);
        long.extend_from_slice(&short);
        let mut asm = SysexAssembler::<16>::new();
        let mut got = Vec::new();
        for p in sysex_packets(&long[..30]).chain(sysex_packets(&short)) {
            if let Some(m) = asm.push_packet(p) {
                got.push(m.to_vec());
            }
        }
        assert_eq!(got, [short]);
    }

    #[test]
    fn other_packets_ignored() {
        let mut asm = SysexAssembler::<16>::new();
        assert_eq!(asm.push_packet([0x09, 0x90, 60, 100]), None);
        let p = short_message_packet(&ShortMessage::new3(0x90, 60, 100));
        assert_eq!(p, [0x09, 0x90, 60, 100]);
        let p = short_message_packet(&ShortMessage::new2(0xC3, 5));
        assert_eq!(p, [0x0C, 0xC3, 5, 0]);
    }

    fn vec_msg(len: usize) -> Vec<u8> {
        let mut m: Vec<u8> = (0..len).map(|i| (i as u8) & 0x7F).collect();
        m[0] = 0xF0;
        m[len - 1] = 0xF7;
        m
    }
}
