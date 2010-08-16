#
# Contain the semantic checker
#

import sys
from orio.main.util.globals import *
import orio.module.loop.ast, orio.module.loop.ast_lib.forloop_lib

#-----------------------------------------

class SemanticChecker:
    '''Semantic checker'''

    def __init__(self, stmt):
        '''To instantiate a semantic checker instance'''

        self.stmt = stmt
        self.flib = orio.module.loop.ast_lib.forloop_lib.ForLoopLib()

    #----------------------------------------------------------

    def __checkIdenticalNestedLoop(self, stmt, outer_loops):
        '''To ensure that no loops with the same iteration variable name are nested'''

        if isinstance(stmt, orio.module.loop.ast.ExpStmt):
            pass
            
        elif isinstance(stmt, orio.module.loop.ast.CompStmt):
            for s in stmt.stmts:
                self.__checkIdenticalNestedLoop(s, outer_loops)
            
        elif isinstance(stmt, orio.module.loop.ast.IfStmt):
            self.__checkIdenticalNestedLoop(stmt.true_stmt, outer_loops)
            if stmt.false_stmt:
                self.__checkIdenticalNestedLoop(stmt.false_stmt, outer_loops)
            
        elif isinstance(stmt, orio.module.loop.ast.ForStmt):
            for_loop_info = self.flib.extractForLoopInfo(stmt)
            index_id, lbound_exp, ubound_exp, stride_exp, loop_body = for_loop_info
            if index_id.name in outer_loops:
                err('module.loop.submodule.regtile.semant: loops with the same iteration name "%s" cannot be nested' %
                       index_id.name)
            n_outer_loops = outer_loops.copy()
            n_outer_loops[index_id.name] = None
            self.__checkIdenticalNestedLoop(stmt.stmt, n_outer_loops)

        elif isinstance(stmt, orio.module.loop.ast.TransformStmt):
            err('module.loop.submodule.regtile.semant internal error: unprocessed transform statement')
                        
        elif isinstance(stmt, orio.module.loop.ast.NewAST):
            pass

        else:
            err('module.loop.submodule.regtile.semant internal error: unexpected AST type: "%s"' % stmt.__class__.__name__)

    #----------------------------------------------------------
    
    def check(self):
        '''
        To perform semantic checking in order to ensure that register tiling transformation
        will not change the semantics of the given statement
        '''

        self.__checkIdenticalNestedLoop(self.stmt, {})

        
    
