//! Keeps the config in the last 4 KiB sector of the Pico's 2 MiB flash. memory.x leaves that
//! sector out of the program area.

use footswitch_core::Config;

const FLASH_SIZE: u32 = 2 * 1024 * 1024;
const SECTOR_SIZE: usize = 4096;
/// Offset of the config sector from the start of flash.
const CONFIG_OFFSET: u32 = FLASH_SIZE - SECTOR_SIZE as u32;
/// Flash is memory-mapped (XIP) at this address.
const XIP_BASE: u32 = 0x1000_0000;

/// The saved config, or `None` if nothing valid was saved (new board, or a format change).
pub fn load() -> Option<Config> {
    // SAFETY: the sector is inside the mapped flash and no one writes it while we read.
    let bytes = unsafe {
        core::slice::from_raw_parts((XIP_BASE + CONFIG_OFFSET) as *const u8, Config::STORED_LEN)
    };
    Config::load(bytes)
}

/// Writes `cfg` to flash and checks it reads back. Takes about 50 ms, during which nothing else
/// runs (no USB polling, no scans); the USB host just sees NAKs for that time.
pub fn save(cfg: &Config) -> Result<(), ()> {
    let mut buf = [0xFFu8; SECTOR_SIZE];
    cfg.store(&mut buf);
    // SAFETY: interrupts are off, core 1 is not running and there is no DMA, so nothing touches
    // flash while XIP is down. The offset and length are sector aligned.
    cortex_m::interrupt::free(|_| unsafe {
        rp2040_flash::flash::flash_range_erase_and_program(CONFIG_OFFSET, &buf, true);
    });
    if load().as_ref() == Some(cfg) { Ok(()) } else { Err(()) }
}
