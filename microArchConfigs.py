import copy
from typing import Dict

class MicroArchConfig:
   def __init__(self, name, XEDName, IQWidth, DSBWidth, IDQWidth, issueWidth, RBWidth, RSWidth, retireWidth, pop5CRequiresComplexDecoder,
                macroFusibleInstrCanBeDecodedAsLastInstr, branchCanBeLastInstrInCachedBlock, both32ByteBlocksMustBeCacheable=False, nDecoders=4,
                preDecodeWidth=5, preDecodeBlockSize=16, predecodeDecodeDelay=3, issueDispatchDelay=5, DSB_MS_Stall=4, pop5CEndsDecodeGroup=True,
                high8RenamedSeparately=True, movzxHigh8AliasCanBeEliminated=True, moveEliminationPipelineLength=2, moveEliminationGPRSlots=4,
                moveEliminationSIMDSlots=4, moveEliminationGPRAllAliasesMustBeOverwritten=True, LSDEnabled=True, LSDUnrolling={}, fastPointerChasing=True,
                slow256BitMemAcc=False, DSBBlockSize=32, simplePortAssignment=False, isAMD=False, loadPorts='23', storeAddrPorts='78',
                storeDataPorts='49', fusiblePorts='237', dividerPort='0', loadLatency=5, portNames=None, experimental=False, portAssignment=None,
                renameImmediateFolding=False, takenBranchPort=None, memoryRenaming=None, sameRegMoveEliminated=False):
      self.name = name
      self.XEDName = XEDName # see obj/wkit/bin/xed -chip-check-list
      self.IQWidth = IQWidth # width of the instruction queue
      self.DSBWidth = DSBWidth
      self.IDQWidth = IDQWidth # width of the instruction decode queue
      self.issueWidth = issueWidth # number of (fused-domain) uops that can be issued per cycle
      self.RBWidth = RBWidth # width of the reorder buffer
      self.RSWidth = RSWidth # width of the reservation station
      self.retireWidth = retireWidth # number of uops that can be retired per cycle
      self.pop5CRequiresComplexDecoder = pop5CRequiresComplexDecoder # pop rsp and pop r12 require the complex decoder
      self.macroFusibleInstrCanBeDecodedAsLastInstr = macroFusibleInstrCanBeDecodedAsLastInstr # if True, a macro-fusible instr. can be decoded on the last decoder or when the instruction queue is empty
      self.branchCanBeLastInstrInCachedBlock = branchCanBeLastInstrInCachedBlock # probably because of JCC Erratum https://www.intel.com/content/dam/support/us/en/documents/processors/mitigations-jump-conditional-code-erratum.pdf
      self.both32ByteBlocksMustBeCacheable = both32ByteBlocksMustBeCacheable # a 32 byte block can only be in the DSB if the other 32 byte block in the same 64 byte block is also cacheable
      self.nDecoders = nDecoders # number of decoders
      self.preDecodeWidth = preDecodeWidth # number of instructions that can be predecoded per cycle
      self.preDecodeBlockSize = preDecodeBlockSize # block size of the predecoder
      self.predecodeDecodeDelay = predecodeDecodeDelay # minimum delay between predecoding and decoding
      self.issueDispatchDelay = issueDispatchDelay # minimum delay between issuing and dispatching
      self.DSB_MS_Stall = DSB_MS_Stall # number of stall cycles when switching from DSB to MS
      self.pop5CEndsDecodeGroup = pop5CEndsDecodeGroup # after pop rsp and pop r12, no other instr. can be decoded in the same cycle
      self.high8RenamedSeparately = high8RenamedSeparately # whether the high8 register are renamed separately from the low8 registers
      self.movzxHigh8AliasCanBeEliminated = movzxHigh8AliasCanBeEliminated # whether movzx can be eliminated if the second register has the same encoding as a high8 register
      self.moveEliminationPipelineLength = moveEliminationPipelineLength
      self.moveEliminationGPRSlots = moveEliminationGPRSlots # the number of slots or 'unlimited'
      self.moveEliminationSIMDSlots = moveEliminationSIMDSlots # the number of slots or 'unlimited'
      self.moveEliminationGPRAllAliasesMustBeOverwritten = moveEliminationGPRAllAliasesMustBeOverwritten
      self.LSDEnabled = LSDEnabled
      self.LSDUnrolling = LSDUnrolling
      self.fastPointerChasing = fastPointerChasing
      self.slow256BitMemAcc = slow256BitMemAcc # 256-bit memory load/store uops block the load/store units twice
      self.DSBBlockSize = DSBBlockSize
      self.simplePortAssignment = simplePortAssignment # assign ports with equal probability
      # Experimental AMD support: only the back end is modeled. The front end is reduced to a dispatch-width limit (in macro-ops), uops are
      # assigned to the least-loaded applicable port, and ports are named with single letters (see portNames).
      self.isAMD = isAMD
      self.loadPorts = loadPorts # ports with load AGUs; a uop on one of these ports is a load (or, if there is a store-data uop without address uop, a store-address) uop
      self.storeAddrPorts = storeAddrPorts # ports that can only be used by store-address uops
      self.storeDataPorts = storeDataPorts # ports used by store-data uops
      self.fusiblePorts = fusiblePorts # a uop on one of these ports can be micro-fused with the next uop of the instruction
      self.dividerPort = dividerPort # port that is connected to the divider
      self.loadLatency = loadLatency # latency of a load uop
      self.portNames = portNames or {} # display names for ports, e.g., {'a': 'ALU0'}
      self.experimental = experimental # not included in '-arch all'
      self.portAssignment = portAssignment # None: select the port assignment algorithm based on the number of ports; 'ICL': use the algorithm for ICL
      self.renameImmediateFolding = renameImmediateFolding # add/sub with an 8-bit immediate, inc, dec, and lea with base (+disp.) are handled by the renamer
      self.takenBranchPort = takenBranchPort # if set, the branch at the end of the loop can only use this port
      # Memory renaming: a load that reads what an earlier store to the same address (with the same addressing expression) wrote gets the value
      # directly from the register that the store read. None: not supported; 'data': the instructions are marked in the instruction data
      # (convertXML.py); 'latency': read-modify-write instructions for which uops.info measured a memory-to-memory latency of at most 1 cycle
      self.memoryRenaming = memoryRenaming
      self.sameRegMoveEliminated = sameRegMoveEliminated # whether 'mov eax, eax' etc. are eliminated (only used for the experimental configurations)

MicroArchConfigs: Dict[str, MicroArchConfig] = {}

MicroArchConfigs['SKL'] = MicroArchConfig( # https://en.wikichip.org/wiki/intel/microarchitectures/skylake_(client)#Pipeline
   name = 'SKL',
   XEDName = 'SKYLAKE',
   IQWidth = 25,
   # nDecoders = 4, # wikichip seems to be wrong
   DSBWidth = 6,
   IDQWidth = 64,
   issueWidth = 4,
   RBWidth = 224,
   RSWidth = 97,
   retireWidth = 4,
   pop5CRequiresComplexDecoder = True,
   pop5CEndsDecodeGroup = False,
   macroFusibleInstrCanBeDecodedAsLastInstr = True,
   branchCanBeLastInstrInCachedBlock = False,
   both32ByteBlocksMustBeCacheable = True,
   movzxHigh8AliasCanBeEliminated = False,
   moveEliminationPipelineLength = 2,
   LSDEnabled = False,
   DSB_MS_Stall = 2,
)

MicroArchConfigs['SKX'] = copy.deepcopy(MicroArchConfigs['SKL'])
MicroArchConfigs['SKX'].name = 'SKX'
MicroArchConfigs['SKX'].XEDName = 'SKYLAKE_SERVER'

MicroArchConfigs['KBL'] = copy.deepcopy(MicroArchConfigs['SKL'])
MicroArchConfigs['KBL'].name = 'KBL'

MicroArchConfigs['CFL'] = copy.deepcopy(MicroArchConfigs['SKL'])
MicroArchConfigs['CFL'].name = 'CFL'

MicroArchConfigs['CLX'] = copy.deepcopy(MicroArchConfigs['SKL'])
MicroArchConfigs['CLX'].name = 'CLX'
MicroArchConfigs['CLX'].XEDName = 'CASCADE_LAKE'
MicroArchConfigs['CLX'].LSDEnabled = True
MicroArchConfigs['CLX'].LSDUnrolling = {1:2, 2:2, 3:6, 4:6, 5:6, 6:2, 7:3, 8:3, 9:3, 10:3, 11:3, 12:3, 13:3, 14:2, 15:2, 16:2, 17:2, 18:2, 19:2, 20:2,
                                        21:2, 22:2, 23:2, 24:2, 25:2, 26: 2, 27:2, 28:2}

MicroArchConfigs['HSW'] = MicroArchConfig( # https://en.wikichip.org/wiki/intel/microarchitectures/haswell_(client)#Core
   name = 'HSW',
   XEDName = 'HASWELL',
   IQWidth = 20,
   DSBWidth = 4,
   IDQWidth = 56,
   issueWidth = 4,
   RBWidth = 192,
   RSWidth = 60,
   retireWidth = 4,
   pop5CRequiresComplexDecoder = True,
   pop5CEndsDecodeGroup = True,
   macroFusibleInstrCanBeDecodedAsLastInstr = False,
   branchCanBeLastInstrInCachedBlock = True,
   both32ByteBlocksMustBeCacheable = False,
   movzxHigh8AliasCanBeEliminated = False,
   moveEliminationPipelineLength = 2,
   DSB_MS_Stall = 4,
   LSDUnrolling = {1:8, 2:8, 3:8, 4:8, 5:6, 6:5, 7:4, 8:4, 9:3, 10:3, 11:3, 12:3, 13:2, 14:2, 15:2, 16: 2, 17:2, 18:2, 19:2,
                   20: 2, 21:2, 22:2, 23:2, 24:2, 25:2, 26:2, 27:2, 28: 2}
)

MicroArchConfigs['BDW'] = copy.deepcopy(MicroArchConfigs['HSW'])
MicroArchConfigs['BDW'].name = 'BDW'
MicroArchConfigs['BDW'].XEDName = 'BROADWELL'

MicroArchConfigs['IVB'] = MicroArchConfig( # https://en.wikichip.org/wiki/intel/microarchitectures/ivy_bridge_(client)
   name = 'IVB',
   XEDName = 'IVYBRIDGE',
   IQWidth = 20,
   DSBWidth = 4,
   IDQWidth = 56,
   issueWidth = 4,
   RBWidth = 168,
   RSWidth = 54,
   retireWidth = 4,
   pop5CRequiresComplexDecoder = True,
   pop5CEndsDecodeGroup = True,
   macroFusibleInstrCanBeDecodedAsLastInstr = False,
   branchCanBeLastInstrInCachedBlock = True,
   both32ByteBlocksMustBeCacheable = False,
   moveEliminationPipelineLength = 3,
   moveEliminationGPRAllAliasesMustBeOverwritten = False,
   LSDUnrolling = {},
   slow256BitMemAcc = True
)

MicroArchConfigs['SNB'] = copy.deepcopy(MicroArchConfigs['IVB'])
MicroArchConfigs['SNB'].name = 'SNB'
MicroArchConfigs['SNB'].XEDName = 'SANDYBRIDGE'
MicroArchConfigs['SNB'].IDQWidth = 28

MicroArchConfigs['ICL'] = MicroArchConfig( # https://en.wikichip.org/wiki/intel/microarchitectures/sunny_cove
   name = 'ICL',
   XEDName = 'ICE_LAKE',
   IQWidth = 25, # ?
   DSBWidth = 6,
   IDQWidth = 70,
   issueWidth = 5,
   RBWidth = 352,
   RSWidth = 160,
   retireWidth = 8,
   pop5CRequiresComplexDecoder = True,
   pop5CEndsDecodeGroup = False,
   macroFusibleInstrCanBeDecodedAsLastInstr = True,
   branchCanBeLastInstrInCachedBlock = True,
   LSDEnabled = True,
   DSB_MS_Stall = 2,
   fastPointerChasing = False,
   high8RenamedSeparately = False,
   movzxHigh8AliasCanBeEliminated = False,
   moveEliminationGPRSlots = 0,
   moveEliminationSIMDSlots = 'unlimited',
   LSDUnrolling = {1:6, 2:6, 3:6, 4:6, 5:6, 6:6, 7:4, 8:4, 9:3, 10:3, 11:3, 12:3, 13:2, 14:2, 15:2, 16:2, 17:2, 18:2, 19:2,
                   20:2, 21:2, 22:2, 23:2, 24:2, 25:2, 26:2, 27:2, 28:2, 29:2, 30:2},
   DSBBlockSize = 64
)

MicroArchConfigs['TGL'] = copy.deepcopy(MicroArchConfigs['ICL'])
MicroArchConfigs['TGL'].name = 'TGL'
MicroArchConfigs['TGL'].XEDName = 'TIGER_LAKE'

MicroArchConfigs['RKL'] = copy.deepcopy(MicroArchConfigs['ICL'])
MicroArchConfigs['RKL'].name = 'RKL'
MicroArchConfigs['RKL'].moveEliminationGPRSlots = 'unlimited'

MicroArchConfigs['CLX_SimplePorts'] = copy.deepcopy(MicroArchConfigs['CLX'])
MicroArchConfigs['CLX_SimplePorts'].simplePortAssignment = True

MicroArchConfigs['CLX_noLSD'] = copy.deepcopy(MicroArchConfigs['CLX'])
MicroArchConfigs['CLX_noLSD'].LSDEnabled = False

MicroArchConfigs['CLX_noLSDUnrolling'] = copy.deepcopy(MicroArchConfigs['CLX'])
MicroArchConfigs['CLX_noLSDUnrolling'].LSDUnrolling = {}

MicroArchConfigs['CLX_noMoveElim'] = copy.deepcopy(MicroArchConfigs['CLX'])
MicroArchConfigs['CLX_noMoveElim'].moveEliminationGPRSlots = 0
MicroArchConfigs['CLX_noMoveElim'].moveEliminationSIMDSlots = 0

MicroArchConfigs['CLX_fullMoveElim'] = copy.deepcopy(MicroArchConfigs['CLX'])
MicroArchConfigs['CLX_fullMoveElim'].moveEliminationGPRSlots = 'unlimited'
MicroArchConfigs['CLX_fullMoveElim'].moveEliminationSIMDSlots = 'unlimited'

MicroArchConfigs['CLX_SimplePorts_noMoveElim'] = copy.deepcopy(MicroArchConfigs['CLX'])
MicroArchConfigs['CLX_SimplePorts_noMoveElim'].simplePortAssignment = True
MicroArchConfigs['CLX_SimplePorts_noMoveElim'].moveEliminationGPRSlots = 0
MicroArchConfigs['CLX_SimplePorts_noMoveElim'].moveEliminationSIMDSlots = 0

# Experimental: AMD Zen 3 (family 19h). Back end only; see the comments at 'isAMD' above.
# Sources: AMD Software Optimization Guide for Family 19h Processors (SOG 19h) as cited in LLVM's X86ScheduleZnver3.td, and measurements on
# a Ryzen 7 7735U (Zen 3+).
#   ALU0-3 = a-d (ALU0: divider; ALU1: multiplier; ALU0 and ALU3: branches, see convertXML.py), AGU0-2 = g-i, integer store data = s,t
#   (at most two stores per cycle), FP0-5 = k-p, FP store data = x
MicroArchConfigs['ZEN3'] = MicroArchConfig(
   name = 'ZEN3',
   XEDName = 'AMD_FUTURE', # the XED version used here has no chip definition for Zen 3
   IQWidth = 25, # not used (no front-end model)
   DSBWidth = 8, # not used (no front-end model)
   IDQWidth = 64, # not used (no front-end model)
   issueWidth = 6, # macro-ops dispatched per cycle (SOG 19h, 2.9.6; confirmed by measurement)
   RBWidth = 256, # SOG 19h, 2.10.3
   RSWidth = 160, # 4x24 integer + 2x32 FP scheduler entries; modeled as one pool
   retireWidth = 8, # SOG 19h, 2.10.3
   pop5CRequiresComplexDecoder = False,
   pop5CEndsDecodeGroup = False,
   macroFusibleInstrCanBeDecodedAsLastInstr = True,
   branchCanBeLastInstrInCachedBlock = True,
   high8RenamedSeparately = False,
   moveEliminationGPRSlots = 'unlimited',
   moveEliminationSIMDSlots = 'unlimited',
   LSDEnabled = False,
   fastPointerChasing = False,
   isAMD = True,
   experimental = True,
   memoryRenaming = 'data',
   sameRegMoveEliminated = True, # perf, Ryzen 7 7735U (zenbench SET=movs): 'mov r11d, r11d; sub r11, r12' runs at 1 cycle per iteration
   loadPorts = 'ghi',
   storeAddrPorts = 'yz', # virtual ports for the store-address uops of read-modify-write instructions; see convertXML.py
   storeDataPorts = 'stx',
   fusiblePorts = 'ghi',
   dividerPort = 'a',
   loadLatency = 4, # SOG 19h, 2.12 (integer loads)
   portNames = {'a': 'ALU0', 'b': 'ALU1', 'c': 'ALU2', 'd': 'ALU3', 'g': 'AGU0', 'h': 'AGU1', 'i': 'AGU2', 's': 'SD0', 't': 'SD1',
                'k': 'FP0', 'l': 'FP1', 'm': 'FP2', 'n': 'FP3', 'o': 'FP4', 'p': 'FP5', 'x': 'FPSt', 'y': '(SA0)', 'z': '(SA1)'},
)

# Experimental: Alder Lake P-cores (Golden Cove). Based on the ICL configuration; apart from the LSD, the front-end parameters and the port
# assignment were not reverse-engineered for this microarchitecture (use -simpleFrontEnd to ignore the front end).
# Widths and buffer sizes are the commonly cited figures for Golden Cove; they were NOT checked against Intel's optimization manual. The
# reservation station is modeled as one pool. Ports as named by uops.info: 0, 1, 5, 6, B (ALUs), 2, 3, A (loads), 4, 9 (store data), 7, 8 (store address).
# Measured on a Core i7-12650H: register moves are eliminated, and the instructions that uops.info reports with zero uops (64-bit add/sub with an
# 8-bit immediate, inc, dec, lea with base and displacement) have zero latency but occupy an issue slot.
MicroArchConfigs['ADL-P'] = copy.deepcopy(MicroArchConfigs['ICL'])
MicroArchConfigs['ADL-P'].name = 'ADL-P'
MicroArchConfigs['ADL-P'].XEDName = 'ALDER_LAKE'
MicroArchConfigs['ADL-P'].nDecoders = 6
MicroArchConfigs['ADL-P'].DSBWidth = 8
MicroArchConfigs['ADL-P'].IDQWidth = 144
MicroArchConfigs['ADL-P'].issueWidth = 6
MicroArchConfigs['ADL-P'].RBWidth = 512
MicroArchConfigs['ADL-P'].RSWidth = 205 # unverified
MicroArchConfigs['ADL-P'].retireWidth = 8
MicroArchConfigs['ADL-P'].moveEliminationGPRSlots = 'unlimited'
# LSD: measured on a Core i7-12650H with perf (zenbench/lsd_experiment.py): loops of nops with up to 35 uops are delivered by the LSD, and
# their cycle counts are explained by these unroll counts (for loops with fewer than 7 uops, the count cannot be determined this way).
MicroArchConfigs['ADL-P'].LSDEnabled = True
MicroArchConfigs['ADL-P'].LSDUnrolling = dict([(7, 9), (8, 9)] + [(n, 5) for n in range(9, 19)] + [(n, 3) for n in range(19, 33)] + [(n, 2) for n in range(33, 36)])
MicroArchConfigs['ADL-P'].loadPorts = '23A'
MicroArchConfigs['ADL-P'].fusiblePorts = '237A'
MicroArchConfigs['ADL-P'].portAssignment = 'ICL'
MicroArchConfigs['ADL-P'].renameImmediateFolding = True
# perf, Core i7-12650H: the (macro-fused) branch at the end of a loop is always executed on port 6, while branches that are not taken
# also use port 0 (e.g., zenbench loops imul_indep3 and test_jcc3)
MicroArchConfigs['ADL-P'].takenBranchPort = '6'
# perf, Core i7-12650H (zenbench SET=rmw): e.g., 'add dword ptr [rsi+64], 3' and 'add byte ptr [rsi+64], 3' run at 1 cycle per iteration, while the
# forms with a register source and the 16-bit forms take more than 7 cycles. This agrees with the memory-to-memory latencies measured by
# uops.info (1 vs. 6 or more cycles).
MicroArchConfigs['ADL-P'].memoryRenaming = 'latency'
MicroArchConfigs['ADL-P'].experimental = True
