# Acquisition status

Generated 2026-11-10T23:14:05Z by `scripts/status.py`.

**8/16 files · 31.58% · 111.34 GiB of 352.52 GiB** · free disk 327.83 GiB

| Component | Files | Complete | Size | State |
|---|---:|---:|---:|---|
| Engram | 1 | 1/1 | 103.00 GiB | complete |
| Drafter | 1 | 1/1 | 7.43 GiB | complete |
| Vision | 1 | 1/1 | 927.17 MiB | complete |
| Packer metadata | 1 | 1/1 | 5.51 MiB | complete |
| IQ2_XXS | 4 | 0/4 | 128.75 GiB | pending |
| IQ1_M | 4 | 0/4 | 112.43 GiB | pending |
| Text | 4 | 4/4 | 11.58 KiB | complete |

`runnable_here: false` — 6 GiB VRAM against a documented 8 GiB floor (12 GiB measured),
39.4 GiB RAM. The library is portable: copy it to a machine with a real card, re-run
`scripts/verify_library.py`, then `Tools/runtime/import-verified.ps1`.

Hashes are not evidence of freshness: run `python scripts/verify_library.py` for the
byte-level verdict, and `python scripts/gguf_probe.py --library` for the headers.

