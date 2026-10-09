# Semiconductor market relevance audit (own web search)

Date: 2026-08-13  
Market: Global Semiconductor (`global_semiconductor_market_global`) — **183** Company Details rows  
All roles labeled: **Solution Provider** (role tag is uniform; relevance judged by business, not Role string).

## Inclusion rule (strict)

Keep if the entity **designs, fabricates, packages/tests, or supplies semiconductor devices, wafers, manufacturing equipment, ATE, EDA/IP, or semiconductor-focused design services**.

Remove if: end-system OEM (PCs, aircraft, motors, UC), EMS/PCBA, industrial automation instruments, defense systems integrator, freight/logistics, government R&D institute without commercial chip products, invented country placeholders, or **regional / acquired duplicate** of a company already listed.

---

## Verdict

| Result | Count |
|--------|------:|
| Starting rows | 183 |
| Clear REMOVE (off-market / fake / wrong vertical) | ~22 |
| Duplicate / acquired / regional REMOVE | ~15 |
| KEEP (on-market after purge) | ~146 |

Core list is largely real semiconductor players (IDM, fabless, foundry, OSAT, equipment, EDA). Noise is concentrated in Latin America/Africa placeholders, end-system OEMs, and regional duplicates.

---

## REMOVE — wrong market (web-checked)

| Brand | Why |
|-------|-----|
| Mitel Networks | Unified communications / VoIP; semiconductor arm spun out as Zarlink (2001). |
| WEG S.A. | Electric motors, drives, transformers — industrial electrical, not chips. |
| Embraer | Aircraft OEM; consumes chips, does not sell semiconductors. |
| Positivo Tecnologia | Brazilian PC/phone/POS hardware OEM; not a chip maker. |
| Nortech Systems | EMS (PCBA / cable / box-build), not semiconductor. |
| Cascodium | Electronics + firmware design services (Andover MA); not a chip vendor. |
| Semicab | Freight / logistics optimization (semicab.com) — not semiconductors. |
| Smar Equipamentos Industriais | Industrial automation / field instruments (Brazil). |
| AEL Sistemas | Defense avionics / Elbit affiliate; systems, not commercial chip vendor. |
| Ciena Corporation | Optical networking systems OEM (not a semiconductor market player as brand). |
| Siemens AG | Conglomerate; keep **Siemens EDA** separately. |
| Raytheon Australia | Defense systems integration (NASAMS etc.), not commercial semi. |
| Centro de Tecnologia da Informação Renato Archer (CTI) | Brazilian government research center. |
| Instituto de Pesquisas Eldorado | R&D institute (has microelectronics lab; not commercial market vendor). |
| C-DAC | MeitY R&D org (VEGA etc.); not a commercial semiconductor company. |
| Algeria Semiconductor | No verifiable company under this name. |
| Egyptian Semiconductor | No verifiable company under this name. |
| Tunisia Semiconductor | No verifiable company under this name. |
| Moroccan Semiconductor | No verifiable company under this name. |
| Ethiopia Semiconductor | No verifiable company under this name. |
| South African Microelectronics | Generic/nonexistent name (real SA player is SAMES / Azoteq — not listed as this). |
| Nanolithography Solutions | No clear commercial match for this exact brand (not ASML/Raith). |
| Sahasra Electronics | Group storage/USB products; keep **Sahasra Semiconductors** (OSAT) only. |

## REMOVE — duplicates / acquired / regional offices

| Brand | Why |
|-------|-----|
| GlobalFoundries (already listed) | Explicit duplicate of GlobalFoundries. |
| Intel (Australia) / Intel India / Intel Mexico | Regional of Intel Corporation (kept). |
| Alphawave IP (Canada) | Regional of Alphawave IP (kept). |
| Semtech Corporation (Canadian operations) | Regional of Semtech. |
| Lumentum (Canada) | Regional of Lumentum. |
| Huawei Technologies - Chile (semiconductor R&D) | Regional R&D label, not a distinct vendor. |
| Skyworks Solutions - Mexico | Regional of Skyworks. |
| Cypress Semiconductor (now Infineon) | Acquired; Infineon kept. |
| Dialog Semiconductor (now Renesas) | Acquired; Renesas kept. |
| DSP Group (now part of Synaptics) | Acquired. |
| Xilinx (now part of AMD) | Acquired; AMD kept. |
| Mellanox Technologies | Acquired by NVIDIA (kept). |
| Habana Labs | Acquired by Intel (kept). |
| Sierra Wireless (now Semtech) | Acquired into Semtech. |

## KEEP examples (verified on-market)

TSMC, Intel, Samsung Electronics, NVIDIA, AMD, Broadcom, Qualcomm, MediaTek, ASML, Applied Materials, Lam, KLA, Tokyo Electron, ASE, Amkor, JCET, GlobalFoundries, SMIC, UMC, Micron, SK Hynix, Kioxia, Arm, Cadence, Synopsys, Siemens EDA, Tower, X-FAB, Siltronic, GlobalWafers, Wolfspeed, Infineon, NXP, ST, TI, Analog Devices, Rohm, Renesas, ON Semi, Sony Semiconductor Solutions, CEITEC, Chipus, Unitec Semicondutores, Sahasra Semiconductors, Polymatech, RIR Power Electronics, Cyient (semiconductor subsidiary), Kenya Semiconductor Technologies / STL, Helix Semiconductors, Pragmatic, etc.

## Borderline kept (ecosystem)

Jenoptik (semi optics/equipment), Rohde & Schwarz (semi test & measurement), Murata / Samsung Electro-Mechanics (components/substrates adjacent), Apple (designs SoCs), Western Digital (NAND/storage), Bosch Sensortec (MEMS sensors).

---

## Next step

Purge REMOVE sets from FINAL Excel + rebuild quadrant HTML/JSON (scores unchanged; no hardcoded score edits).
