//! Scans the module chain (74HC165 switch inputs, 74HC595 LED outputs) with PIO0.
//!
//! See docs/design.md, "Shift register bit assignment" and "Scan timing". One scan:
//!
//! 1. LATCH low: every 165 loads its inputs.
//! 2. LATCH high: every 595 copies what was shifted in during the previous scan to its outputs.
//! 3. 8 × MAX_PEDALS times: set LED_DATA, sample SW_DATA, pulse CLK high.
//!
//! The firmware always clocks MAX_PEDALS bytes, whatever the number of modules. Switch bytes
//! after the last module read 0 (the end-of-chain pull-down), which is how the module count is
//! found. LED bytes go out last module first, so the final bytes sent are the ones that stay in
//! the chain: whatever the chain length, module k ends up holding `leds[k]`.

use footswitch_core::MAX_PEDALS;
use rp2040_hal::gpio::{FunctionPio0, Pin, PullDown, PullNone, bank0};
use rp2040_hal::pac::{PIO0, RESETS};
use rp2040_hal::pio::{PIOBuilder, PIOExt, PinDir, Rx, SM0, ShiftDirection, Tx};

pub type ClkPin = Pin<bank0::Gpio16, FunctionPio0, PullNone>;
pub type LatchPin = Pin<bank0::Gpio17, FunctionPio0, PullNone>;
pub type LedDataPin = Pin<bank0::Gpio18, FunctionPio0, PullNone>;
pub type SwDataPin = Pin<bank0::Gpio19, FunctionPio0, PullDown>;

const CLK: u8 = 16; // side-set bit 0
const LATCH: u8 = 17; // side-set bit 1
const LED_DATA: u8 = 18; // OUT pin
const SW_DATA: u8 = 19; // IN pin

pub struct Chain {
    tx: Tx<(PIO0, SM0)>,
    rx: Rx<(PIO0, SM0)>,
    _pins: (ClkPin, LatchPin, LedDataPin, SwDataPin),
}

impl Chain {
    pub fn new(
        pio0: PIO0,
        resets: &mut RESETS,
        pins: (ClkPin, LatchPin, LedDataPin, SwDataPin),
    ) -> Self {
        // Side-set bits: 0 = CLK, 1 = LATCH. LATCH idles high, CLK idles low.
        // TX FIFO: first the byte count minus one, then one LED byte per word (in bits 31..24).
        // RX FIFO: one switch byte per word (bits 7..0, the first bit read in bit 7).
        let program = pio_proc::pio_asm!(
            ".side_set 2",
            ".wrap_target",
            "    pull block          side 0b10",     // byte count - 1
            "    mov y, osr          side 0b10",
            "    nop                 side 0b00 [7]", // LATCH low: 165s load
            "    nop                 side 0b10 [7]", // LATCH high: 595s update
            "byteloop:",
            "    pull block          side 0b10",     // next LED byte
            "    set x, 7            side 0b10",
            "bitloop:",
            "    out pins, 1         side 0b10 [1]", // LED_DATA
            "    in pins, 1          side 0b10 [1]", // sample SW_DATA
            "    jmp x-- bitloop     side 0b11 [2]", // CLK high: both chains shift
            "    push block          side 0b10",
            "    jmp y-- byteloop    side 0b10",
            ".wrap",
        );

        let (mut pio, sm0, _, _, _) = pio0.split(resets);
        let installed = pio.install(&program.program).unwrap();
        // 125 MHz / 31.25 = 4 MHz PIO clock. A bit takes 7 PIO cycles, so CLK runs at about
        // 570 kHz: slow, for margin on long ribbon chains. 16 modules scan in about 250 µs.
        let (mut sm, rx, tx) = PIOBuilder::from_installed_program(installed)
            .side_set_pin_base(CLK)
            .out_pins(LED_DATA, 1)
            .in_pin_base(SW_DATA)
            .out_shift_direction(ShiftDirection::Left)
            .in_shift_direction(ShiftDirection::Left)
            .autopull(false)
            .autopush(false)
            .clock_divisor_fixed_point(31, 64)
            .build(sm0);
        sm.set_pindirs([
            (CLK, PinDir::Output),
            (LATCH, PinDir::Output),
            (LED_DATA, PinDir::Output),
            (SW_DATA, PinDir::Input),
        ]);
        sm.start();
        // Dropping `pio` here is fine: the state machine and its program keep running.

        Chain { tx, rx, _pins: pins }
    }

    /// Runs one scan: shows `leds` (module 1 first; bit 0 red, 1 green, 2 blue) after the next
    /// latch, and returns the switch bytes read (module 1 first).
    ///
    /// LEDs lag one scan behind: the 595s latch the data at the start of the next scan.
    pub fn scan(&mut self, leds: &[u8; MAX_PEDALS]) -> [u8; MAX_PEDALS] {
        let mut switches = [0u8; MAX_PEDALS];
        while !self.tx.write((MAX_PEDALS - 1) as u32) {}
        let (mut sent, mut got) = (0, 0);
        while got < MAX_PEDALS {
            if sent < MAX_PEDALS && self.tx.write((leds[MAX_PEDALS - 1 - sent] as u32) << 24) {
                sent += 1;
            }
            if let Some(w) = self.rx.read() {
                switches[got] = w as u8;
                got += 1;
            }
        }
        switches
    }
}
