void MatMatMult(double* A, double* B, double* C, int n) {

/*@ begin PerfTuning (
    def performance_params {
        param thread_count[]  = [32, 64];
        param block_count[]  = range(14,28,14);
        param inner_loop_unroll_fact[] = range(1, 5);
        param preferred_L1_cache[]  = [16, 48];
        param stream_count[] = [1, 2, 4, 8];
        param CFLAGS[] = ['-O3'];
    }

    def input_params
    {
        param CONT = 500;
        param NCONT = 500;
        param M = 500;
    }

    def input_vars
    {
        decl static double A[M * M] = random;
        decl static double B[M * M] = random;
        decl static double C[M * M] = 0;
    }

    def search
    {
        arg algorithm = 'Randomlocal';
        arg total_runs = 1000;
    }

    def build {
      arg build_command = 'nvcc -arch=sm_75 @CFLAGS';
    }

    def performance_counter {
      arg method = 'basic timer';
      arg repetitions = 1;
    }
) @*/

int n = M;

#define max(x,y)    ((x) > (y)? (x) : (y))
#define min(x,y)    ((x) < (y)? (x) : (y))

/*@ begin Loop(
  transform CUDA(threadCount=thread_count,
                 blockCount=block_count,
                 preferL1Size=preferred_L1_cache,
                 unrollInner=inner_loop_unroll_fact,
                 streamCount=stream_count)
  for(i=0; i<=n-1; i++)
    for(j=0; j<=n-1; j++) {
      for(k=0; k<=n-1; k++){
        C[i*n+j] += A[i*n+k]*B[k*n+j];
      }
    }
) @*/

/*@ end @*/
/*@ end @*/


}



