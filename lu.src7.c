void LU(double* A, double* L, double* U, int n) {

/*@ begin PerfTuning (
    def performance_params {
        param thread_count[]  = [32, 64];
        param block_count[]  = range(14,28,14);
        param inner_loop_unroll_fact[] = range(1, 5);
        param preferred_L1_cache[]  = [16, 48];
        param stream_count[] = [2];
        param CFLAGS[] = ['-O3'];
    }

    def input_params
    {
      param N = 500;
    }

    def input_vars
    {
        decl static double L[N * N] = random;
        decl static double U[N * N] = random;
        decl static double A[N * N] = random;

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

int n = N;
int m = N;

#define max(x,y)    ((x) > (y)? (x) : (y))
#define min(x,y)    ((x) < (y)? (x) : (y))

/*@ begin Loop(
  transform CUDA(threadCount=thread_count,
                 blockCount=block_count,
                 preferL1Size=preferred_L1_cache,
                 unrollInner=inner_loop_unroll_fact,
                 streamCount=stream_count)
    for (k=0; k<=n-1; k++) {
      for (j=k+1; j<=m-1; j++)
        A[k * N + j] = A[k * N + j]/A[k * N + k];

      for(i=k+1; i<=m-1; i++)
        for (j=k+1; j<=m-1; j++)
          A[i * N + j] = A[i * N +j] - A[i * N + k]*A[k * N + j];
    }
) @*/

/*@ end @*/
/*@ end @*/


}



