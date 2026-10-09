# LNG Brand / Company / Role verification (Aug 2026)

**Market:** Global Liquefied Natural Gas Market  
**File:** `output/chatgpt_expand/global_liquefied_natural_gas_market_global/global_liquefied_natural_gas_market_global_FINAL.xlsx`  
**After fix:** 221 companies — Brand 216 / Marketer 5

## Fixes applied

### Corrected false / imprecise ownership
| Brand (after) | Issue | Fix |
|---|---|---|
| APA Corporation | Listed as `(acquired by APA Corporation)` — holding-company reorg, not a buyout | Renamed from Apache; Company = Brand (independent public) |
| Noble Resources | Listed as Noble Group acquired by Vitol | Renamed; Vitol acquired **Noble Resources** (Jan 2025) |
| Sempra Infrastructure Partners | Listed as `acquired by Sempra…` | Now `(owned by Sempra ~70%, KKR ~20%, ADIA ~10%; KKR 65% sale pending 2026)` |
| Expand Energy Corporation | Still named Chesapeake | Renamed after Southwestern merger (Oct 2024) |
| Mubadala Energy | Still Mubadala Petroleum | Renamed (2022 rebrand); subsidiary of Mubadala Investment Company |
| Höegh Evi | Still Höegh LNG Holdings | Renamed; owned by Aequitas 50% / Igneo 50% |
| SK Innovation E&S | Still SK E&S | Renamed; `(merged into SK Innovation)` Nov 2024 |
| GAZ-SYSTEM (Polskie LNG / Świnoujście) | Polskie LNG as standalone | Renamed after Mar 2021 merger into GAZ-SYSTEM |
| CNOOC | Duplicate long + short names | Deduped to **CNOOC** |

### Confirmed acquisitions / ownership (kept or added)
| Brand | Company column |
|---|---|
| Anadarko Petroleum Corporation | (acquired by Occidental Petroleum Corporation) |
| Pavilion Energy | (acquired by Shell plc) — completed Apr 2025 |
| Tellurian Inc. | (acquired by Woodside Energy Group Ltd) — completed Oct 2024 |
| Noble Resources | (acquired by Vitol) |
| Wintershall Dea AG | (acquired by Harbour Energy plc — E&P excl. Russia, Sep 2024) |
| Senex Energy | (acquired by POSCO International 50.1% / Hancock Energy 49.9%) |
| Magnolia LNG | (acquired by Glenfarne Group) |
| Endesa | (subsidiary of Enel S.p.A. ~70%) |
| Kunlun Energy | (subsidiary of PetroChina / CNPC) |
| Equinor (UK) Limited | (subsidiary of Equinor ASA) |
| ADNOC Gas | (subsidiary of ADNOC) |
| PTT LNG / PTT Global LNG | (subsidiary of PTT Public Company Limited) |
| FortisBC | (subsidiary of Fortis Inc.) |
| VNG Handel & Vertrieb GmbH | (subsidiary of VNG AG) |
| PetroVietnam Gas | (subsidiary of Petrovietnam) |
| JERA Co., Inc. | (owned by TEPCO Fuel & Power and Chubu Electric — 50/50 JV) |
| Uniper SE | (owned by Federal Republic of Germany ~99.12%) |

### Removed (off-market / defunct / duplicates)
- Jordan Cove LNG (Pembina cancelled 2021)
- RasGas + Qatar Gas (merged into QatarEnergy LNG)
- Prelude FLNG (Shell-operated project, not a company)
- LNG Limited (sold Magnolia; inactive)
- Fox Petroleum, Indra Gas, Zodiac Energy, Zeta Energy, Goldeneye LNG, STX LNG

### Restored after overly-broad filter
- **Petronet LNG Limited**
- **Pakistan LNG Limited (PLL)**

### Role
- Default **Brand** for LNG producers / utilities / project companies
- **Marketer** for pure commodity traders: Vitol, Gunvor, Trafigura, Mercuria, Glencore

## Script
`scripts/fix_lng_ownership.py`
