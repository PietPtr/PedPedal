// Flashes a Raspberry Pi Pico (RP2040) from the browser over WebUSB.
//
// A Pico started with BOOTSEL held runs its bootrom, which shows two USB interfaces: the
// RPI-RP2 drive and PICOBOOT, a vendor interface that reads, erases and writes flash. Browsers
// can't write files to the drive, but WebUSB (Chrome, Edge) can talk PICOBOOT, which is what
// picotool uses too. The protocol is in the RP2040 datasheet, section 2.8.5.
//
// Only the flash sectors the UF2 file covers are erased, so the saved pedal config in the last
// sector stays. A UF2 that would touch that sector is refused.

/** The bootrom's USB IDs, for navigator.usb.requestDevice({ filters }). */
export const BOOTSEL_FILTERS = [{ vendorId: 0x2e8a, productId: 0x0003 }];

export const isBootsel = (d) =>
  BOOTSEL_FILTERS.some((f) => d.vendorId === f.vendorId && d.productId === f.productId);

const FLASH_START = 0x10000000;
const FLASH_SIZE = 2 * 1024 * 1024;
const SECTOR = 4096;
/** The firmware keeps its saved config in the last flash sector (firmware/memory.x). */
const CONFIG_SECTOR = FLASH_START + FLASH_SIZE - SECTOR;
const SRAM_END = 0x20042000;

// ---- UF2 ----

const UF2_MAGIC0 = 0x0a324655;
const UF2_MAGIC1 = 0x9e5d5157;
const UF2_MAGIC_END = 0x0ab16f30;
const UF2_FLAG_NOT_MAIN_FLASH = 0x1;
const UF2_FLAG_FAMILY = 0x2000;
const RP2040_FAMILY = 0xe48bff56;

/**
 * Parses a UF2 file into the flash sectors it writes: [{ addr, data }] with 4 KiB `data`,
 * sorted by address. Bytes of a sector that the file doesn't cover are 0xFF (erased).
 */
export function parseUf2(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length === 0 || bytes.length % 512) throw new Error("Not a UF2 file (bad length).");
  const sectors = new Map();
  for (let off = 0; off < bytes.length; off += 512) {
    const v = new DataView(bytes.buffer, bytes.byteOffset + off, 512);
    if (v.getUint32(0, true) !== UF2_MAGIC0 || v.getUint32(4, true) !== UF2_MAGIC1
      || v.getUint32(508, true) !== UF2_MAGIC_END) {
      throw new Error(`Not a UF2 file (bad block at byte ${off}).`);
    }
    const flags = v.getUint32(8, true);
    if (flags & UF2_FLAG_NOT_MAIN_FLASH) continue;
    if ((flags & UF2_FLAG_FAMILY) && v.getUint32(28, true) !== RP2040_FAMILY) {
      throw new Error("This UF2 file is not for an RP2040.");
    }
    const addr = v.getUint32(12, true);
    const size = v.getUint32(16, true);
    if (size > 476) throw new Error("Bad UF2 block size.");
    if (addr < FLASH_START || addr + size > CONFIG_SECTOR) {
      throw new Error(`UF2 writes outside the program flash (0x${addr.toString(16)}).`);
    }
    for (let i = 0; i < size;) {
      const a = addr + i;
      const base = a - (a % SECTOR);
      let s = sectors.get(base);
      if (!s) sectors.set(base, (s = new Uint8Array(SECTOR).fill(0xff)));
      const n = Math.min(size - i, base + SECTOR - a);
      s.set(bytes.subarray(off + 32 + i, off + 32 + i + n), a - base);
      i += n;
    }
  }
  if (!sectors.size) throw new Error("The UF2 file has nothing to write.");
  return [...sectors.entries()].sort((a, b) => a[0] - b[0]).map(([addr, data]) => ({ addr, data }));
}

// ---- PICOBOOT ----

const CMD_MAGIC = 0x431fd10b;
const Cmd = {
  ExclusiveAccess: 0x01,
  Reboot: 0x02,
  FlashErase: 0x03,
  Read: 0x84,
  Write: 0x05,
  ExitXip: 0x06,
  EnterXip: 0x07,
};
const IF_RESET = 0x41;
const IF_CMD_STATUS = 0x42;
const STATUS_TEXT = [
  "ok", "unknown command", "invalid command length", "invalid transfer length",
  "invalid address", "bad alignment", "interleaved write", "rebooting", "unknown error",
];

export class PicobootError extends Error {
  constructor(message, kind) {
    super(message);
    this.kind = kind; // "access" (can't open or claim the device), "protocol", "verify"
  }
}

export class Picoboot {
  /** A Pico in BOOTSEL mode that the page already has permission for, or null. */
  static async find() {
    if (!navigator.usb) return null;
    return (await navigator.usb.getDevices()).find(isBootsel) ?? null;
  }

  /** Asks the user to pick the Pico (needs a click). Null if they cancel. */
  static async request() {
    try {
      return await navigator.usb.requestDevice({ filters: BOOTSEL_FILTERS });
    } catch (e) {
      if (e.name === "NotFoundError") return null;
      throw e;
    }
  }

  constructor(device) {
    this.device = device;
    this.token = 1;
  }

  async open() {
    const d = this.device;
    try {
      await d.open();
      if (!d.configuration) await d.selectConfiguration(1);
      const iface = d.configuration.interfaces.find((i) => i.alternates[0].interfaceClass === 0xff);
      if (!iface) throw new PicobootError("The Pico has no PICOBOOT interface.", "protocol");
      this.iface = iface.interfaceNumber;
      await d.claimInterface(this.iface);
      const eps = iface.alternates[0].endpoints;
      this.epIn = eps.find((e) => e.direction === "in").endpointNumber;
      this.epOut = eps.find((e) => e.direction === "out").endpointNumber;
    } catch (e) {
      if (e instanceof PicobootError) throw e;
      throw new PicobootError(e.message, "access");
    }
    await this.reset();
  }

  async close() {
    try { await this.device.close(); } catch { /* already gone */ }
  }

  /** Resets the PICOBOOT interface: clears halts and aborts a half-done command. */
  async reset() {
    await this.device.controlTransferOut({
      requestType: "vendor", recipient: "interface", request: IF_RESET, value: 0, index: this.iface,
    });
  }

  async status() {
    const r = await this.device.controlTransferIn({
      requestType: "vendor", recipient: "interface", request: IF_CMD_STATUS, value: 0, index: this.iface,
    }, 16);
    return r.data.getUint32(4, true);
  }

  /**
   * Sends one command. `args` are 32-bit words; `data` is sent for an OUT command, and
   * `inLength` bytes are read back for an IN command (bit 7 of the id). Returns the read data.
   */
  async command(id, args = [], { argBytes = args.length * 4, data = null, inLength = 0 } = {}) {
    const pkt = new DataView(new ArrayBuffer(32));
    const transfer = id & 0x80 ? inLength : (data?.length ?? 0);
    pkt.setUint32(0, CMD_MAGIC, true);
    pkt.setUint32(4, this.token++, true);
    pkt.setUint8(8, id);
    pkt.setUint8(9, argBytes);
    pkt.setUint32(12, transfer, true);
    args.forEach((a, i) => pkt.setUint32(16 + 4 * i, a, true));

    const check = async (r) => {
      if (r.status === "ok") return r;
      const code = await this.status().catch(() => 8);
      await this.reset().catch(() => {});
      throw new PicobootError(`PICOBOOT command 0x${id.toString(16)} failed: ${STATUS_TEXT[code] ?? code}.`, "protocol");
    };

    await check(await this.device.transferOut(this.epOut, pkt.buffer));
    let result = null;
    if (transfer) {
      if (id & 0x80) result = (await check(await this.device.transferIn(this.epIn, transfer))).data;
      else await check(await this.device.transferOut(this.epOut, data));
    }
    // Status phase: a zero-length packet in the other direction from the data.
    if (id & 0x80) await check(await this.device.transferOut(this.epOut, new Uint8Array(0)));
    else await check(await this.device.transferIn(this.epIn, 64));
    return result;
  }

  exclusive(on) { return this.command(Cmd.ExclusiveAccess, [on ? 1 : 0], { argBytes: 1 }); }
  exitXip() { return this.command(Cmd.ExitXip); }
  enterXip() { return this.command(Cmd.EnterXip); }
  erase(addr, size) { return this.command(Cmd.FlashErase, [addr, size]); }
  write(addr, data) { return this.command(Cmd.Write, [addr, data.length], { data }); }
  read(addr, size) { return this.command(Cmd.Read, [addr, size], { inLength: size }); }
  /** Starts the program in flash after `delayMs`. */
  reboot(delayMs = 500) { return this.command(Cmd.Reboot, [0, SRAM_END, delayMs]); }

  /**
   * Writes `sectors` (from parseUf2) to flash, reads them back to check, and restarts the
   * Pico. `onProgress(phase, fraction)` is called with phase "write", "verify" or "reboot".
   */
  async flash(sectors, onProgress = () => {}) {
    await this.exclusive(true); // keeps the computer off the RPI-RP2 drive meanwhile
    try {
      await this.exitXip();
      for (const [i, { addr, data }] of sectors.entries()) {
        onProgress("write", i / sectors.length);
        await this.erase(addr, SECTOR);
        await this.write(addr, data);
      }
      // The bootrom reads flash through XIP, which erase and write switched off.
      await this.enterXip();
      for (const [i, { addr, data }] of sectors.entries()) {
        onProgress("verify", i / sectors.length);
        const dv = await this.read(addr, SECTOR);
        const got = new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
        if (got.length !== SECTOR) throw new PicobootError("Short read from flash.", "protocol");
        const bad = got.findIndex((b, j) => b !== data[j]);
        if (bad >= 0) {
          throw new PicobootError(`Flash check failed at 0x${(addr + bad).toString(16)}.`, "verify");
        }
      }
    } catch (e) {
      await this.exclusive(false).catch(() => {});
      throw e;
    }
    onProgress("reboot", 1);
    // The Pico drops off USB when it restarts, which can cut the reply short.
    await this.reboot().catch(() => {});
    await this.close();
  }
}
