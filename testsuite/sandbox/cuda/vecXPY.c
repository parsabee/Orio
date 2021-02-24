typedef struct {
    double *data;
} MX;

void VecXPY(int n, MX *X, MX *Y) {
  double *x = X->data;
  double *y = Y->data;
  register int i;
  /*@ begin PerfTuning(
        def performance_params {
          param TC[] = [32, 64];
          param BC[] = range(14,29,14);
          param SC[] = range(1,3);
          param CB[] = [True, False];
          param PL[] = [16];
          param CFLAGS[] = [''];
        }
        def build {
          arg build_command = 'nvcc -arch=sm_75 @CFLAGS';
        }
        def input_params {
          param N[] = [1000];
        }
        def input_vars {
          decl dynamic double y[N] = random;
          decl dynamic double x[N] = random;
        }
        def performance_counter {
          arg method = 'basic timer';
          arg repetitions = 1;
        }
  ) @*/

  int n=N;

  /*@ begin Loop(transform CUDA(threadCount=TC, blockCount=BC, streamCount=SC, cacheBlocks=CB, preferL1Size=PL)

  for (i=0; i<=n-1; i++)
    y[i]+=x[i];

  ) @*/

  for (i=0; i<=n-1; i++)
    y[i]+=x[i];

  /*@ end @*/
  /*@ end @*/
}
