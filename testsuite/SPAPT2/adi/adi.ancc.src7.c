void adi(double* X, double* A, double* B) {
/*@ begin PerfTuning (
    def performance_params {
        param thread_count[]  = [32, 64];
        param block_count[]  = range(14,28,14);
        param inner_loop_unroll_fact[] = range(1, 5);
        param preferred_L1_cache[]  = [16, 48];
        param stream_count[] = [1, 2, 4, 8];
        param CFLAGS[] = ['-O3'];
    }
    def build {
      arg build_command = 'nvcc -arch=sm_75 @CFLAGS';
    }
  def performance_counter
  {
  arg repetitions = 5;
  }

  def search
  {
  arg algorithm = 'Randomlocal';
  arg total_runs = 1000;
  }

  def input_params
  {
  param T[] = [256];
  param N[] = [512]; 
  }
  
  def input_vars {
  decl static double X[N * (N+20)] = random;
  decl static double A[N * (N+20)] = random;
  decl static double B[N * (N+20)] = random;
  }
) @*/   


#define max(x,y)    ((x) > (y)? (x) : (y))
#define min(x,y)    ((x) < (y)? (x) : (y))


int t, n = N;


/*@ begin Loop (
 

for (t=0; t<=T-1; t++)
  {
  
  transform CUDA(threadCount=thread_count,
                 blockCount=block_count,
                 preferL1Size=preferred_L1_cache,
                 unrollInner=inner_loop_unroll_fact,
                 streamCount=stream_count)
  for (i1=0; i1<=n-1; i1++)
    for (i2=1; i2<=n-1; i2++)
    {
     X[i1 * n + i2] = X[i1 * n + i2] - X[i1 * n + (i2-1)] * A[i1 * n + i2] / B[i1 * n + (i2-1)];
     B[i1 * n + i2] = B[i1 * n + i2] - A[i1 * n + i2] * A[i1 * n + i2] / B[i1 * n + (i2-1)];
     }

  transform CUDA(threadCount=thread_count,
                 blockCount=block_count,
                 preferL1Size=preferred_L1_cache,
                 unrollInner=inner_loop_unroll_fact,
                 streamCount=stream_count)
   for (i1=1; i1<=n-1; i1++)
      for (i2=0; i2<=n-1; i2++)
      {
      X[i1 * n + i2] = X[i1 * n + i2] - X[(i1-1)  * n + i2] * A[i1 * n + i2] / B[(i1-1) * n + i2];
      B[i1 * n + i2] = B[i1 * n + i2] - A[i1 * n + i2] * A[i1 * n + i2] / B[(i1-1) * n + i2];
       }
  }


) @*/


/*@ end @*/
/*@ end @*/
}

