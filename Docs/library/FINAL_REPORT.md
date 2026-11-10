# Final report — DeepSeek-V4.1-Flash-1017 Uncensored power stack

Generated **2026-11-10T23:16:54Z** by `scripts/final_report.py`.

## Verdict

- Verification: **pass** — 6/16 files, 6 PASS, 0 FAIL, 0 MISSING
- Bytes: 352.52 GiB expected, 932.69 MiB present, 932.69 MiB hash-verified
- Portability: **False** — 14 of 16 accepted files not yet hash-verified: .gitattributes, DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00004.gguf, DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00002-of-00004.gguf, DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00003-of-00004.gguf, DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00004-of-00004.gguf, DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf ...
- Hardware minimum (Strata): {'vramGiBMinimum': 8, 'vramGiBMeasured': 12, 'source': 'Strata runtime self-report', 'note': 'Strata requires at least 8 GiB VRAM; 12 GiB was measured on this box. Weights stay in this library dir; the runtime loads them from here.'}
- Source report: `Library\logs\verify-library-latest.json`

## Files

| File | Bytes | Status | Expected hash | Actual hash |
|---|---:|---|---|---|
| `.gitattributes` | 2,671 | **PASS** | `b1e3ec093cff28e4` | `b1e3ec093cff28e4` |
| `LICENSE` | 1,084 | **PASS** | `d62e3bef9f054f21` | `d62e3bef9f054f21` |
| `README.md` | 6,801 | **PASS** | `160420a94d06802d` | `160420a94d06802d` |
| `rungs.json` | 1,297 | **PASS** | `23f96d807b81f811` | `23f96d807b81f811` |
| `DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf` | 5,780,589 | **PASS** | `cc15d470afcb0305` | `cc15d470afcb0305` |
| `mmproj-BF16.gguf` | 972,208,288 | **PASS** | `9a1ef7c40d0d702c` | `9a1ef7c40d0d702c` |

## GGUF headers (parsed on disk)

| File | GiB | Tensors | Architecture | Notes |
|---|---:|---:|---|---|
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

