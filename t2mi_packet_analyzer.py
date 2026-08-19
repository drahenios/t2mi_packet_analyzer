#!/bin/python3

# =============================================================================
# DVB-T2 MI BBFRAME Extractor and TS Rebuilder
#
# Author : Xabier Legaspi Juanatey
# Date   : 2026-05-28
#
# This tool parses MPEG-TS packets carrying DVB-T2 Modulator Interface (T2-MI)
# streams over PID 0x1000. It extracts T2-MI packets of type 0x00 containing
# DVB-T2 BBFRAME payloads, validates BBHEADER integrity and reconstructs the
# original MPEG-TS stream transported in High Efficiency Mode (HEM).
#
# The script also generates a detailed packet analysis log including:
#   - T2-MI headers
#   - BBHEADER fields
#   - CRC validation
#   - DATA FIELD extraction
# =============================================================================

import sys
from typing import Optional, Tuple

# ===== CONSTANTS =====

# MPEG-TS packet size
TS_PACKET_SIZE = 188

# MPEG-TS sync byte
SYNC_BYTE = 0x47

# DVB-T2 MI PID
TARGET_PID = 0x1000

# Fixed structure sizes
T2MI_HEADER_SIZE = 6
T2MI_PAYLOAD_00_HEADER_SIZE = 3
BBHEADER_SIZE = 10
T2MI_CRC_SIZE = 4

# Minimum size required to attempt resync
MINIMUM_SIZE = (
    T2MI_HEADER_SIZE
    + T2MI_PAYLOAD_00_HEADER_SIZE
    + BBHEADER_SIZE
    + TS_PACKET_SIZE
    - 1
)

# ===== TS PARSER =====

def parse_ts_header(packet: bytes) -> Tuple[int, int, int, Optional[bytes]]:
    # Validate TS packet size
    if len(packet) < 188:
        raise ValueError("Invalid TS packet length")

    # Validate MPEG-TS sync byte
    if packet[0] != SYNC_BYTE:
        raise ValueError("Invalid sync byte")

    # Extract TS header fields
    pid = ((packet[1] & 0x1F) << 8) | packet[2]
    pusi = (packet[1] >> 6) & 0x1
    cc = packet[3] & 0x0F
    afc = (packet[3] >> 4) & 0x3

    # AFC value 0 is reserved
    if afc == 0:
        raise ValueError("Invalid adaptation field control")

    index = 4

    # Skip adaptation field if present
    if afc in (2, 3):
        if index >= len(packet):
            return pid, pusi, cc, None

        adaptation_length = packet[index]
        index += 1

        # Prevent adaptation overflow
        if index + adaptation_length > len(packet):
            raise ValueError("Invalid adaptation field length")

        index += adaptation_length

    # Extract payload if available
    payload = packet[index:] if (afc in (1, 3) and index < len(packet)) else None

    return pid, pusi, cc, payload

# ===== CRC-32 =====

def crc32(data: bytes) -> int:
    # DVB-T2 MI CRC-32 polynomial
    crc = 0xFFFFFFFF
    poly = 0x04C11DB7

    for b in data:
        crc ^= b << 24

        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) & 0xFFFFFFFF) ^ poly
            else:
                crc = (crc << 1) & 0xFFFFFFFF

    return crc

# ===== T2-MI PARSER =====

def parse_t2mi_packet(packet: bytes) -> dict:
    # Extract fixed T2-MI header
    header_bytes = packet[:T2MI_HEADER_SIZE]

    packet_type = header_bytes[0]
    packet_count = header_bytes[1]
    superframe_idx = (header_bytes[2] >> 4) & 0x0F
    rfu = ((header_bytes[2] & 0x0F) << 5) | ((header_bytes[3] >> 3) & 0x1F)
    stream_id = header_bytes[3] & 0x07

    # Payload length is stored in bits
    payload_len_bits = int.from_bytes(header_bytes[4:6], "big")
    payload_len_bytes = (payload_len_bits + 7) // 8

    # Compute padding required for byte alignment
    pad_bits = (8 - (payload_len_bits % 8)) % 8
    pad_len_bytes = (pad_bits + 7) // 8

    # Extract payload
    payload_bytes = packet[
        T2MI_HEADER_SIZE:
        T2MI_HEADER_SIZE + payload_len_bytes
    ]

    # Extract alignment padding
    pad_bytes = packet[
        T2MI_HEADER_SIZE + payload_len_bytes:
        T2MI_HEADER_SIZE + payload_len_bytes + pad_len_bytes
    ]

    # Extract CRC-32
    crc_bytes = packet[
        T2MI_HEADER_SIZE + payload_len_bytes + pad_len_bytes:
        T2MI_HEADER_SIZE + payload_len_bytes + pad_len_bytes + T2MI_CRC_SIZE
    ]

    received_crc = int.from_bytes(crc_bytes, "big")

    # CRC includes header + payload + padding
    computed_crc = crc32(
        packet[:T2MI_HEADER_SIZE + payload_len_bytes + pad_len_bytes]
    )

    return {
        "packet_type": packet_type,
        "packet_count": packet_count,
        "superframe_idx": superframe_idx,
        "rfu": rfu,
        "stream_id": stream_id,
        "payload_len": payload_len_bits,
        "pad_len": pad_len_bytes * 8,
        "header_bytes": header_bytes,
        "payload_bytes": payload_bytes,
        "pad_bytes": pad_bytes,
        "crc_bytes": crc_bytes,
        "crc_received": received_crc,
        "crc_computed": computed_crc,
        "crc_ok": (received_crc == computed_crc)
    }

# ===== CRC-8 =====

def crc8(data: bytes) -> int:
    """
    DVB-S2 CRC-8.

    Polynomial:
        x^8 + x^7 + x^6 + x^4 + x^2 + 1

    Hex:
        0xD5
    """

    crc = 0x00
    poly = 0xD5

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF

    return crc

# ===== T2-MI PAYLOAD 0x00 PARSER =====

def parse_payload_00(payload_bytes: bytes, payload_len_bits: int) -> dict:
    # Ensure minimum payload size
    if len(payload_bytes) < 3:
        raise ValueError("T2-MI payload too short")

    # ---- T2-MI payload header ----

    header_payload_00 = payload_bytes[:3]

    frame_idx = payload_bytes[0]

    # Single-PLP stream expected
    plp_id = payload_bytes[1]

    if plp_id != 0x00:
        raise ValueError(f"plp_id is not 0 (plp_id={plp_id})")

    third_byte = payload_bytes[2]

    intl_frame_start = (third_byte >> 7) & 0x01
    rfu_t2mi = third_byte & 0x7F

    # ---- BBFRAME ----

    bbframe_bytes = payload_bytes[3:]

    if len(bbframe_bytes) < 10:
        raise ValueError("BBFRAME too short")

    # Extract BBHEADER
    bbheader = bbframe_bytes[:10]

    # ---- MATYPE-1 ----

    matype1 = bbheader[0]

    ts_gs = (matype1 >> 6) & 0b11
    sis_mis = (matype1 >> 5) & 0b1
    ccm_acm = (matype1 >> 4) & 0b1
    issyi = (matype1 >> 3) & 0b1
    npd = (matype1 >> 2) & 0b1
    ext = matype1 & 0b11

    # Only TS mode supported
    if ts_gs != 0b11:
        raise ValueError(f"Only TS supported (ts_gs={ts_gs})")

    # ---- CRC / MODE ----

    crc_mode_byte = bbheader[9]

    # CRC is computed over first 9 bytes
    computed_crc = crc8(bbheader[:9])

    # MODE is XORed with CRC
    mode = crc_mode_byte ^ computed_crc

    # Only High Efficiency Mode supported
    if mode != 0x01:
        raise ValueError(f"Only HEM supported (mode={mode})")

    # ISSY must be disabled
    if issyi != 0b0:
        raise ValueError(
            f"ISSYI must be inactive (ISSYI={issyi})"
        )

    # NPD unsupported in current extractor
    if npd != 0b0:
        raise ValueError(
            f"Null-packet deletion (NPD) is active (NPD={npd})"
        )

    # ---- ISSY / DFL / SYNCD ----

    issy_msb = int.from_bytes(bbheader[2:4], "big")
    issy_lsb = bbheader[6]

    # Rebuild 24-bit ISSY field
    issy = (issy_msb << 8) | issy_lsb

    # DATA FIELD length in bits
    dfl_bits = int.from_bytes(bbheader[4:6], "big")
    dfl_bytes = (dfl_bits + 7) // 8

    # SYNCD offset in bits
    syncd = int.from_bytes(bbheader[7:9], "big")

    # ---- DATA FIELD ----

    data_field_start = 10
    data_field_end = data_field_start + dfl_bytes

    data_field = bbframe_bytes[data_field_start:data_field_end]

    # Validate complete BBFRAME extraction
    if len(data_field) < dfl_bytes:
        raise ValueError("Incomplete DATA FIELD")

    return {
        "header_payload_00_bytes": header_payload_00,

        "frame_idx": frame_idx,
        "plp_id": plp_id,
        "intl_frame_start": intl_frame_start,
        "rfu": rfu_t2mi,

        "bbheader_bytes": bbheader,

        "ts_gs": ts_gs,
        "sis_mis": sis_mis,
        "ccm_acm": ccm_acm,
        "issyi": issyi,
        "npd": npd,
        "ext": ext,

        "issy": issy,
        "dfl_bits": dfl_bits,
        "syncd": syncd,

        "crc_mode": crc_mode_byte,
        "mode": mode,
        "crc_computed": computed_crc,

        "data_field": data_field,
    }

# =========================
# HEX DUMP
# =========================
def hex_dump(data: bytes, width=16) -> str:
    if not data:
        return "None"
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_bytes = " ".join(f"{b:02X}" for b in chunk)
        lines.append(f"{i:04X}: {hex_bytes}")
    return "\n".join(lines)

# =========================
# LOGGER
# =========================
class Logger:
    def __init__(self, analysis_file: str):
        self.analysis_out = open(analysis_file, "w")

    def log_t2mi(self, info: dict, index: int):
        a = self.analysis_out

        a.write("\n" + "="*60 + "\n")
        a.write(f"T2-MI PACKET #{index}\n")
        a.write("="*60 + "\n")

        # ---- T2-MI HEADER ----
        a.write("\n[T2-MI HEADER]\n")
        a.write(hex_dump(info["header_bytes"]) + "\n\n")
        a.write(f"packet_type: {info['packet_type']}\n")
        a.write(f"packet_count: {info['packet_count']}\n")
        a.write(f"superframe_idx: {info['superframe_idx']}\n")
        a.write(f"rfu: {info['rfu']}\n")
        a.write(f"t2mi_stream_id: {info['stream_id']}\n")
        a.write(f"payload_len: {info['payload_len']} bits\n\n")

        if info["packet_type"] == 0x00:
            try:
                bb = parse_payload_00(info["payload_bytes"], info["payload_len"])

                # ---- T2-MI PAYLOAD OF TYPE 0x00 HEADER (FOR BBFRAME) ----
                a.write("\n[T2-MI 0x00 PAYLOAD HEADER]\n")
                a.write(hex_dump(bb["header_payload_00_bytes"]) + "\n\n")
                a.write(f"frame_idx: {bb['frame_idx']}\n")
                a.write(f"plp_id: {bb['plp_id']}\n")
                a.write(f"intl_frame_start: {bb['intl_frame_start']}\n")
                a.write(f"rfu: {bb['rfu']}\n")


                # ---- BBHEADER ----
                a.write("\n[BBHEADER]\n")
                a.write(hex_dump(bb["bbheader_bytes"]) + "\n\n")
                a.write("---- MATYPE-1 ----\n")
                a.write(f"TS/GS: {bb['ts_gs']} (expected 3 = TS)\n")
                a.write(f"SIS/MIS: {bb['sis_mis']}\n")
                a.write(f"CCM/ACM: {bb['ccm_acm']}\n")
                a.write(f"ISSYI: {bb['issyi']}\n")
                a.write(f"NPD: {bb['npd']}\n")
                a.write(f"EXT: {bb['ext']}\n")
                a.write("-------------------\n")
                a.write(f"ISSY: {bb['issy']}\n")
                a.write(f"DFL: {bb['dfl_bits']} bits\n")
                a.write(f"SYNCD: {bb['syncd']} bits\n")
                a.write("------ CRC-8 ------\n")
                a.write(f"CRC-8 Mode: 0x{bb['crc_mode']:02X}\n")
                a.write(f"CRC-8 Computed: 0x{bb['crc_computed']:02X}\n")
                a.write(f"MODE: {bb['mode']} (expected 1 = HEM)\n")

                # ---- DATA FIELD ----
                a.write("\n[DATA FIELD]\n")
                a.write(hex_dump(bb["data_field"]) + "\n")


                # ---- PAD ----
                a.write("\n[PAD]\n")
                a.write(hex_dump(info["pad_bytes"])+ "\n\n")
                a.write(f"pad_len: {info['pad_len']} bits\n")

                # ---- CRC-32 ----
                a.write("\n[CRC-32]\n")
                a.write(hex_dump(info["crc_bytes"]) + " (")
                a.write("OK" if info['crc_ok'] else "FAIL")
                a.write(")\n")

            except Exception as e:
                raise RuntimeError(f"T2-MI 0x00 PAYLOAD parsing failed: {e}")

        a.flush()

    def close(self):
        self.analysis_out.close()

# =========================
# BUFFER + EXTRACTION
# =========================

def append_to_buffer(buffer, payload, pusi):
    if not payload:
        return None  # no reset

    if pusi:
        pointer = payload[0]

        tail = payload[1:1 + pointer]
        new_start = payload[1 + pointer:]

        buffer.extend(tail)
        return new_start  # signal reset point

    else:
        buffer.extend(payload)
        return None

# ---- High efficiency mode/transport stream extractor
class HEMTSExtractor:
    def __init__(self):
        self.buffer = bytearray()
        self.UP_SIZE = 187  # TS payload size without sync byte
        self.first_bbframe = True

    def process_bbframe(self, bb):
        data = bb["data_field"]

        # ---- Apply SYNCD ONLY ON FIRST BBFRAME ----
        if self.first_bbframe:
            syncd_bytes = bb["syncd"] // 8

            # IMPORTANT: only skip if possible
            if syncd_bytes > 0:
                if syncd_bytes > len(data):
                    # avoid cutting more than available
                    syncd_bytes = len(data)

                data = data[syncd_bytes:]

            self.first_bbframe = False

        # ---- Append to continuous stream ----
        self.buffer.extend(data)

        packets = []

        # ---- Extract TS packets ----
        while len(self.buffer) >= self.UP_SIZE:
            up = self.buffer[:self.UP_SIZE]
            del self.buffer[:self.UP_SIZE]

            packets.append(bytes([0x47]) + up)

        return packets

def extract_t2mi_packets(buffer: bytearray):
    packets = []
    while len(buffer) >= T2MI_HEADER_SIZE:
        payload_len_bits = int.from_bytes(buffer[4:6], "big")
        payload_len_bytes = (payload_len_bits + 7) // 8

        pad_bits = (8 - (payload_len_bits % 8)) % 8
        pad_len_bytes = (pad_bits + 7) // 8

        total_size = T2MI_HEADER_SIZE + payload_len_bytes + pad_len_bytes + T2MI_CRC_SIZE

        if len(buffer) < total_size:
            break

        packets.append(bytes(buffer[:total_size]))
        del buffer[:total_size]

    return packets

def handle_t2mi_packet(t2mi_packet, t2mi_index, logger, extractor, ts_out):
    try:
        info = parse_t2mi_packet(t2mi_packet)
    except Exception as e:
        print(f"T2-MI parsing failed: {e}")
        return

    logger.log_t2mi(info, t2mi_index)

    if info["packet_type"] != 0x00:
        return

    try:
        bb = parse_payload_00(
            info["payload_bytes"],
            info["payload_len"]
        )
    except Exception as e:
        print(f"Payload 0x00 parsing failed: {e}")
        return

    try:
        ts_packets = extractor.process_bbframe(bb)
    except Exception as e:
        print(f"TS reconstruction failed: {e}")
        return

    for pkt in ts_packets:
        ts_out.write(pkt)

# =========================
# MAIN
# =========================
def main():
    if len(sys.argv) < 4:
        print("Usage: ts_to_t2mi.py file.ts first_packet last_packet")
        sys.exit(1)

    filename = sys.argv[1]
    first_packet_idx = int(sys.argv[2])
    last_packet_idx = int(sys.argv[3])

    buffer = bytearray()
    new_start = bytearray()
    cc_state = None
    t2mi_index = 0
    started = False
    resync_mode = False
    logger = Logger("t2mi_packet_analysis.txt")
    extractor = HEMTSExtractor()
    ts_out = open("output.ts", "wb")

    with open(filename, "rb") as f:
        
        for i in range(first_packet_idx, last_packet_idx + 1):
            f.seek(i * TS_PACKET_SIZE)
            ts_packet = f.read(TS_PACKET_SIZE)

            if len(ts_packet) != TS_PACKET_SIZE:
                continue

            try:
                pid, pusi, cc, payload = parse_ts_header(ts_packet)
                
                # Reads only TS packets with pid = 0x1000
                if pid != TARGET_PID:
                    continue

                if not started:
                    if pusi:
                        started = True
                    else:
                        continue

                if  pusi == 1:
                    ts_index = 0
                else:
                    ts_index +=1

                # ---- Continuity counter check ----
                if cc_state:
                    expected_cc = (cc_state + 1) % 16

                    if cc != expected_cc:
                        print(f"[WARN] CC discontinuity (unexpected) at {i}")
                        resync_mode = True

                cc_state = cc

                # ---- RESYNC MODE ----
                if resync_mode:
                    buffer_len_bits = int.from_bytes(buffer, "big")
                    buffer_len_bytes = (buffer_len_bits + 7) // 8
                    
                    if buffer_len_bytes >= MINIMUM_SIZE:
                        up_count = buffer_len_bytes // 187
                        up_len_bytes = up_count * 187
                        # EXTRACT  UP PACKETS
                        

                    print(f"[INFO] Resync achieved at packet {i}")
                    started = False
                    cc_state = None
                    resync_mode = False
                    buffer.clear()

                # ---- NORMAL PROCESSING ----

                new_start = append_to_buffer(buffer, payload, pusi)

                # Extract ALL complete T2-MI packets first
                t2mi_packets = extract_t2mi_packets(buffer)

                for t2mi_packet in t2mi_packets:
                    handle_t2mi_packet(t2mi_packet, t2mi_index, logger, extractor, ts_out)
                    t2mi_index += 1

                # Reset buffer
                if new_start is not None:
                    buffer.clear()
                    buffer.extend(new_start)

            except Exception as e:
                print(f"Error at TS packet {i}: {e}")

    logger.close()
    ts_out.close()


if __name__ == "__main__":
    main()
