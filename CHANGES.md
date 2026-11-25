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

### Round 11: ZEN3 against real hot loops (`improve-r11`)

Development data: the development split of a benchmark of real hot loops (961 loops from 112 libraries measured in
situ on the Ryzen 7 7735U; the held-out split was not used). Mechanisms come from AMD's Software Optimization Guide
for family 19h (SOG) and from microbenchmarks that isolate them; the development split is a check, not a fitting
target. Every new behavior is a `MicroArchConfig` parameter whose default keeps the previous behavior: with the
defaults, the fixture export of all other configurations is byte-identical to `improve-r10`'s.

| Step (ZEN3) | Commit | Source | Dev ≤10 % (per library) | per loop | MAPE |
|---|---|---|---:|---:|---:|
| round 10 | `7301b04` | | 58.5 % | 55.3 % | 12.3 % |
| vector register file: 144 in flight, reusable 10 cycles after retirement | `c382a3a` | window probes | 68.6 % | 66.3 % | 10.0 % |
| store forwarding at an offset, into vector registers (+2/+3), failures 19 cycles apart | `9d5b07e` | 27 forwarding probes, failed-forwarding probes | 69.5 % | 67.1 % | 9.7 % |
| branches on ALU0 and the branch unit; fused register-writing pairs on ALU0 | `18affdd` | SOG 2.10.2, loop benchmarks r9b/r9c | | | |
| branch fusion of memory forms | `b08fbe8` | SOG 2.8.5, retired macro-ops | 70.9 % | 68.4 % | 8.8 % |
| MUL/MULX throughput, VCVTSD2SS/SS2SD merge latency, lane-crossing latencies | `b723d05`, `3929854`, `6c0f612` | single-instruction loops | 70.9 % | 68.8 % | 8.7 % |

Guards, within 10 % (round 10 -> round 11): dev13 84.3 -> 84.8, dev11 83.0 -> 83.9, holdout5 83.5 -> 83.9, bhive1
(dev half) 89.0 -> 89.5, bhive3 88.9 -> 89.2; the accuracy table of wuica's gate: holdout7 84.6 -> 85.5, holdout8
85.7 -> 86.3, bhive5 87.7 -> 88.3, bhive6 88.8 -> 89.1, dogfood loops 57.1 -> 81.0.

Too-fast error by hardware stall class (the diagnosis's dispatch-stall counters; share of round 10's too-fast mass):
FP register file 26.9 -> 6.1 %, store-reload interlocks 35.1 -> 19.9 %, execution-bound 20.5 -> 18.1 %, integer
scheduler 13.3 -> 13.9 %. The too-slow mass falls from 2.97 to 1.70 (per-library weights).

New generic parameters (all off by default): `vecRegFileSize`, `gprRegFileSize`, `vecRegFreeDelay`,
`gprRegFreeDelay`, `storeForwardOverlap`, `vectorStoreForwardDelay`, `storeForwardFailInterval`, `branchPorts`,
`fusedALUBranchPorts`, `amdBranchFusionRules`. The table corrections are entries of `INSTR_CORRECTIONS` in
`convertXML.py`.

Tried and not kept: the integer register file at the SOG's size (192 - 38 = 154; dev -0.3, holdout7 -0.4; the probe
onset is gradual, not a step); zeroing idioms without an execution port (SOG 2.9.2, measured 0.18-0.22 cycles each;
dev -0.9, some loops became twice as slow, a side effect not understood). Not changed: the macro-op count of `mul
m64` / `mulx r64, r64, m64` (measured 3, model 2; 3 would make them microcoded under the op-cache rule).

**ICX in round 11** (1,029 development loops measured on the Xeon Gold 6314U; values from probes on that machine):

| Step (ICX) | Commit | Source | Dev ≤10 % (per library) | per loop | MAPE |
|---|---|---|---:|---:|---:|
| round 10 | | | 65.2 % | 64.0 % | 10.3 % |
| vector register file 176, free delay 10 (alone) | `1a89172` | window probes (onset 160 fillers; documented 224 registers is an upper bound) | 71.6 % | 70.7 % | 8.9 % |
| store forwarding: overlap, ymm +1, failures 18 apart (alone) | `79ab878` | forwarding probes | 65.2 % | 63.9 % | 10.2 % |
| moves in the 4th rename slot execute (alone) | `863df35` | 26 + 25 move-elimination probes | 69.1 % | 68.3 % | 9.7 % |
| loops delivered one 64-byte line per cycle (alone) | `ba35f27` | offset probes, front-end probes | 67.0 % | 65.9 % | 9.7 % |
| all four | | | 76.9 % | 76.4 % | 7.6 % |
| + tables (SHA, blends, zmm loads/stores, merge latencies, double sqrt, zmm on p0/p5, VEX ones idiom) | `75a83b1`..`80b4254` | single-form loops, probes | 77.1 % | 76.8 % | 7.5 % |

Guards (ICX, round 10 -> round 11): dev13 86.9 -> 86.8, dev11 87.5 -> 87.8, holdout5 86.6 -> 87.3, bhive1 89.0 -> 89.1, bhive3 88.4 -> 88.1;
gate holdout7 85.8 -> 85.9, holdout8 85.6 -> 86.0, bhive5 89.7 -> 89.8, bhive6 88.2 -> 88.6.

**ADL-P in round 11** (874 development loops measured on the Core i7-12650H P-core):

| Step (ADL-P) | Commit | Source | Dev ≤10 % (per library) | per loop | MAPE |
|---|---|---|---:|---:|---:|
| round 10 | | | 78.7 % | 79.3 % | 7.0 % |
| scheduler queues math 110 / loads 70 / stores 50 (alone) | `17a4590` | window probes (onsets 88-96 / 72 / 64) | 86.1 % | 86.6 % | 5.7 % |
| fast add/sub +1 to other consumers (alone) | `91da3b6` | 14 probe pairs | 79.9 % | 80.5 % | 6.8 % |
| store forwarding: overlap, failures 17 apart (alone) | `c56ee25` | forwarding probes | 78.7 % | 79.3 % | 6.9 % |
| vector register file 264, free delay 10 (alone) | `bba7b99` | window probe | 80.2 % | 80.7 % | 6.6 % |
| integer register file 232 (alone) | `e229a68` | window probe | 78.7 % | 79.3 % | 6.9 % |
| VEX ones idiom; GPR -> vector moves 1 cycle (alone) | `b077dd3`, `c3bb556` | probes, round trips | 78.7 / 79.0 % | 79.3 / 79.6 % | 6.6 / 6.9 % |
| all | | | 86.9 % | 87.4 % | 5.0 % |

Guards (ADL-P, round 10 -> round 11): dev13 90.8 -> 90.9, dev11 90.4 -> 90.5, holdout5 91.8 (=), bhive1 91.8 (=), bhive3 91.9 -> 92.0;
gate holdout7 90.9 (=), holdout8 90.7 -> 90.8, bhive5 92.6 -> 93.4 (MAPE 3.18 -> 3.90), bhive6 91.5 -> 92.1.

All other configurations (the 12 Intel models and their variants) are byte-identical to round 10 in the fixture export; each CPU's
round-11 changes leave the other two CPUs' frozen predictions identical. The VEX compare-equal ones idiom is dependency-breaking on all
three machines (probes: ZEN3 2.45, ICX 3.2, ADL-P 3.0 cycles against 9.0 dependent); it is corrected for ICX and ADL-P, not for the frozen
ZEN3.

New generic parameters added after the ZEN3 part (off by default): `moveElimBlockedSlots`, `lsdLineDelivery`, `schedulerQueues`,
`fastAddBypassDelay`; `INSTR_CORRECTIONS` also accepts `lat_SR` and `divC`.

## 3. Validation harness (`microbench/`)

- `microbench/fuzz/`: random-loop generator, perf measurement, scoring (`fuzz_report.py`), held-out sets.
- `microbench/real/`: loops from BHive basic blocks (`bhive_gen.py`, `real_measure.py`).
- Microbenchmarks for individual rules (`renaming_test.sh`, `zero_idiom_test.sh`, ...), measurements in `microbench/measurements/`.
- `intel_regression.sh`: checks that the stock Intel models are unchanged.
- `71b229b` removed three one-off experiment scripts.

## 4. How to check that a change does not alter predictions

The speed changes were checked by comparing the complete detailed output, the JSON output and the HTML trace of the old and new code on 329 files (random loops, BHive blocks, all microbench microbenchmarks) × all 21 configurations, and by checking that results are the same for different `PYTHONHASHSEED` values. `-graph` and `-depGraph` were not compared (they need plotly and pydot).
