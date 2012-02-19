#
# Contain the CUDA transformation module
#

import orio.module.loop.ast_lib.forloop_lib, orio.module.loop.ast_lib.common_lib
import orio.main.util.globals as g
import orio.module.loop.ast as ast

#----------------------------------------------------------------------------------------------------------------------

class Transformation:
    '''Code transformation'''

    def __init__(self, stmt, devProps, targs):
        '''Instantiate a code transformation object'''
        self.stmt        = stmt
        self.devProps    = devProps
        self.threadCount, self.cacheBlocks, self.pinHostMem = targs
        
    def transform(self):
        '''Transform the enclosed for-loop'''
        # get rid of compound statement that contains only a single statement
        while isinstance(self.stmt.stmt, ast.CompStmt) and len(self.stmt.stmt.stmts) == 1:
            self.stmt.stmt = self.stmt.stmt.stmts[0]
        
        # extract for-loop structure
        index_id, _, ubound_exp, _, loop_body = orio.module.loop.ast_lib.forloop_lib.ForLoopLib().extractForLoopInfo(self.stmt)

        loop_lib = orio.module.loop.ast_lib.common_lib.CommonLib()
        tcount = str(self.threadCount)
        int0 = ast.NumLitExp(0,ast.NumLitExp.INT)

        #--------------------------------------------------------------------------------------------------------------
        # begin rewrite the loop body
        # collect all identifiers from the loop's upper bound expression
        collectIdents = lambda n: [n.name] if isinstance(n, ast.IdentExp) else []
        ubound_ids = loop_lib.collectNode(collectIdents, ubound_exp)
        
        # create decls for ubound_exp id's, assuming all ids are int's
        kernelParams = [ast.FieldDecl('int', x) for x in ubound_ids]

        # collect all identifiers from the loop body
        loop_body_ids = loop_lib.collectNode(collectIdents, loop_body)
        lbi = set(filter(lambda x: x != index_id.name, loop_body_ids))
        
        # collect all LHS identifiers within the loop body
        def collectLhsIds(n):
            if isinstance(n, ast.BinOpExp) and n.op_type == ast.BinOpExp.EQ_ASGN:
                if isinstance(n.lhs, ast.IdentExp):
                    return [n.lhs.name]
                elif isinstance(n.lhs, ast.ArrayRefExp) and isinstance(n.lhs.exp, ast.IdentExp):
                    return [n.lhs.exp.name]
                else: return []
            else: return []
        lhs_ids = loop_lib.collectNode(collectLhsIds, loop_body)

        # collect all array and non-array idents in the loop body
        collectArrayIdents = lambda n: [n.exp.name] if (isinstance(n, ast.ArrayRefExp) and isinstance(n.exp, ast.IdentExp)) else []
        array_ids = set(loop_lib.collectNode(collectArrayIdents, loop_body))
        lhs_array_ids = list(set(lhs_ids).intersection(array_ids))
        rhs_array_ids = list(array_ids.difference(lhs_array_ids))
        isReduction = len(lhs_array_ids) == 0

        # create decls for loop body id's
        if isReduction:
            lbi = lbi.difference(set(lhs_ids))
        kernelParams += [ast.FieldDecl('double*', x) for x in lbi]
        scalar_ids = list(lbi.difference(array_ids))
        
        kernel_temps = []
        if isReduction:
            for var in lhs_ids:
                temp = 'orcuda_var_' + str(g.Globals().getcounter())
                kernel_temps += [temp]
                rrLhs = lambda n: ast.IdentExp(temp) if (isinstance(n, ast.IdentExp) and n.name == var) else n
                loop_body = loop_lib.rewriteNode(rrLhs, loop_body)

        # add dereferences to all non-array id's in the loop body
        addDerefs2 = lambda n: ast.ParenthExp(ast.UnaryExp(n, ast.UnaryExp.DEREF)) if (isinstance(n, ast.IdentExp) and n.name in scalar_ids) else n
        loop_body2 = loop_lib.rewriteNode(addDerefs2, loop_body)

        collectLhsExprs = lambda n: [n.lhs] if isinstance(n, ast.BinOpExp) and n.op_type == ast.BinOpExp.EQ_ASGN else []
        loop_lhs_exprs = loop_lib.collectNode(collectLhsExprs, loop_body2)

        # replace all array indices with thread id
        tid = 'tid'
        rewriteToTid = lambda x: ast.IdentExp(tid) if isinstance(x, ast.IdentExp) else x
        rewriteArrayIndices = lambda n: ast.ArrayRefExp(n.exp, loop_lib.rewriteNode(rewriteToTid, n.sub_exp)) if isinstance(n, ast.ArrayRefExp) else n
        loop_body3 = loop_lib.rewriteNode(rewriteArrayIndices, loop_body2)
        # end rewrite the loop body
        #--------------------------------------------------------------------------------------------------------------


        #--------------------------------------------------------------------------------------------------------------
        # begin generate the kernel
        kernelStmts = []
        blockIdx  = ast.IdentExp('blockIdx.x')
        blockSize = ast.IdentExp('blockDim.x')
        threadIdx = ast.IdentExp('threadIdx.x')
        kernelStmts += [
            ast.VarDeclInit('int', tid,
                            ast.BinOpExp(ast.BinOpExp(blockIdx, blockSize, ast.BinOpExp.MUL), threadIdx, ast.BinOpExp.ADD))
        ]
        cacheReads  = []
        cacheWrites = []
        if self.cacheBlocks:
            for var in array_ids:
                sharedVar = 'shared_' + var
                kernelStmts += [
                    # __shared__ double shared_var[threadCount];
                    ast.VarDecl('__shared__ double', [sharedVar + '[' + tcount + ']'])
                ]
                sharedVarExp = ast.ArrayRefExp(ast.IdentExp(sharedVar), threadIdx)
                varExp       = ast.ArrayRefExp(ast.IdentExp(var), ast.IdentExp(tid))
                
                # cache reads
                cacheReads += [
                    # shared_var[threadIdx.x]=var[tid];
                    ast.ExpStmt(ast.BinOpExp(sharedVarExp, varExp, ast.BinOpExp.EQ_ASGN))
                ]
                # var[tid] -> shared_var[threadIdx.x]
                rrToShared = lambda n: sharedVarExp \
                                if isinstance(n, ast.ArrayRefExp) and \
                                   isinstance(n.exp, ast.IdentExp) and \
                                   n.exp.name == var \
                                else n
                rrRhsExprs = lambda n: ast.BinOpExp(n.lhs, loop_lib.rewriteNode(rrToShared, n.rhs), n.op_type) \
                                if isinstance(n, ast.BinOpExp) and \
                                   n.op_type == ast.BinOpExp.EQ_ASGN \
                                else n
                loop_body3 = loop_lib.rewriteNode(rrRhsExprs, loop_body3)

                # cache writes also
                if var in lhs_array_ids:
                    rrLhsExprs = lambda n: ast.BinOpExp(loop_lib.rewriteNode(rrToShared, n.lhs), n.rhs, n.op_type) \
                                    if isinstance(n, ast.BinOpExp) and \
                                       n.op_type == ast.BinOpExp.EQ_ASGN \
                                    else n
                    loop_body3 = loop_lib.rewriteNode(rrLhsExprs, loop_body3)
                    cacheWrites += [ast.ExpStmt(ast.BinOpExp(varExp, sharedVarExp, ast.BinOpExp.EQ_ASGN))]

        if isReduction:
            for temp in kernel_temps:
                kernelStmts += [ast.VarDeclInit('double', temp, int0)]

        kernelStmts += [
            ast.IfStmt(ast.BinOpExp(ast.IdentExp(tid), ubound_exp, ast.BinOpExp.LE),
                       ast.CompStmt(cacheReads + [loop_body3] + cacheWrites))
        ]
        
        # begin reduction statements
        block_r = 'block_r'
        if isReduction:
            kernelStmts += [ast.Comment('reduce single-thread results within a block')]
            # declare the array shared by threads within a block
            kernelStmts += [ast.VarDecl('__shared__ double', ['cache['+tcount+']'])]
            # store the lhs/computed values into the shared array
            kernelStmts += [ast.AssignStmt('cache[threadIdx.x]',loop_lhs_exprs[0])]
            # sync threads prior to reduction
            kernelStmts += [ast.ExpStmt(ast.FunCallExp(ast.IdentExp('__syncthreads'),[]))];
            # at each step, divide the array into two halves and sum two corresponding elements
            # int i = blockDim.x/2;
            idx = 'i'
            idxId = ast.IdentExp(idx)
            int2 = ast.NumLitExp(2,ast.NumLitExp.INT)
            kernelStmts += [ast.VarDecl('int', [idx])]
            kernelStmts += [ast.AssignStmt(idx, ast.BinOpExp(ast.IdentExp('blockDim.x'), int2, ast.BinOpExp.DIV))]
            #while(i!=0){
            #  if(threadIdx.x<i)
            #    cache[threadIdx.x]+=cache[threadIdx.x+i];
            #  __syncthreads();
            # i/=2;
            #}
            kernelStmts += [ast.WhileStmt(ast.BinOpExp(idxId, int0, ast.BinOpExp.NE),
                                      ast.CompStmt([ast.IfStmt(ast.BinOpExp(threadIdx, idxId, ast.BinOpExp.LT),
                                                               ast.ExpStmt(ast.BinOpExp(ast.ArrayRefExp(ast.IdentExp('cache'), threadIdx),
                                                                                        ast.ArrayRefExp(ast.IdentExp('cache'),
                                                                                                        ast.BinOpExp(threadIdx,
                                                                                                                     idxId,
                                                                                                                     ast.BinOpExp.ADD)),
                                                                                        ast.BinOpExp.ASGN_ADD))
                                                               ),
                                                    ast.ExpStmt(ast.FunCallExp(ast.IdentExp('__syncthreads'),[])),
                                                    ast.AssignStmt(idx,ast.BinOpExp(idxId, int2, ast.BinOpExp.DIV))
                                                    ])
                                      )]
            # the first thread within a block stores the results for the entire block
            kernelParams += [ast.FieldDecl('double*', block_r)]
            # if(threadIdx.x==0) block_r[blockIdx.x]=cache[0];
            kernelStmts += [
                ast.IfStmt(ast.BinOpExp(threadIdx, int0, ast.BinOpExp.EQ),
                           ast.AssignStmt('block_r[blockIdx.x]',ast.ArrayRefExp(ast.IdentExp('cache'), int0)))
            ]
        # end reduction statements

        dev_kernel_name = 'orcuda_kern_'+str(g.Globals().getcounter())
        dev_kernel = ast.FunDecl(dev_kernel_name, 'void', ['__global__'], kernelParams, ast.CompStmt(kernelStmts))
        
        # after getting interprocedural AST, make this a sub to that AST
        g.Globals().cunit_declarations += orio.module.loop.codegen.CodeGen('cuda').generator.generate(dev_kernel, '', '  ')
        # end generate the kernel
        #--------------------------------------------------------------------------------------------------------------
        
        
        #--------------------------------------------------------------------------------------------------------------
        # begin marshal resources
        # declare device variables
        dev = 'dev_'
        dev_lbi = map(lambda x: dev+x, list(lbi))
        dev_block_r = dev + block_r
        host_ids = []
        if isReduction:
            dev_lbi  += [dev_block_r]
            host_ids += [block_r]
        hostDecls  = [ast.Comment('declare variables')]
        hostDecls += [ast.VarDecl('double', map(lambda x: '*'+x, dev_lbi + host_ids))]
        
        # calculate device dimensions
        hostDecls += [ast.VarDecl('dim3', ['dimGrid', 'dimBlock'])]
        gridxIdent = ast.IdentExp('dimGrid.x')
        host_arraysize = ubound_ids[0]
        # initialize grid size
        deviceDims  = [ast.Comment('calculate device dimensions')]
        deviceDims += [
            ast.ExpStmt(ast.BinOpExp(gridxIdent,
                                     ast.FunCallExp(ast.IdentExp('ceil'),
                                                    [ast.BinOpExp(ast.CastExpr('float', ast.IdentExp(host_arraysize)),
                                                                  ast.CastExpr('float', ast.IdentExp(tcount)),
                                                                  ast.BinOpExp.DIV)
                                                    ]),
                                     ast.BinOpExp.EQ_ASGN))]
        # initialize block size
        deviceDims += [ast.ExpStmt(ast.BinOpExp(ast.IdentExp('dimBlock.x'), ast.IdentExp(tcount), ast.BinOpExp.EQ_ASGN))]

        # allocate device memory
        # copy data from host to device
        mallocs  = [ast.Comment('allocate device memory')]
        h2dcopys = [ast.Comment('copy data from host to device')]
        dblIdent    = ast.IdentExp('double')
        sizeofIdent = ast.IdentExp('sizeof')
        dev_scalar_ids = map(lambda x: (x,dev+x), scalar_ids)
        for sid,dsid in dev_scalar_ids:
            # malloc scalars in the form of:
            # -- cudaMalloc((void**)&dev_alpha,sizeof(double));
            mallocs += [
                ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMalloc'),
                                           [ast.CastExpr('void**', ast.UnaryExp(ast.IdentExp(dsid), ast.UnaryExp.ADDRESSOF)),
                                            ast.FunCallExp(sizeofIdent, [dblIdent])
                                            ]))]
            # memcopy scalars in the form of:
            # -- cudaMemcpy(dev_alpha,&host_alpha,sizeof(double),cudaMemcpyHostToDevice);
            h2dcopys += [
                ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMemcpy'),
                                           [ast.IdentExp(dsid), ast.UnaryExp(ast.IdentExp(sid), ast.UnaryExp.ADDRESSOF),
                                            ast.FunCallExp(sizeofIdent, [dblIdent]),
                                            ast.IdentExp('cudaMemcpyHostToDevice')
                                            ]))]
        dev_array_ids = map(lambda x: (x,dev+x), array_ids)
        for aid,daid in dev_array_ids:
            # malloc arrays in the form of:
            # -- cudaMalloc((void**)&dev_X,host_arraysize*sizeof(double));
            mallocs += [
                ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMalloc'),
                                           [ast.CastExpr('void**', ast.UnaryExp(ast.IdentExp(daid), ast.UnaryExp.ADDRESSOF)),
                                            ast.BinOpExp(ast.IdentExp(host_arraysize),
                                                         ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                         ast.BinOpExp.MUL)
                                            ]))]
            # memcopy in the form of:
            # -- cudaMemcpy(dev_X,host_X,host_arraysize*sizeof(double),cudaMemcpyHostToDevice);
            if aid in rhs_array_ids:
                h2dcopys += [
                    ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMemcpy'),
                                               [ast.IdentExp(daid),
                                                ast.IdentExp(aid),
                                                ast.BinOpExp(ast.IdentExp(host_arraysize),
                                                             ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                             ast.BinOpExp.MUL),
                                                ast.IdentExp('cudaMemcpyHostToDevice')
                                                ]))]
        # malloc block-level result var
        if isReduction:
            mallocs += [
                ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMalloc'),
                                           [ast.CastExpr('void**', ast.UnaryExp(ast.IdentExp(dev_block_r), ast.UnaryExp.ADDRESSOF)),
                                            ast.BinOpExp(gridxIdent,
                                                         ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                         ast.BinOpExp.MUL)
                                            ]))]
            for var in host_ids:
                if self.pinHostMem:
                    mallocs += [
                        ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaHostAlloc'),
                                                   [ast.CastExpr('void**', ast.UnaryExp(ast.IdentExp(var), ast.UnaryExp.ADDRESSOF)),
                                                    ast.BinOpExp(ast.IdentExp(host_arraysize),
                                                                 ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                                 ast.BinOpExp.MUL),
                                                    ast.IdentExp('cudaHostAllocDefault')
                                                    ]))]
                else:
                    mallocs += [
                        ast.AssignStmt(var,
                                       ast.CastExpr('double*',
                                                    ast.FunCallExp(ast.IdentExp('malloc'),
                                                   [ast.BinOpExp(gridxIdent,
                                                                 ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                                 ast.BinOpExp.MUL)
                                                    ])))]
        # invoke device kernel function:
        # -- kernelFun<<<numOfBlocks,numOfThreads>>>(dev_vars, ..., dev_result);
        args = map(lambda x: ast.IdentExp(x), [host_arraysize] + dev_lbi)
        kernell_call = ast.ExpStmt(ast.FunCallExp(ast.IdentExp(dev_kernel_name+'<<<dimGrid,dimBlock>>>'), args))
        
        # copy data from devices to host
        # -- cudaMemcpy(host_Y,dev_Y,host_arraysize*sizeof(double),cudaMemcpyDeviceToHost);
        d2hcopys = [ast.Comment('copy data from device to host')]
        for var in lhs_ids:
            res_scalar_ids = filter(lambda x: x[1] == (dev+var), dev_scalar_ids)
            for rsid,drsid in res_scalar_ids:
                d2hcopys += [
                    ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMemcpy'),
                                                   [ast.IdentExp(rsid), ast.IdentExp(drsid),
                                                    ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                    ast.IdentExp('cudaMemcpyDeviceToHost')
                                                    ]))]
            res_array_ids  = filter(lambda x: x[1] == (dev+var), dev_array_ids)
            for raid,draid in res_array_ids:
                d2hcopys += [
                    ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMemcpy'),
                                                   [ast.IdentExp(raid), ast.IdentExp(draid),
                                                    ast.BinOpExp(ast.IdentExp(host_arraysize),
                                                                 ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                                 ast.BinOpExp.MUL),
                                                    ast.IdentExp('cudaMemcpyDeviceToHost')
                                                    ]))]
        # memcpy block-level result var
        if isReduction:
            d2hcopys += [
                    ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaMemcpy'),
                                                   [ast.IdentExp(block_r), ast.IdentExp(dev_block_r),
                                                    ast.BinOpExp(gridxIdent,
                                                                 ast.FunCallExp(sizeofIdent,[dblIdent]),
                                                                 ast.BinOpExp.MUL),
                                                    ast.IdentExp('cudaMemcpyDeviceToHost')
                                                    ]))]
        # reduce block-level results
        pp = [ast.Comment('post-processing on the host')]
        if isReduction:
            pp += [ast.VarDecl('int', ['i'])]
            pp += [ast.ForStmt(ast.BinOpExp(ast.IdentExp('i'), int0, ast.BinOpExp.EQ_ASGN),
                               ast.BinOpExp(ast.IdentExp('i'), gridxIdent, ast.BinOpExp.LT),
                               ast.UnaryExp(ast.IdentExp('i'), ast.UnaryExp.POST_INC),
                               ast.ExpStmt(ast.BinOpExp(ast.IdentExp(lhs_ids[0]),
                                                        ast.ArrayRefExp(ast.IdentExp(block_r), ast.IdentExp('i')),
                                                        ast.BinOpExp.ASGN_ADD)))]

        # free allocated variables
        free_vars = [ast.Comment('free allocated memory')]
        for dvar in dev_lbi:
            free_vars += [ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaFree'), [ast.IdentExp(dvar)]))]
        for hvar in host_ids:
            if self.pinHostMem:
                free_vars += [ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaFreeHost'), [ast.IdentExp(hvar)]))]
            else:
                free_vars += [ast.ExpStmt(ast.FunCallExp(ast.IdentExp('free'), [ast.IdentExp(hvar)]))]
        # end marshal resources
        #--------------------------------------------------------------------------------------------------------------
        
        
        #--------------------------------------------------------------------------------------------------------------
        # cuda timing calls
        timerDecls = [
            ast.VarDecl('cudaEvent_t', ['start', 'stop']),
            ast.VarDecl('float', ['orcuda_elapsed']),
            ast.VarDecl('FILE*', ['orcuda_fp'])
        ]
        timerStart = [
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventCreate'), [ast.UnaryExp(ast.IdentExp('start'), ast.UnaryExp.ADDRESSOF)])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventCreate'), [ast.UnaryExp(ast.IdentExp('stop'),  ast.UnaryExp.ADDRESSOF)])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventRecord'), [ast.IdentExp('start'), int0]))
        ]
        timerStop  = [
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventRecord'), [ast.IdentExp('stop'), int0])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventSynchronize'), [ast.IdentExp('stop')])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventElapsedTime'),
                                       [ast.UnaryExp(ast.IdentExp('orcuda_elapsed'), ast.UnaryExp.ADDRESSOF),
                                        ast.IdentExp('start'), ast.IdentExp('stop')])),
            ast.AssignStmt('orcuda_fp',
                        ast.FunCallExp(ast.IdentExp('fopen'), [ast.StringLitExp('orcuda_time.out'), ast.StringLitExp('a')])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('fprintf'),
                                       [ast.IdentExp('orcuda_fp'),
                                        ast.StringLitExp('Kernel_time@rep[%d]:%fms. '),
                                        ast.IdentExp('orio_i'),
                                        ast.IdentExp('orcuda_elapsed')])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('fclose'), [ast.IdentExp('orcuda_fp')])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventDestroy'), [ast.IdentExp('start')])),
            ast.ExpStmt(ast.FunCallExp(ast.IdentExp('cudaEventDestroy'), [ast.IdentExp('stop')]))
        ]
        #--------------------------------------------------------------------------------------------------------------
        
        transformed_stmt = ast.CompStmt(
            hostDecls + deviceDims + mallocs + h2dcopys
            +
            timerDecls + timerStart
            +
            [ast.Comment('invoke device kernel function'), kernell_call]
            +
            timerStop
            +
            d2hcopys + pp + free_vars
        )
        return transformed_stmt
    

