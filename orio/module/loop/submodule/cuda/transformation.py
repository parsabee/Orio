#
# Contains the CUDA transformation module
#

import orio.module.loop.ast_lib.forloop_lib, orio.module.loop.ast_lib.common_lib
import orio.main.util.globals as g
from orio.module.loop.ast import *

#----------------------------------------------------------------------------------------------------------------------
class Transformation(object):
    '''Code transformation'''

    # -----------------------------------------------------------------------------------------------------------------
    def __init__(self, stmt, devProps, targs):
      '''Instantiate a code transformation object'''
      self.stmt         = stmt
      self.devProps     = devProps
      self.threadCount  = targs['threadCount']
      self.cacheBlocks  = targs['cacheBlocks']
      self.pinHostMem   = targs['pinHostMem']
      self.streamCount  = targs['streamCount']
      self.domain       = targs['domain']
      self.dataOnDevice = targs['dataOnDevice']
      
      if self.streamCount > 1 and (self.devProps['deviceOverlap'] == 0 or self.devProps['asyncEngineCount'] == 0):
          g.err('orio.module.loop.submodule.cuda.transformation: ' +
                'device cannot handle overlaps or concurrent data transfers; so no speedup from streams')
      
      # control flag to perform device-side timing
      self.doDeviceTiming = False

      # ---------------------------------------------------------------------
      # analysis results; initial values are at defaults
      self.model = {
        'inputsize':   IdentExp('n'),
        'isReduction': False,
        'idents':      [],
        'scalars':     [],
        'arrays':      [],
        'rhs_arrays':  [],
        'lhss':        [],
        'intscalars':  [],
        'intarrays':   []
      }

      # tracks various state variables used during transformations
      self.state = {
        'pinnedIdents': [],
        'calc_offset': [],
        'calc_boffset': [],
        'dev_kernel_name': '',
        'dev_redkern_name': ''
      }

      # frequently used constants      
      self.cs = { 
        'nthreads': IdentExp('nthreads'),
        'nstreams': IdentExp('nstreams'),
        'nbytes':   IdentExp('nbytes'),
        'gridx':    IdentExp('dimGrid.x'),
        'soffset':  IdentExp('soffset'),
        'boffset':  IdentExp('boffset'),
        'chunklen': IdentExp('chunklen'),
        'chunkrem': IdentExp('chunkrem'),
        'istream':  IdentExp('istream'),
        'blks4chunk':  IdentExp('blks4chunk'),
        'blks4chunks': IdentExp('blks4chunks'),

        'int0':     NumLitExp(0, NumLitExp.INT),
        'int1':     NumLitExp(1, NumLitExp.INT),
        'int2':     NumLitExp(2, NumLitExp.INT),
        'int3':     NumLitExp(3, NumLitExp.INT),

        'sizeofDbl': FunCallExp(IdentExp('sizeof'), [IdentExp('double')]),
        
        'prefix': 'orcu_',
        'dev':    'dev_'
      }

      # transformation results/components 
      self.newstmts = {
        'hostDecls':      [],
        'deviceDims':     [],
        'streamAllocs':   [],
        'streamDeallocs': [],
        'mallocs':        [],
        'deallocs':       [],
        'h2dcopys':       [],
        'd2hcopys':       [],
        'kernell_calls':  [],
        'timerStart':     [],
        'timerStop':      [],
        'testNewOutput':  []
      }


    # -----------------------------------------------------------------------------------------------------------------
    def createDVarDecls(self):
      '''Create declarations of device-side variables corresponding to host-side variables'''
      intarrays = self.model['intarrays']
      hostDecls = [
        Comment('declare variables'),
        VarDecl('double', map(lambda x: '*'+x[1], self.model['idents']))
      ]
      if len(intarrays)>0:
        hostDecls += [VarDecl('int', map(lambda x: '*'+x[1], intarrays))]
      hostDecls += [
        VarDeclInit('int', self.cs['nthreads'], NumLitExp(self.threadCount, NumLitExp.INT))
      ]
      if self.streamCount > 1:
        hostDecls += [VarDeclInit('int', self.cs['nstreams'], NumLitExp(self.streamCount, NumLitExp.INT))]
      self.newstmts['hostDecls'] = hostDecls

      # free allocated memory and resources
      deallocs = [Comment('free allocated memory')]
      for _,dvar in self.model['idents']:
        deallocs += [ExpStmt(FunCallExp(IdentExp('cudaFree'), [IdentExp(dvar)]))]
      for _,dvar in self.model['intarrays']:
        deallocs += [ExpStmt(FunCallExp(IdentExp('cudaFree'), [IdentExp(dvar)]))]
      self.newstmts['deallocs'] = deallocs


    # -----------------------------------------------------------------------------------------------------------------
    def calcDims(self):
      '''Calculate device dimensions'''
      self.newstmts['deviceDims'] = [
        Comment('calculate device dimensions'),
        VarDecl('dim3', ['dimGrid', 'dimBlock']),
        ExpStmt(BinOpExp(IdentExp('dimBlock.x'), self.cs['nthreads'], BinOpExp.EQ_ASGN)),
        ExpStmt(BinOpExp(self.cs['gridx'],
                         BinOpExp(ParenthExp(BinOpExp(self.model['inputsize'],
                                                      BinOpExp(self.cs['nthreads'], self.cs['int1'], BinOpExp.SUB),
                                                      BinOpExp.ADD)),
                                  self.cs['nthreads'],
                                  BinOpExp.DIV),
                         BinOpExp.EQ_ASGN))
      ]


    # -----------------------------------------------------------------------------------------------------------------
    def createStreamDecls(self):
      '''Create stream declarations'''
      self.state['calc_offset'] = [
        ExpStmt(BinOpExp(self.cs['soffset'],
                         BinOpExp(self.cs['istream'], self.cs['chunklen'], BinOpExp.MUL),
                         BinOpExp.EQ_ASGN))
      ]
      self.state['calc_boffset'] = [
        ExpStmt(BinOpExp(self.cs['boffset'],
                         BinOpExp(self.cs['istream'], self.cs['blks4chunk'], BinOpExp.MUL),
                         BinOpExp.EQ_ASGN))
      ]

      self.newstmts['streamAllocs'] = [
        Comment('create streams'),
        VarDecl('int', [self.cs['istream'], self.cs['soffset']] + ([self.cs['boffset']] if self.model['isReduction'] else [])),
        VarDecl('cudaStream_t', ['stream[nstreams+1]']),
        ForStmt(BinOpExp(self.cs['istream'], self.cs['int0'],     BinOpExp.EQ_ASGN),
                BinOpExp(self.cs['istream'], self.cs['nstreams'], BinOpExp.LE),
                UnaryExp(self.cs['istream'], UnaryExp.POST_INC),
                ExpStmt(FunCallExp(IdentExp('cudaStreamCreate'),
                                           [UnaryExp(ArrayRefExp(IdentExp('stream'), self.cs['istream']), UnaryExp.ADDRESSOF)]))),
        VarDeclInit('int', self.cs['chunklen'], BinOpExp(self.model['inputsize'], self.cs['nstreams'], BinOpExp.DIV)),
        VarDeclInit('int', self.cs['chunkrem'], BinOpExp(self.model['inputsize'], self.cs['nstreams'], BinOpExp.MOD)),
      ]

      deallocs = []
      # unregister pinned memory
      for var in self.state['pinnedIdents']:
        deallocs += [ExpStmt(FunCallExp(IdentExp('cudaHostUnregister'), [IdentExp(var)]))]
      # destroy streams
      deallocs += [
        ForStmt(BinOpExp(self.cs['istream'], self.cs['int0'], BinOpExp.EQ_ASGN),
                BinOpExp(self.cs['istream'], self.cs['nstreams'], BinOpExp.LE),
                UnaryExp(self.cs['istream'], UnaryExp.POST_INC),
                ExpStmt(FunCallExp(IdentExp('cudaStreamDestroy'), [ArrayRefExp(IdentExp('stream'), self.cs['istream'])])))]
      self.newstmts['streamDeallocs'] = deallocs


    # -----------------------------------------------------------------------------------------------------------------
    def createMallocs(self):
      '''Create device-side mallocs'''
      mallocs  = [
        Comment('allocate device memory'),
        VarDeclInit('int', self.cs['nbytes'], BinOpExp(self.model['inputsize'], self.cs['sizeofDbl'], BinOpExp.MUL))
      ]
      h2dcopys = [Comment('copy data from host to device')]
      h2dasyncs    = []
      h2dasyncsrem = []
      # -------------------------------------------------
      for sid,dsid in self.model['scalars']:
        mallocs += [
          ExpStmt(FunCallExp(IdentExp('cudaMalloc'),
                             [CastExpr('void**', UnaryExp(IdentExp(dsid), UnaryExp.ADDRESSOF)),
                              self.cs['sizeofDbl']
                              ]))]
        h2dcopys += [
          ExpStmt(FunCallExp(IdentExp('cudaMemcpy'),
                             [IdentExp(dsid), UnaryExp(IdentExp(sid), UnaryExp.ADDRESSOF),
                              self.cs['sizeofDbl'],
                              IdentExp('cudaMemcpyHostToDevice')
                              ]))]

      # -------------------------------------------------
      pinnedIdents = []
      for aid,daid in self.model['arrays']:
        mallocs += [
          ExpStmt(FunCallExp(IdentExp('cudaMalloc'),
                             [CastExpr('void**', UnaryExp(IdentExp(daid), UnaryExp.ADDRESSOF)),
                              #self.cs['nbytes']
                              FunCallExp(IdentExp('sizeof'), [IdentExp(aid)])
                              ]))]
        # memcopy rhs arrays device to host
        if aid in self.model['rhs_arrays']:
          if self.streamCount > 1:
            # pin host memory while streaming
            mallocs += [
              ExpStmt(FunCallExp(IdentExp('cudaHostRegister'),
                                         [IdentExp(aid), self.model['inputsize'],
                                          IdentExp('cudaHostRegisterPortable')
                                          ]))
            ]
            pinnedIdents += [aid] # remember to unregister at the end
            h2dasyncs += [
              ExpStmt(FunCallExp(IdentExp('cudaMemcpyAsync'),
                                 [BinOpExp(IdentExp(daid),      self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(IdentExp(aid),       self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(self.cs['chunklen'], self.cs['sizeofDbl'], BinOpExp.MUL),
                                  IdentExp('cudaMemcpyHostToDevice'),
                                  ArrayRefExp(IdentExp('stream'), self.cs['istream']) ]))
            ]
            h2dasyncsrem += [
              ExpStmt(FunCallExp(IdentExp('cudaMemcpyAsync'),
                                 [BinOpExp(IdentExp(daid),      self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(IdentExp(aid),       self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(self.cs['chunkrem'], self.cs['sizeofDbl'], BinOpExp.MUL),
                                  IdentExp('cudaMemcpyHostToDevice'),
                                  ArrayRefExp(IdentExp('stream'), self.cs['istream']) ]))
            ]
          else:
            h2dcopys += [
              ExpStmt(FunCallExp(IdentExp('cudaMemcpy'),
                                 [IdentExp(daid), IdentExp(aid), #self.cs['nbytes'],
                                  FunCallExp(IdentExp('sizeof'), [IdentExp(aid)]),
                                  IdentExp('cudaMemcpyHostToDevice')
                                  ]))]
      # for-loop over streams to do async copies
      if self.streamCount > 1:
        h2dcopys += [
          ForStmt(BinOpExp(self.cs['istream'], self.cs['int0'], BinOpExp.EQ_ASGN),
                  BinOpExp(self.cs['istream'], self.cs['nstreams'], BinOpExp.LT),
                  UnaryExp(self.cs['istream'], UnaryExp.POST_INC),
                  CompStmt(self.state['calc_offset'] + h2dasyncs)),
          # copy the remainder in the last/reserve stream
          IfStmt(BinOpExp(self.cs['chunkrem'], self.cs['int0'], BinOpExp.NE),
                 CompStmt(self.state['calc_offset'] + h2dasyncsrem))
        ]

      for aid,daid in self.model['intarrays']:
        mallocs += [
          ExpStmt(FunCallExp(IdentExp('cudaMalloc'),
                             [CastExpr('void**', UnaryExp(IdentExp(daid), UnaryExp.ADDRESSOF)),
                              FunCallExp(IdentExp('sizeof'), [IdentExp(aid)])
                              ]))]
        # memcopy rhs arrays device to host
        if aid in self.model['rhs_arrays']:
          h2dcopys += [
            ExpStmt(FunCallExp(IdentExp('cudaMemcpy'),
                               [IdentExp(daid), IdentExp(aid), FunCallExp(IdentExp('sizeof'), [IdentExp(aid)]),
                                IdentExp('cudaMemcpyHostToDevice')
                                ]))]

      # -------------------------------------------------
      # malloc block-level result var
      if self.model['isReduction']:
        mallocs += [
          ExpStmt(FunCallExp(IdentExp('cudaMalloc'),
                             [CastExpr('void**', UnaryExp(IdentExp(self.cs['dev'] + self.model['lhss'][0]), UnaryExp.ADDRESSOF)),
                              BinOpExp(ParenthExp(BinOpExp(self.cs['gridx'], self.cs['int1'], BinOpExp.ADD)),
                                       self.cs['sizeofDbl'],
                                       BinOpExp.MUL)
                              ]))]

      # -------------------------------------------------
      d2hcopys = [Comment('copy data from device to host')]
      d2hasyncs    = []
      d2hasyncsrem = []
      for var in self.model['lhss']:
        res_scalar_ids = filter(lambda x: x[0] == var, self.model['scalars'])
        for rsid,drsid in res_scalar_ids:
          d2hcopys += [
            ExpStmt(FunCallExp(IdentExp('cudaMemcpy'),
                               [IdentExp(rsid), IdentExp(drsid),
                                self.cs['sizeofDbl'],
                                IdentExp('cudaMemcpyDeviceToHost')
                                ]))]
        res_array_ids  = filter(lambda x: x[0] == var, self.model['arrays'])
        for raid,draid in res_array_ids:
          if self.streamCount > 1:
            d2hasyncs += [
              ExpStmt(FunCallExp(IdentExp('cudaMemcpyAsync'),
                                 [BinOpExp(IdentExp(raid),  self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(IdentExp(draid), self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(self.cs['chunklen'], self.cs['sizeofDbl'], BinOpExp.MUL),
                                  IdentExp('cudaMemcpyDeviceToHost'),
                                  ArrayRefExp(IdentExp('stream'), self.cs['istream'])
                                  ]))]
            d2hasyncsrem += [
              ExpStmt(FunCallExp(IdentExp('cudaMemcpyAsync'),
                                 [BinOpExp(IdentExp(raid),  self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(IdentExp(draid), self.cs['soffset'], BinOpExp.ADD),
                                  BinOpExp(self.cs['chunkrem'], self.cs['sizeofDbl'], BinOpExp.MUL),
                                  IdentExp('cudaMemcpyDeviceToHost'),
                                  ArrayRefExp(IdentExp('stream'), self.cs['istream'])
                                  ]))]
          else:
            d2hcopys += [
              ExpStmt(FunCallExp(IdentExp('cudaMemcpy'),
                                 [IdentExp(raid), IdentExp(draid),
                                  #self.cs['nbytes'],
                                  FunCallExp(IdentExp('sizeof'), [IdentExp(raid)]),
                                  IdentExp('cudaMemcpyDeviceToHost')
                                  ]))]
      # -------------------------------------------------
      # memcpy block-level result var
      if self.model['isReduction']:
        d2hcopys += [
          ExpStmt(FunCallExp(IdentExp('cudaMemcpy'),
                             [UnaryExp(IdentExp(self.model['lhss'][0]),UnaryExp.ADDRESSOF),
                              IdentExp(self.cs['dev'] + self.model['lhss'][0]),
                              self.cs['sizeofDbl'],
                              IdentExp('cudaMemcpyDeviceToHost')
                              ]))]
      # -------------------------------------------------
      if self.streamCount > 1 and not self.model['isReduction']:
        d2hcopys += [ForStmt(BinOpExp(self.cs['istream'], self.cs['int0'], BinOpExp.EQ_ASGN),
                             BinOpExp(self.cs['istream'], self.cs['nstreams'], BinOpExp.LT),
                             UnaryExp(self.cs['istream'], UnaryExp.POST_INC),
                             CompStmt(self.state['calc_offset'] + d2hasyncs))]
        d2hcopys += [IfStmt(BinOpExp(self.cs['chunkrem'], self.cs['int0'], BinOpExp.NE),
                            CompStmt(self.state['calc_offset'] + d2hasyncsrem))]
        # synchronize
        d2hcopys += [ForStmt(BinOpExp(self.cs['istream'], self.cs['int0'], BinOpExp.EQ_ASGN),
                             BinOpExp(self.cs['istream'], self.cs['nstreams'], BinOpExp.LE),
                             UnaryExp(self.cs['istream'], UnaryExp.POST_INC),
                             ExpStmt(FunCallExp(IdentExp('cudaStreamSynchronize'), [ArrayRefExp(IdentExp('stream'), self.cs['istream'])])))]

      self.state['pinnedIdents'] = pinnedIdents
      self.newstmts['mallocs']  = mallocs
      self.newstmts['h2dcopys'] = h2dcopys
      self.newstmts['d2hcopys'] = d2hcopys


    # -----------------------------------------------------------------------------------------------------------------
    def createKernelCalls(self):
      '''Create kernel calls'''
      kernell_calls = [Comment('invoke device kernel')]
      kernell_calls += [ExpStmt(BinOpExp(IdentExp('orio_t_start'), FunCallExp(IdentExp('getClock'), []), BinOpExp.EQ_ASGN))]
      if self.streamCount == 1:
        args = [self.model['inputsize']] + self.model['intscalars'] \
          + map(lambda x: IdentExp(x[1]), self.model['intarrays']) \
          + map(lambda x: IdentExp(x[1]), self.model['idents'])
        kernell_call = ExpStmt(FunCallExp(IdentExp(self.state['dev_kernel_name']+'<<<dimGrid,dimBlock>>>'), args))# + self.state['domainArgs']))
        kernell_calls += [kernell_call]
      else:
        args    = [self.cs['chunklen']] + self.model['intscalars'] + map(lambda x: IdentExp(x[1]), self.model['intarrays'])
        argsrem = [self.cs['chunkrem']] + self.model['intscalars'] + map(lambda x: IdentExp(x[1]), self.model['intarrays'])
        # adjust array args using offsets
        dev_array_idss = map(lambda x: x[1], self.model['arrays'])
        for _,arg in self.model['idents']:
            if arg in dev_array_idss:
                args    += [BinOpExp(IdentExp(arg), self.cs['soffset'], BinOpExp.ADD)]
                argsrem += [BinOpExp(IdentExp(arg), self.cs['soffset'], BinOpExp.ADD)]
            elif arg == self.cs['dev']+self.model['lhss'][0]:
                args    += [BinOpExp(IdentExp(arg), self.cs['boffset'], BinOpExp.ADD)]
                argsrem += [BinOpExp(IdentExp(arg), self.cs['boffset'], BinOpExp.ADD)]
            else:
                args    += [IdentExp(arg)]
                argsrem += [IdentExp(arg)]
        kernell_call    = ExpStmt(FunCallExp(IdentExp(self.state['dev_kernel_name']+'<<<blks4chunk,dimBlock,0,stream['+str(self.cs['istream'])+']>>>'), args))
        kernell_callrem = ExpStmt(FunCallExp(IdentExp(self.state['dev_kernel_name']+'<<<blks4chunk,dimBlock,0,stream['+str(self.cs['istream'])+']>>>'), argsrem))
        kernell_calls += [
          # calc blocks per stream
          VarDeclInit('int', self.cs['blks4chunk'], BinOpExp(self.cs['gridx'], self.cs['nstreams'], BinOpExp.DIV)),
          IfStmt(BinOpExp(BinOpExp(self.cs['gridx'], self.cs['nstreams'], BinOpExp.MOD), self.cs['int0'], BinOpExp.NE),
                 ExpStmt(UnaryExp(self.cs['blks4chunk'], UnaryExp.POST_INC)))
        ]
        # calc total number of blocks to reduce
        boffsets = []
        if self.model['isReduction']:
          kernell_calls += [VarDeclInit('int', self.cs['blks4chunks'], BinOpExp(self.cs['blks4chunk'], self.cs['nstreams'], BinOpExp.MUL))]
          boffsets = self.state['calc_boffset']
        # kernel invocations
        kernell_calls += [
          ForStmt(BinOpExp(self.cs['istream'], self.cs['int0'], BinOpExp.EQ_ASGN),
                  BinOpExp(self.cs['istream'], self.cs['nstreams'], BinOpExp.LT),
                  UnaryExp(self.cs['istream'], UnaryExp.POST_INC),
                  CompStmt(self.state['calc_offset'] + boffsets + [kernell_call])),
          # kernel invocation on the last chunk
          IfStmt(BinOpExp(self.cs['chunkrem'], self.cs['int0'], BinOpExp.NE),
                 CompStmt(self.state['calc_offset'] + boffsets + [kernell_callrem] +
                              ([ExpStmt(UnaryExp(self.cs['blks4chunks'], UnaryExp.POST_INC))] if self.model['isReduction'] else [])))
        ]
      
      # -------------------------------------------------
      # for reductions, iteratively keep block-summing, until nothing more to sum: aka multi-staged reduction
      stageBlocks       = self.cs['prefix'] + 'blks'
      stageThreads      = self.cs['prefix'] + 'trds'
      stageBlocksIdent  = IdentExp(stageBlocks)
      stageThreadsIdent = IdentExp(stageThreads)
      sizeIdent         = IdentExp(self.cs['prefix'] + 'n')
      maxThreads           = self.devProps['maxThreadsPerBlock']
      maxThreadsPerBlock   = NumLitExp(str(maxThreads), NumLitExp.INT)
      maxThreadsPerBlockM1 = NumLitExp(str(maxThreads - 1), NumLitExp.INT)
      if self.model['isReduction']:
        if self.streamCount > 1:
          kernell_calls += [VarDeclInit('int', stageBlocksIdent,  self.cs['blks4chunks'])]
        else:
          kernell_calls += [VarDeclInit('int', stageBlocksIdent,  self.cs['gridx'])]
        bodyStmts = [
          ExpStmt(FunCallExp(IdentExp('cudaDeviceSynchronize'), [])),
          ExpStmt(BinOpExp(sizeIdent, stageBlocksIdent, BinOpExp.EQ_ASGN)),
          ExpStmt(BinOpExp(stageBlocksIdent,
                           BinOpExp(ParenthExp(BinOpExp(stageBlocksIdent, maxThreadsPerBlockM1, BinOpExp.ADD)),
                                        NumLitExp(str(maxThreads), NumLitExp.INT),
                                        BinOpExp.DIV),
                           BinOpExp.EQ_ASGN)),
          IfStmt(BinOpExp(sizeIdent, NumLitExp(str(maxThreads), NumLitExp.INT), BinOpExp.LT),
                 CompStmt([ExpStmt(BinOpExp(stageThreadsIdent, self.cs['int1'], BinOpExp.EQ_ASGN)),
                           WhileStmt(BinOpExp(stageThreadsIdent, sizeIdent, BinOpExp.LT),
                                     ExpStmt(BinOpExp(stageThreadsIdent, self.cs['int1'], BinOpExp.ASGN_SHL)))]),
                 ExpStmt(BinOpExp(stageThreadsIdent, maxThreadsPerBlock, BinOpExp.EQ_ASGN))),
          ExpStmt(FunCallExp(IdentExp(self.state['dev_redkern_name']+'<<<'+stageBlocks+','+stageThreads+'>>>'),
                             [sizeIdent, IdentExp(self.cs['dev']+self.model['lhss'][0])]))
        ]
        kernell_calls += [
          VarDecl('int', [stageThreadsIdent, sizeIdent]),
          WhileStmt(BinOpExp(stageBlocksIdent, self.cs['int1'], BinOpExp.GT), CompStmt(bodyStmts))
        ]
      self.newstmts['kernell_calls'] = kernell_calls


    # -----------------------------------------------------------------------------------------------------------------
    def transform(self):
        '''Transform the enclosed for-loop'''
        # get rid of compound statement that contains only a single statement
        while isinstance(self.stmt.stmt, CompStmt) and len(self.stmt.stmt.stmts) == 1:
            self.stmt.stmt = self.stmt.stmt.stmts[0]
        
        # extract for-loop structure
        index_id, _, ubound_exp, _, loop_body = orio.module.loop.ast_lib.forloop_lib.ForLoopLib().extractForLoopInfo(self.stmt)

        indices = [index_id.name]
        ktempints = []
        nestedLoop = False
        if isinstance(loop_body, ForStmt):
          index_id2, _, ubound_exp2, _, _ = orio.module.loop.ast_lib.forloop_lib.ForLoopLib().extractForLoopInfo(loop_body)
          nestedLoop = True
          indices += [index_id2.name]
          ktempints += [index_id2] # declare inner index

        # abbreviations
        loop_lib = orio.module.loop.ast_lib.common_lib.CommonLib()

        #--------------------------------------------------------------------------------------------------------------
        # analysis
        # collect all identifiers from the loop's upper bound expression
        collectIdents = lambda n: [n.name] if isinstance(n, IdentExp) else []
        
        # collect all LHS identifiers within the loop body
        def collectLhsIds(n):
          if isinstance(n, BinOpExp) and n.op_type == BinOpExp.EQ_ASGN:
            if isinstance(n.lhs, IdentExp):
              return [n.lhs.name]
            elif isinstance(n.lhs, ArrayRefExp):
              llhs = n.lhs.exp
              while isinstance(llhs, ArrayRefExp):
                llhs = llhs.exp
              if isinstance(llhs, IdentExp):
                return [llhs.name]
            else: return []
          else: return []
        def collectRhsIds(n):
          if isinstance(n, BinOpExp) and n.op_type == BinOpExp.EQ_ASGN:
            return loop_lib.collectNode(collectIdents, n.rhs)
          else: return []
        def collectIntIds(n):
          if isinstance(n, ArrayRefExp):
            return loop_lib.collectNode(collectIdents, n.sub_exp)
          else: return []
        def collectIntIdsClosure(inferredInts):
          def collectIntIds(n):
            # constrained C
            if isinstance(n, BinOpExp) and n.op_type == BinOpExp.EQ_ASGN and isinstance(n.lhs, IdentExp) and n.lhs.name in inferredInts:
              idents = loop_lib.collectNode(collectIdents, n.rhs)
              return idents
            else: return []
          return collectIntIds
        lhs_ids = loop_lib.collectNode(collectLhsIds, loop_body)
        rhs_ids = loop_lib.collectNode(collectRhsIds, loop_body)
        lhs_ids = filter(lambda x: x not in indices, lhs_ids)

        # collect all array and non-array idents in the loop body
        collectArrayIdents = lambda n: [n.exp.name] if (isinstance(n, ArrayRefExp) and isinstance(n.exp, IdentExp)) else []
        array_ids = set(loop_lib.collectNode(collectArrayIdents, loop_body))
        lhs_array_ids = list(set(lhs_ids).intersection(array_ids))
        rhs_array_ids = list(set(rhs_ids).intersection(array_ids))
        self.model['isReduction'] = len(lhs_array_ids) == 0
        self.model['rhs_arrays'] = rhs_array_ids
        self.model['lhss'] = lhs_ids


        #--------------------------------------------------------------------------------------------------------------
        # in validation mode, output original code's results and (later on) compare against transformed code's results
        if g.Globals().validationMode and not g.Globals().executedOriginal:
          original = self.stmt.replicate()
          printFpIdent = IdentExp('fp')
          testOrigOutput = [
            VarDeclInit('FILE*', printFpIdent, FunCallExp(IdentExp('fopen'), [StringLitExp('origexec.out'), StringLitExp('w')])),
            original
          ]
          bodyStmts = [original.stmt]
          for var in self.model['lhss']:
            if var in array_ids:
              bodyStmts += [ExpStmt(FunCallExp(IdentExp('fprintf'),
                [printFpIdent, StringLitExp("\'"+var+"[%d]\',%f; "), index_id, ArrayRefExp(IdentExp(var), index_id)])
              )]
            else:
              testOrigOutput += [ExpStmt(FunCallExp(IdentExp('fprintf'), [printFpIdent, StringLitExp("\'"+var+"\',%f"), IdentExp(var)]))]
          original.stmt = CompStmt(bodyStmts)
          testOrigOutput += [ExpStmt(FunCallExp(IdentExp('fclose'), [printFpIdent]))]
      
          return CompStmt(testOrigOutput)


        #--------------------------------------------------------------------------------------------------------------
        # begin rewrite the loop body
        # create decls for ubound_exp id's, assuming all ids are int's
        ubound_idss = map(lambda x: loop_lib.collectNode(collectIdents, x), [ubound_exp]+([ubound_exp2] if nestedLoop else []))
        ubound_ids = reduce(lambda acc,item: acc+item, ubound_idss, [])
        kernelParams = [FieldDecl('int', x) for x in ubound_ids]

        int_ids = set(filter(lambda x: x not in (indices+ubound_ids), loop_lib.collectNode(collectIntIds, loop_body)))
        int_ids_pass2 = set(filter(lambda x: x not in (indices+ubound_ids), loop_lib.collectNode(collectIntIdsClosure(int_ids), loop_body)))
        ktempints += list(int_ids)
        intarrays = list(int_ids_pass2.intersection(array_ids))
        array_ids = array_ids.difference(intarrays)

        # collect all identifiers from the loop body
        loop_body_ids = loop_lib.collectNode(collectIdents, loop_body)
        lbi = set(filter(lambda x: x not in (indices+ubound_ids+list(int_ids)+list(int_ids_pass2)), loop_body_ids))
        
        # create decls for loop body id's
        if self.model['isReduction']:
            lbi = lbi.difference(set(lhs_ids))
        kernelParams += [FieldDecl('int*', x) for x in intarrays]
        kernelParams += [FieldDecl('double*', x) for x in lbi]
        scalar_ids = list(lbi.difference(array_ids))
        
        # initialize with the results of the analysis
        dev = self.cs['dev']
        idents = list(lbi)
        if self.model['isReduction']:
          idents += [lhs_ids[0]]
        self.model['idents']  = map(lambda x: (x, dev+x), idents)
        self.model['scalars'] = map(lambda x: (x, dev+x), scalar_ids)
        self.model['arrays']  = map(lambda x: (x, dev+x), array_ids)
        self.model['inputsize'] = IdentExp(ubound_ids[0])
        self.model['intscalars'] = map(lambda x: IdentExp(x), ubound_ids[1:])
        self.model['intarrays']  = map(lambda x: (x, dev+x), intarrays)

        ktempdbls = []
        if self.model['isReduction']:
            for var in lhs_ids:
                tempIdent = IdentExp(self.cs['prefix'] + 'var' + str(g.Globals().getcounter()))
                ktempdbls += [tempIdent]
                rrLhs = lambda n: tempIdent if (isinstance(n, IdentExp) and n.name == var) else n
                loop_body = loop_lib.rewriteNode(rrLhs, loop_body)

        # add dereferences to all non-array id's in the loop body
        addDerefs2 = lambda n: ParenthExp(UnaryExp(n, UnaryExp.DEREF)) if (isinstance(n, IdentExp) and n.name in scalar_ids) else n
        loop_body2 = loop_lib.rewriteNode(addDerefs2, loop_body)

        collectLhsExprs = lambda n: [n.lhs] if isinstance(n, BinOpExp) and n.op_type == BinOpExp.EQ_ASGN else []
        loop_lhs_exprs = loop_lib.collectNode(collectLhsExprs, loop_body2)

        # replace all array indices with thread id
        tid = 'tid'
        tidIdent = IdentExp(tid)
        rewriteToTid = lambda x: tidIdent if isinstance(x, IdentExp) and x.name == index_id.name else x
        #rewriteArrayIndices = lambda n: ArrayRefExp(n.exp, loop_lib.rewriteNode(rewriteToTid, n.sub_exp)) if isinstance(n, ArrayRefExp) else n
        loop_body3 = loop_lib.rewriteNode(rewriteToTid, loop_body2)
        # end rewrite the loop body
        #--------------------------------------------------------------------------------------------------------------


        #--------------------------------------------------------------------------------------------------------------
        domainStmts   = []
        #domainArgs    = []
        domainParams  = []
        if self.domain != None:
          domainStmts = [Comment('stencil domain parameters')]
          gridn = 'gn'
          gridm = 'gm'
          #gridp = 'gp'
          dof   = 'dof'
          nos   = 'nos'
          sidx  = 'sidx'
          gridmIdent = IdentExp(gridm)
          gridnIdent = IdentExp(gridn)
          #gridpIdent = IdentExp(gridp)
          dofIdent   = IdentExp(dof)
          nosIdent   = IdentExp(nos)
          sidxIdent  = IdentExp(sidx)
          int4       = NumLitExp(4, NumLitExp.INT)
          int5       = NumLitExp(5, NumLitExp.INT)
          int6       = NumLitExp(6, NumLitExp.INT)
          int7       = NumLitExp(7, NumLitExp.INT)
          domainStmts += [
            VarDeclInit('int', gridmIdent, FunCallExp(IdentExp('round'), [
              FunCallExp(IdentExp('pow'), [self.model['inputsize'], CastExpr('double', BinOpExp(self.cs['int1'], self.cs['int3'], BinOpExp.DIV))])
            ])),
            VarDeclInit('int', gridnIdent, gridmIdent),
            #VarDeclInit('int', gridpIdent, gridmIdent),
            VarDeclInit('int', dofIdent, self.cs['int1']), # 1 dof
            VarDeclInit('int', nosIdent, int7), # 7 stencil points
            VarDecl('int', [sidx + '[' + nos + ']']),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, self.cs['int0']), self.cs['int0'], BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, self.cs['int1']), dofIdent, BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, self.cs['int2']), BinOpExp(gridmIdent, dofIdent, BinOpExp.MUL), BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, self.cs['int3']), BinOpExp(gridmIdent, BinOpExp(gridnIdent, dofIdent, BinOpExp.MUL), BinOpExp.MUL), BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, int4), UnaryExp(dofIdent, UnaryExp.MINUS), BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, int5), BinOpExp(UnaryExp(gridmIdent, UnaryExp.MINUS), dofIdent, BinOpExp.MUL), BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(ArrayRefExp(sidxIdent, int6), BinOpExp(UnaryExp(gridmIdent, UnaryExp.MINUS),
                                                                    BinOpExp(gridnIdent, dofIdent, BinOpExp.MUL), BinOpExp.MUL), BinOpExp.EQ_ASGN))
          ]
          for var in lhs_array_ids:
            domainStmts += [
              ExpStmt(FunCallExp(IdentExp('cudaMemset'), [IdentExp(var), self.cs['int0'], IdentExp('scSize')]))
            ]
          domainStmts += [
            ExpStmt(BinOpExp(IdentExp('dimGrid.x'), self.model['inputsize'], BinOpExp.EQ_ASGN)),
            ExpStmt(BinOpExp(IdentExp('dimBlock.x'), nosIdent, BinOpExp.EQ_ASGN))
            ]
          #domainArgs = [sidxIdent]
          domainParams = [FieldDecl('int*', sidx)]
          kernelParams += domainParams
        #--------------------------------------------------------------------------------------------------------------


        #--------------------------------------------------------------------------------------------------------------
        #--------------------------------------------------------------------------------------------------------------
        #--------------------------------------------------------------------------------------------------------------
        # begin generate the kernel
        idx        = self.cs['prefix'] + 'i'
        size       = self.cs['prefix'] + 'n'
        idxIdent   = IdentExp(idx)
        sizeIdent  = IdentExp(size)
        blockIdx   = IdentExp('blockIdx.x')
        blockSize  = IdentExp('blockDim.x')
        threadIdx  = IdentExp('threadIdx.x')
        tidVarDecl = VarDeclInit('int', tidIdent, BinOpExp(BinOpExp(blockIdx, blockSize, BinOpExp.MUL), threadIdx, BinOpExp.ADD))
        kernelStmts   = [tidVarDecl]
        redKernStmts  = [tidVarDecl]
        redkernParams = []
        cacheReads    = []
        cacheWrites   = []
        if self.cacheBlocks and not isinstance(loop_body3, ForStmt):
            for var in array_ids:
                sharedVar = 'shared_' + var
                kernelStmts += [
                    # __shared__ double shared_var[threadCount];
                    VarDecl('__shared__ double', [sharedVar + '[' + str(self.threadCount) + ']'])
                ]
                sharedVarExp = ArrayRefExp(IdentExp(sharedVar), threadIdx)
                varExp       = ArrayRefExp(IdentExp(var), tidIdent)
                
                # cache reads
                if var in rhs_array_ids:
                    cacheReads += [
                        # shared_var[threadIdx.x]=var[tid];
                        ExpStmt(BinOpExp(sharedVarExp, varExp, BinOpExp.EQ_ASGN))
                    ]
                # var[tid] -> shared_var[threadIdx.x]
                rrToShared = lambda n: sharedVarExp \
                                if isinstance(n, ArrayRefExp) and \
                                   isinstance(n.exp, IdentExp) and \
                                   n.exp.name == var \
                                else n
                rrRhsExprs = lambda n: BinOpExp(n.lhs, loop_lib.rewriteNode(rrToShared, n.rhs), n.op_type) \
                                if isinstance(n, BinOpExp) and \
                                   n.op_type == BinOpExp.EQ_ASGN \
                                else n
                loop_body3 = loop_lib.rewriteNode(rrRhsExprs, loop_body3)

                # cache writes also
                if var in lhs_array_ids:
                    rrLhsExprs = lambda n: BinOpExp(loop_lib.rewriteNode(rrToShared, n.lhs), n.rhs, n.op_type) \
                                    if isinstance(n, BinOpExp) and \
                                       n.op_type == BinOpExp.EQ_ASGN \
                                    else n
                    loop_body3 = loop_lib.rewriteNode(rrLhsExprs, loop_body3)
                    cacheWrites += [ExpStmt(BinOpExp(varExp, sharedVarExp, BinOpExp.EQ_ASGN))]

        if self.model['isReduction']:
            for temp in ktempdbls:
                kernelStmts += [VarDeclInit('double', temp, self.cs['int0'])]
        if len(ktempints) > 1:
            kernelStmts += [VarDecl('int', map(lambda x: IdentExp(x), ktempints))]

        #--------------------------------------------------
        if self.domain == None:
          # the rewritten loop body statement
          kernelStmts += [
            IfStmt(BinOpExp(tidIdent, ubound_exp, BinOpExp.LE),
                   CompStmt(cacheReads + [loop_body3] + cacheWrites))
          ]
        else:
          kernelStmts  = [VarDeclInit('int', tidIdent, BinOpExp(blockIdx, ArrayRefExp(sidxIdent, threadIdx), BinOpExp.ADD))]
          kernelStmts += [
            IfStmt(BinOpExp(BinOpExp(tidIdent, self.cs['int0'], BinOpExp.GE),
                            BinOpExp(tidIdent, self.model['inputsize'], BinOpExp.LT),
                            BinOpExp.LAND),
                   CompStmt([loop_body3]))
          ]

        #--------------------------------------------------
        # begin reduction statements
        reducts      = 'reducts'
        reductsIdent = IdentExp(reducts)
        blkdata      = self.cs['prefix'] + 'vec'+str(g.Globals().getcounter())
        blkdataIdent = IdentExp(blkdata)
        if self.model['isReduction']:
            kernelStmts += [Comment('reduce single-thread results within a block')]
            # declare the array shared by threads within a block
            kernelStmts += [VarDecl('__shared__ double', [blkdata+'['+str(self.threadCount)+']'])]
            # store the lhs/computed values into the shared array
            kernelStmts += [ExpStmt(BinOpExp(ArrayRefExp(blkdataIdent, threadIdx),
                                                     loop_lhs_exprs[0],
                                                     BinOpExp.EQ_ASGN))]
            # sync threads prior to reduction
            kernelStmts += [ExpStmt(FunCallExp(IdentExp('__syncthreads'),[]))];
            # at each step, divide the array into two halves and sum two corresponding elements
            kernelStmts += [VarDecl('int', [idx])]
            kernelStmts += [
                ForStmt(BinOpExp(idxIdent, BinOpExp(IdentExp('blockDim.x'), self.cs['int2'], BinOpExp.DIV), BinOpExp.EQ_ASGN),
                            BinOpExp(idxIdent, self.cs['int0'], BinOpExp.GT),
                            BinOpExp(idxIdent, self.cs['int1'], BinOpExp.ASGN_SHR),
                            CompStmt([IfStmt(BinOpExp(threadIdx, idxIdent, BinOpExp.LT),
                                                     ExpStmt(BinOpExp(ArrayRefExp(blkdataIdent, threadIdx),
                                                                              ArrayRefExp(blkdataIdent,
                                                                                              BinOpExp(threadIdx, idxIdent, BinOpExp.ADD)),
                                                                              BinOpExp.ASGN_ADD))
                                                     ),
                                          ExpStmt(FunCallExp(IdentExp('__syncthreads'),[]))]))
            ]
            # the first thread within a block stores the results for the entire block
            kernelParams += [FieldDecl('double*', reducts)]
            kernelStmts += [
                IfStmt(BinOpExp(threadIdx, self.cs['int0'], BinOpExp.EQ),
                           ExpStmt(BinOpExp(ArrayRefExp(reductsIdent, blockIdx),
                                                    ArrayRefExp(blkdataIdent, self.cs['int0']),
                                                    BinOpExp.EQ_ASGN)))
            ]
        # end reduction statements
        #--------------------------------------------------
        
        #--------------------------------------------------
        # begin multi-stage reduction kernel
        blkdata      = self.cs['prefix'] + 'vec'+str(g.Globals().getcounter())
        blkdataIdent = IdentExp(blkdata)
        if self.model['isReduction']:
          redkernParams += [FieldDecl('int', size), FieldDecl('double*', reducts)]
          redKernStmts += [VarDecl('__shared__ double', [blkdata+'['+str(self.devProps['maxThreadsPerBlock'])+']'])]
          redKernStmts += [IfStmt(BinOpExp(tidIdent, sizeIdent, BinOpExp.LT),
                                      ExpStmt(BinOpExp(ArrayRefExp(blkdataIdent, threadIdx),
                                                               ArrayRefExp(reductsIdent, tidIdent),
                                                               BinOpExp.EQ_ASGN)),
                                      ExpStmt(BinOpExp(ArrayRefExp(blkdataIdent, threadIdx),
                                                               self.cs['int0'],
                                                               BinOpExp.EQ_ASGN)))]
          redKernStmts += [ExpStmt(FunCallExp(IdentExp('__syncthreads'),[]))]
          redKernStmts += [VarDecl('int', [idx])]
          redKernStmts += [ForStmt(
            BinOpExp(idxIdent, BinOpExp(IdentExp('blockDim.x'), self.cs['int2'], BinOpExp.DIV), BinOpExp.EQ_ASGN),
            BinOpExp(idxIdent, self.cs['int0'], BinOpExp.GT),
            BinOpExp(idxIdent, self.cs['int1'], BinOpExp.ASGN_SHR),
            CompStmt([IfStmt(BinOpExp(threadIdx, idxIdent, BinOpExp.LT),
                                     ExpStmt(BinOpExp(ArrayRefExp(blkdataIdent, threadIdx),
                                                              ArrayRefExp(blkdataIdent,
                                                                              BinOpExp(threadIdx, idxIdent, BinOpExp.ADD)),
                                                              BinOpExp.ASGN_ADD))
                                     ),
                          ExpStmt(FunCallExp(IdentExp('__syncthreads'),[]))])
          )]
          redKernStmts += [
            IfStmt(BinOpExp(threadIdx, self.cs['int0'], BinOpExp.EQ),
                       ExpStmt(BinOpExp(ArrayRefExp(reductsIdent, blockIdx),
                                                ArrayRefExp(blkdataIdent, self.cs['int0']),
                                                BinOpExp.EQ_ASGN)))
          ]
        # end multi-stage reduction kernel
        #--------------------------------------------------

        dev_kernel_name = self.cs['prefix'] + 'kernel'+str(g.Globals().getcounter())
        dev_kernel = FunDecl(dev_kernel_name, 'void', ['__global__'], kernelParams, CompStmt(kernelStmts))
        self.state['dev_kernel_name'] = dev_kernel_name
        
        dev_redkern_name = self.cs['prefix'] + 'blksum'+str(g.Globals().getcounter())
        dev_redkern = FunDecl(dev_redkern_name, 'void', ['__global__'], redkernParams, CompStmt(redKernStmts))
        self.state['dev_redkern_name'] = dev_redkern_name
        
        # after getting interprocedural AST, make this a sub to that AST
        g.Globals().cunit_declarations += orio.module.loop.codegen.CodeGen('cuda').generator.generate(dev_kernel, '', '  ')
        if self.model['isReduction']:
          g.Globals().cunit_declarations += '\n' + orio.module.loop.codegen.CodeGen('cuda').generator.generate(dev_redkern, '', '  ')
        # end generate the kernel
        #--------------------------------------------------------------------------------------------------------------
        #--------------------------------------------------------------------------------------------------------------
        #--------------------------------------------------------------------------------------------------------------

        
        #--------------------------------------------------------------------------------------------------------------
        # begin marshal resources
        # declare device variables
        self.createDVarDecls()
        
        # calculate device dimensions
        self.calcDims()

        # if streaming, divide vectors into chunks and asynchronously overlap copy-copy and copy-exec ops
        if self.streamCount > 1:
          self.createStreamDecls()

        # malloc and memcpy
        self.createMallocs()
        
        # kernel calls
        self.createKernelCalls()
        # end marshal resources
        #--------------------------------------------------------------------------------------------------------------
        
        
        #--------------------------------------------------------------------------------------------------------------
        # cuda timing calls
        if self.doDeviceTiming:
          self.newstmts['timerStart'] = [
            VarDecl('cudaEvent_t', ['start', 'stop']),
            VarDecl('float', [self.cs['prefix'] + 'elapsed']),
            VarDecl('FILE*', [self.cs['prefix'] + 'fp']),
            ExpStmt(FunCallExp(IdentExp('cudaEventCreate'), [UnaryExp(IdentExp('start'), UnaryExp.ADDRESSOF)])),
            ExpStmt(FunCallExp(IdentExp('cudaEventCreate'), [UnaryExp(IdentExp('stop'),  UnaryExp.ADDRESSOF)])),
            ExpStmt(FunCallExp(IdentExp('cudaEventRecord'), [IdentExp('start'), self.cs['int0']]))
          ]
          self.newstmts['timerStop'] = [
            ExpStmt(FunCallExp(IdentExp('cudaEventRecord'), [IdentExp('stop'), self.cs['int0']])),
            ExpStmt(FunCallExp(IdentExp('cudaEventSynchronize'), [IdentExp('stop')])),
            ExpStmt(FunCallExp(IdentExp('cudaEventElapsedTime'),
                                       [UnaryExp(IdentExp(self.cs['prefix'] + 'elapsed'), UnaryExp.ADDRESSOF),
                                        IdentExp('start'), IdentExp('stop')])),
            AssignStmt(self.cs['prefix'] + 'fp',
                        FunCallExp(IdentExp('fopen'), [StringLitExp(self.cs['prefix'] + 'time.out'), StringLitExp('a')])),
            ExpStmt(FunCallExp(IdentExp('fprintf'),
                                       [IdentExp(self.cs['prefix'] + 'fp'),
                                        StringLitExp('Kernel_time@rep[%d]:%fms. '),
                                        IdentExp('orio_i'),
                                        IdentExp(self.cs['prefix'] + 'elapsed')])),
            ExpStmt(FunCallExp(IdentExp('fclose'), [IdentExp(self.cs['prefix'] + 'fp')])),
            ExpStmt(FunCallExp(IdentExp('cudaEventDestroy'), [IdentExp('start')])),
            ExpStmt(FunCallExp(IdentExp('cudaEventDestroy'), [IdentExp('stop')]))
          ]

        #--------------------------------------------------------------------------------------------------------------
        # in validation mode, output transformed codes' results for comparison with original code's results
        testNewOutput  = []
        if g.Globals().validationMode:
          printFpIdent = IdentExp('fp')
          original = ForStmt(
            BinOpExp(idxIdent, self.cs['int0'], BinOpExp.EQ_ASGN),
            BinOpExp(idxIdent, ubound_exp, BinOpExp.LE),
            UnaryExp(idxIdent, UnaryExp.POST_INC),
            Comment('placeholder')
          )
          testNewOutput = [
            VarDeclInit('FILE*', printFpIdent, FunCallExp(IdentExp('fopen'), [StringLitExp('newexec.out'), StringLitExp('w')])),
            VarDecl('int', [idxIdent]),
            original
          ]
          bodyStmts = []
          for var in self.model['lhss']:
            if var in array_ids:
              bodyStmts += [ExpStmt(FunCallExp(IdentExp('fprintf'),
                [printFpIdent, StringLitExp("\'"+var+"[%d]\',%f; "), idxIdent, ArrayRefExp(IdentExp(var), idxIdent)]))
              ]
            else:
              testNewOutput += [ExpStmt(
                FunCallExp(IdentExp('fprintf'), [printFpIdent, StringLitExp("\'"+var+"\',%f"), IdentExp(var)])
              )]
          original.stmt = CompStmt(bodyStmts)
          testNewOutput += [ExpStmt(FunCallExp(IdentExp('fclose'), [printFpIdent]))]
          self.newstmts['testNewOutput'] = testNewOutput

        #--------------------------------------------------------------------------------------------------------------
        # add up all components
        transformed_stmt = CompStmt(
            self.newstmts['hostDecls']
          + self.newstmts['deviceDims']
          + self.newstmts['streamAllocs']
          + self.newstmts['mallocs']
          + self.newstmts['h2dcopys']
          + self.newstmts['timerStart']
          + domainStmts
          + self.newstmts['kernell_calls']
          + self.newstmts['timerStop']
          + self.newstmts['d2hcopys']
          + self.newstmts['streamDeallocs']
          + self.newstmts['deallocs']
          + self.newstmts['testNewOutput']
        )
        return transformed_stmt


