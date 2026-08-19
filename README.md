# DVB-T2 MI BBFRAME Extractor

---

DVB-T2 MI BBFRAME Extractor and TS Rebuilder

Author : Xabier Legaspi Juanatey + ChatGPT
Date : 2026-05-28

---

## Overview

This project parses DVB-T2 Modulator Interface (T2-MI) streams encapsulated inside MPEG Transport Stream (`.ts`) files.

The script extracts T2-MI packets carried on PID `0x1000`, parses T2-MI payloads of type `0x00` (Baseband Frames), validates DVB-S2 BBHEADER fields and reconstructs the original MPEG-TS stream transported in High Efficiency Mode (HEM).

The tool also generates a detailed analysis log containing:

* MPEG-TS parsing information
* T2-MI packet headers
* BBHEADER fields
* CRC validation
* DATA FIELD dumps
* Synchronization parameters

The reconstructed transport stream is written into a new `.ts` output file.

---

# Features

* MPEG-TS parser
* DVB-T2 MI parser
* T2-MI packet extraction from PID `0x1000`
* BBFRAME parsing
* DVB-S2 BBHEADER parsing
* CRC-32 validation
* CRC-8 validation
* HEM TS packet reconstruction
* Detailed packet analysis logging

---

# Supported Configuration

The current implementation assumes:

* T2-MI packets on PID `0x1000`
* T2-MI payload type `0x00`
* DVB-S2 High Efficiency Mode (HEM)
* TS packetized mode
* ISSY disabled
* Null Packet Deletion (NPD) disabled
* Single PLP stream (`plp_id = 0`)

Unsupported configurations will raise parsing exceptions.

---

# Requirements

* Python 3.8+
* No external dependencies

---

# Usage

```bash
python3 t2mi_packet_analyzer.py input.ts first_packet last_packet
```

Example:

```bash
python3 t2mi_packet_analyzer.py capture.ts 0 50000
```

---

# Input Parameters

| Parameter      | Description                           |
| -------------- | ------------------------------------- |
| `input.ts`     | MPEG-TS file containing T2-MI packets |
| `first_packet` | First TS packet index to analyze      |
| `last_packet`  | Last TS packet index to analyze       |

---

# Outputs

The script generates two files:

---

## 1. `output.ts`

Reconstructed MPEG Transport Stream extracted from BBFRAME DATA FIELD payloads.

This stream can be analyzed using tools such as:

* DVBInspector
* TSReader
* ffprobe
* Wireshark

DVBInspector is especially useful for inspecting MPEG-TS tables, PIDs and PES streams.

---

## 2. `t2mi_packet_analysis.txt`

Detailed analysis log containing:

* T2-MI headers
* BBHEADER dumps
* MATYPE-1 fields
* DFL values
* SYNCD values
* CRC validation
* DATA FIELD hex dumps

Example:

```text
============================================================
T2-MI PACKET #15
============================================================

[T2-MI HEADER]
0000: 00 0F 10 00 05 E8

packet_type: 0
packet_count: 15
superframe_idx: 1
...
```

---

# MPEG-TS Packet Structure

```text
   0               1               2               3
   +---------------+---------------+---------------+---------------+
   | Sync (0x47)   | TEI |PUSI|PID (12:8)          | PID (7:0)     |
   +---------------+---------------+---------------+---------------+
   | TSC | AFC | CC|                                               |
   +---------------+                                               |
   |                                                               |
   |                 Adaptation Field (optional)                   |
   |                                                               |
   +---------------------------------------------------------------+
   |                                                               |
   |                        Payload                                |
   |                                                               |
   +---------------------------------------------------------------+
```

---

# T2-MI Payload Type 0x00 Structure

```text
   T2-MI HEADER
   ----------------------------------------------------------------

   +---------------+---------------+---------------+---------------+
   | packet_type   | packet_count  | SF_IDX | RFU  | RFU   |SID|  |
   +---------------+---------------+---------------+---------------+
   | payload_len_bits                              |               |
   +---------------+---------------+---------------+---------------+


   PAYLOAD TYPE 0x00 HEADER
   ----------------------------------------------------------------

   +---------------+---------------+---------------+
   | frame_idx     | plp_id        |IFS|   RFU     |
   +---------------+---------------+---------------+


   DVB-T2 BBHEADER (HEM / TS MODE)
   ----------------------------------------------------------------

   +---------------+---------------+---------------+---------------+
   | MATYPE-1      | MATYPE-2      | ISSY (23:16)  | ISSY (15:8)   |
   +---------------+---------------+---------------+---------------+
   | DFL (15:8)    | DFL (7:0)     | ISSY (7:0)    | SYNCD (15:8)  |
   +---------------+---------------+---------------+---------------+
   | SYNCD (7:0)   | CRC-8/MODE                                    |
   +---------------+---------------+---------------+---------------+


   DATA FIELD
   ----------------------------------------------------------------

   +---------------------------------------------------------------+
   |                                                               |
   |                     BBFRAME DATA FIELD                        |
   |                                                               |
   +---------------------------------------------------------------+


   BBPADDING
   ----------------------------------------------------------------

   +---------------------------------------------------------------+
   |                         BBPADDING                             |
   +---------------------------------------------------------------+


   PAD
   ----------------------------------------------------------------

   +---------------------------------------------------------------+
   |                       BYTE ALIGNMENT PAD                      |
   +---------------------------------------------------------------+


   CRC-32
   ----------------------------------------------------------------

   +---------------+---------------+---------------+---------------+
   |                        CRC-32                                 |
   +---------------+---------------+---------------+---------------+
```


---

# Internal Workflow

The processing flow is:

1. Read MPEG-TS packets
2. Filter PID `0x1000`
3. Reassemble T2-MI packets
4. Parse T2-MI headers
5. Extract payload type `0x00`
6. Parse DVB-T2 BBHEADER
7. Extract DATA FIELD
8. Rebuild MPEG-TS packets from HEM stream
9. Write reconstructed TS stream

---

# Notes

* TS synchronization recovery is partially implemented.
* BBFRAME validation is intentionally strict.
* The parser rejects unsupported DVB-T2 configurations.
* Packet alignment is handled using `SYNCD`.

---

# Files

| File                       | Description                    |
| -------------------------- | ------------------------------ |
| `t2mi_packet_analyzer.py`  | Main parser and extractor      |
| `output.ts`                | Reconstructed transport stream |
| `t2mi_packet_analysis.txt` | Detailed packet analysis log   |

---

# License

Educational and research use.

