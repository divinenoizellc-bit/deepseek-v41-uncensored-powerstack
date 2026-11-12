# Final report — DeepSeek-V4.1-Flash-1017 Uncensored power stack

Generated **2026-11-12T02:51:56Z** by `scripts/final_report.py`.  **State: COMPLETE**

## Verdict

- Verification: **pass** — 16/16 files, 16 PASS, 0 FAIL, 0 MISSING
- Bytes: 352.52 GiB expected, 352.52 GiB present, 352.52 GiB hash-verified
- Portability: **True** — every accepted file is present and hash-verified
- Hardware minimum (Strata): {'vramGiBMinimum': 8, 'vramGiBMeasured': 12, 'source': 'Strata runtime self-report', 'note': 'Strata requires at least 8 GiB VRAM; 12 GiB was measured on this box. Weights stay in this library dir; the runtime loads them from here.'}
- Source report: `Library\logs\verify-library-latest.json`

## Files

| File | Bytes | Status | Expected hash | Actual hash |
|---|---:|---|---|---|
| `.gitattributes` | 2,671 | **PASS** | `b1e3ec093cff28e4` | `b1e3ec093cff28e4` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00004.gguf` | 39,358,830,464 | **PASS** | `6e3f0d5ff53d0042` | `6e3f0d5ff53d0042` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00002-of-00004.gguf` | 39,176,113,248 | **PASS** | `34d68c99fdae9948` | `34d68c99fdae9948` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00003-of-00004.gguf` | 39,997,334,720 | **PASS** | `fb1dd52e9029400b` | `fb1dd52e9029400b` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00004-of-00004.gguf` | 2,188,841,824 | **PASS** | `25eb979db1aac9da` | `25eb979db1aac9da` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf` | 39,075,714,624 | **PASS** | `d46efb67ccffd8fb` | `d46efb67ccffd8fb` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00002-of-00004.gguf` | 39,388,449,504 | **PASS** | `cec1b2c3da429dc7` | `cec1b2c3da429dc7` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00003-of-00004.gguf` | 39,246,891,616 | **PASS** | `9d9c2140fcb134a0` | `9d9c2140fcb134a0` |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00004-of-00004.gguf` | 20,527,837,312 | **PASS** | `92e1b7aac2c27451` | `92e1b7aac2c27451` |
| `LICENSE` | 1,084 | **PASS** | `d62e3bef9f054f21` | `d62e3bef9f054f21` |
| `README.md` | 6,801 | **PASS** | `160420a94d06802d` | `160420a94d06802d` |
| `rungs.json` | 1,297 | **PASS** | `23f96d807b81f811` | `23f96d807b81f811` |
| `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` | 110,595,290,816 | **PASS** | `eb19f30d368d3937` | `eb19f30d368d3937` |
| `DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf` | 5,780,589 | **PASS** | `cc15d470afcb0305` | `cc15d470afcb0305` |
| `dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf` | 7,976,914,240 | **PASS** | `6ba6ac1b331c5406` | `6ba6ac1b331c5406` |
| `mmproj-BF16.gguf` | 972,208,288 | **PASS** | `9a1ef7c40d0d702c` | `9a1ef7c40d0d702c` |

## GGUF headers (parsed on disk)

| File | GiB | Tensors | Architecture | Notes |
|---|---:|---:|---|---|
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00004.gguf` | 36.66 | 46 | `deepseek41` | part 1/4, file_type 31 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00002-of-00004.gguf` | 36.49 | 41 | `?` | part 2/4 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00003-of-00004.gguf` | 37.25 | 647 | `?` | part 3/4 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00004-of-00004.gguf` | 2.04 | 274 | `?` | part 4/4 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf` | 36.39 | 42 | `deepseek41` | part 1/4, file_type 19 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00002-of-00004.gguf` | 36.68 | 36 | `?` | part 2/4 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00003-of-00004.gguf` | 36.55 | 34 | `?` | part 3/4 |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00004-of-00004.gguf` | 19.12 | 896 | `?` | part 4/4 |
| `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` | 103.00 | 2 | `deepseek41-engram` | — |
| `dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf` | 7.43 | 78 | `dflash` | file_type 7 |
| `mmproj-BF16.gguf` | 0.91 | 298 | `clip` | file_type 32 |
| `DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf` | 0.01 | 0 | `deepseek41` | part 1/9, file_type 38 |

## Reproduce

```powershell
python scripts\verify_library.py
python scripts\gguf_probe.py --library
python scripts\check_pins.py
python scripts\status.py --write
```

