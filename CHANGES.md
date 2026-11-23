# Changes in this fork

Base: [andreas-abel/uiCA](https://github.com/andreas-abel/uiCA) `master` at `6ebeeab` (2024-01-14, "Fixes k0 register dependencies #23").
Commit hashes refer to [jtl06/uiCA](https://github.com/jtl06/uiCA); each commit message has the details and measurements.

## 1. Fixes that also apply to the original uiCA (upstream candidates)

These change or fix behavior of the stock Intel models, or of uiCA in general, and are independent of the new models.

| Fix | Commit | Effect |
|---|---|---|
| **Division/square root with a memory operand.** uops.info gives only `min_cycles_*` latencies for instructions with value-dependent latency; `convertXML.py` ignored them, so the memory latency defaulted to 1 and `computeUopProperties` gave the register input that latency too (e.g. `divpd xmm5, [rax]` predicted at 4 cycles/iteration instead of 13). | `aa9f2c7` | 14 instruction forms on SKL, 52 on ICL/RKL. Random loops with div/sqrt on Ice Lake-SP (stock ICL): mean error 7.0% → 3.3%. |
| **Iform names of newer uops.info data.** Newer `instructions.xml` files use iform names of newer XED versions; 113 differ from those of the bundled XED (e.g. `ANDN_GPR64q_GPR64q_GPR64q` vs. `ANDN_VGPR64q_VGPR64q_VGPR64q`, `MOVZX_GPR64_MEMw` vs. `MOVZX_GPRv_MEMw`). All BMI1/BMI2/TBM instructions and `movzx`/`movsx r32/r64, m16` got no data on any microarchitecture. `genIformMap.py` generates `xedIformMap.py`, which `convertXML.py` uses. | `9a2007c` | These instructions get data again; the tables change only by the renames. |
| **Nondeterministic results.** `Scheduler.processPendingUops` iterated over a `set` of uops, whose order depends on memory addresses (and so on `PYTHONHASHSEED` and allocation history); the order in which dependent uops became ready could differ between runs of the same input. Now iterates in program order. | `9b69d9d` | Same output for every run. Observed only with the ZEN3 model (13 of 329 test files, port-usage columns; throughput changed for 5 of about 4900 measured loops, accuracy unchanged); the stock Intel models gave identical output on the same files, but the code is shared. |
| **`getRegSize`**: `['AX', 'BX', 'CX', 'DX', 'SP', 'BP' 'SI', 'DI']` was missing a comma, so `BP` and `SI` were reported as 64-bit registers. | `a100889` | No output changed on the test files. |
| **`-TPonly`** was declared with `nargs='?', const='graph.html'` (copied from `-graph`), so in `uiCA.py -TPonly file.o` the file name was taken as its value. Now a flag. | `ddc22da` | — |
| **Install prerequisites.** Building the XED module needs the Python headers and setuptools (not bundled with Python ≥ 3.12); the README did not list them, and `setup.sh` failed in the middle of the build. README updated; `setup.sh` checks first and prints the package names. | `b765ee2` | — |
| **Speed.** The cyclic garbage collector is paused during a simulation; `__slots__` for the uop and instruction-instance classes; per-instruction precomputation of rename keys and uop grouping; memoized helpers. `runSimulation` also starts from a fresh state (random seed, uop counter), so library use gives the same results as the CLI. | `49c6b2a` | Same output. CLI, 1000 instructions: 386 → 291 ms; 3000: 1265 → 866 ms; small blocks: 102 → 91 ms (mostly Python startup). Many simulations in one process: 1.6× faster. |
| **Generalized port parameters.** The simulator's hard-coded Intel port numbers (load, store-address, store-data, micro-fusion and divider ports, load latency) are `MicroArchConfig` parameters, with the previous values as defaults. | `c0e0acd` | Refactor; output unchanged. Needed for non-Intel models. |
| **Crash: load uop without an address.** Some instructions without a memory input operand have a load port in their port data (PCMPESTRI/VPCMPESTRM with register operands on SNB/IVB, OUT, INS); `Renamer.cycle` failed with `AttributeError: 'NoneType' object has no attribute 'get'`. Such a load uop now reads no store and gets no fast pointer chasing. | `ebc6e47` | These inputs get a result; other output unchanged. |
| **Crash: DSB-to-MITE switch.** The front end checked whether the next instruction is in the DSB only when the DSB delivered the last uop of an instruction, so it stayed on the DSB after a microcoded instruction, an instruction without uops or a macro-fused pair whose successor is not in the DSB; it then delivered the next round's block too early and failed with `IndexError: deque index out of range` in `DSB.cycle`. The check now uses the last DSB entry read in the cycle and skips a fused branch. | `19ba4f3`, `e9b7a70` | These inputs get a result; other output unchanged. |
| **Crash: paired stores without a displacement.** `dispatchUops` computed `None - None` for two stores without a displacement (e.g. two `push qword ptr [rax]`) at the heads of the port-4 and port-9 queues (ICL, TGL, RKL). A missing displacement is now 0. | `1a3e7bf` | These inputs get a result; other output unchanged. |
| **`InputError`.** With `-minIterations` < 1 the simulation could stop before the first iteration was complete, and the throughput computation failed with `IndexError`. `runSimulation` now raises `InputError` (a new exception class for inputs that cannot be analyzed) with a message that says why. | `8360f1b` | — |

Cleanup: `86de104` removes unused helpers from `x64_lib.py` (`regTo32/16/8`, `regToSize`, `getRegForMemPrefix`, `getSizeOfMemPrefix`, `getMemAddr`, `Low8Regs`, `STATUSFLAGS*`).

## 2. New experimental models

Not included in `-arch all`; selected with `-arch ZEN3`, `-arch ADL-P`, `-arch ICX`. Validated with `perf` on a Ryzen 7 7735U (Zen 3+), Core i7-12650H (P-cores) and Xeon 6314U (Ice Lake-SP).

**AMD Zen 3** (`ZEN3`): `c0e0acd` back end (uops synthesized from operands, uops.info FP data and a port table following LLVM's `X86ScheduleZnver3.td`; least-loaded port assignment; dispatch width in macro-ops), `172e729` gaps found by checking every instruction, `8aa1dec` memory renaming, `b039cbd` same-register moves, `895e5a8` two stores per cycle only to the same cache line, `8119314` no renaming for load-op instructions, narrow-store penalty, `4a1aef9` op-cache delivery, `fb049dc` immediate/displacement fields per op-cache entry, `4e17992` store-forwarding delays, `eb53410` vector stores, GPR↔vector move latency, `9a2007c` decode with XED chip `ALL` (the bundled XED's AMD chips lack BMI1).

**Alder Lake P-cores** (`ADL-P`): `81fee10` model, `86ce3ad` loop stream detector and loop-branch port, `8aa1dec` memory renaming, `b039cbd` zero-extending moves, `62cb662` renaming of loads into GPRs, `0c59225` cache-line limit for loads, LSD unrolling, `4e17992` store-forwarding delays, `26b48f6` measured throughput as a limit for microcoded instructions.

**Ice Lake server** (`ICX`): `34769e5` model, `34c9bdd` store-forwarding delay, read-modify-write, `26b48f6` measured throughput for microcoded instructions.

**All three** (`a5ef6c2`): memory-renaming width rules, wider-load forwarding failure, value numbering through memory, shift-by-CL flags.

New `MicroArchConfig` parameters (defaults keep the stock models unchanged): `isAMD`, `experimental`, `portNames`, `portAssignment`, `loadPorts`, `storeAddrPorts`, `storeDataPorts`, `vectorStoreDataPorts`, `fusiblePorts`, `dividerPort`, `loadLatency`, `takenBranchPort`, `loadLineSlots`, `storeLineRestrictedPorts`, `memoryRenaming`, `memRenamingWidths`, `memRenamingExcluded`, `memRenamingFoldedCheck`, `loadValueNumbering`, `storeForwardDelay`, `storeForwardFailDelay`, `rmwForwardDelayOverride`, `simpleRMWForwardDelay`, `narrowStorePenalty`, `sameRegMoveEliminated`, `renameImmediateFolding`, `opCacheEntryOps`, `opCacheEntryFields`, `opCacheMaxFields`, `dataFrom`.

Fork-only fixes: `917878c` crash (KeyError) with `renameImmediateFolding` and move elimination; `4351920` crash (TypeError) while
writing the `-json` output for an instruction with a fractional throughput limit (the `executed` event goes to the cycle in which it
lies).

The crash fixes were found with the fixtures and the fuzzer of [wuica](https://github.com/jtl06/wuica) (a port of this fork); its
`docs/DEVIATIONS.md` lists every difference from upstream that changes a result or an error. With these fixes, every fixture case
that did not fail before is byte-identical.

### Accuracy (share of loops predicted within 10% of measured; data not used for tuning)

| | Random loops (holdout3) | Real code (BHive blocks, held half) | Reference |
|---|---|---|---|
| ZEN3 | 80.8% | 87.4% | llvm-mca znver3: 54.0% / 70.8% |
| ADL-P | 87.6% | 90.3% | stock uiCA RKL: 44.4% / 69.0% |
| ICX | 83.4% | 88.6% | stock uiCA ICL: 79.2% / 84.6% |

L1-resident data only; no cache misses or branch mispredictions.

## 3. Validation harness (`microbench/`)

- `microbench/fuzz/`: random-loop generator, perf measurement, scoring (`fuzz_report.py`), held-out sets.
- `microbench/real/`: loops from BHive basic blocks (`bhive_gen.py`, `real_measure.py`).
- Microbenchmarks for individual rules (`renaming_test.sh`, `zero_idiom_test.sh`, ...), measurements in `microbench/measurements/`.
- `intel_regression.sh`: checks that the stock Intel models are unchanged.
- `71b229b` removed three one-off experiment scripts.

## 4. How to check that a change does not alter predictions

The speed changes were checked by comparing the complete detailed output, the JSON output and the HTML trace of the old and new code on 329 files (random loops, BHive blocks, all microbench microbenchmarks) × all 21 configurations, and by checking that results are the same for different `PYTHONHASHSEED` values. `-graph` and `-depGraph` were not compared (they need plotly and pydot).
