void MatMatMult(double* A, double* B, double* C, int m, int n, int p) {

/*@ begin PerfTuning (
    def performance_params {
        param TC[]  = range(32,65,32);
        param BC[]  = range(14,28,14);
        param UIF[] = range(1, 5);
        param PL[]  = [16, 48];
        param SC[] = [1, 2, 4, 8];
        param CFLAGS[] = ['-O3'];
    }

    def input_params
    {
        param CONT = 500;
        param NCONT = 500;
        param M = 500;
        param N = 500;
        param K = 500;
    }

    def input_vars
    {
        decl static double A[M][K] = random;
        decl static double B[K][N] = random;
        decl static double C[M][N] = 0;
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

int m = M, p = K, n = N;

#define max(x,y)    ((x) > (y)? (x) : (y))
#define min(x,y)    ((x) < (y)? (x) : (y))

/*@ begin Loop(
  transform CUDA(threadCount=TC, blockCount=BC, preferL1Size=PL, unrollInner=UIF)
  for(i=0; i<=m-1; i++)
    for(j=0; j<=n-1; j++) {
      for(k=0; k<=p-1; k++){
        C[i*n+j] += A[i*p+k]*B[k*n+j];
      }
    }
) @*/

/*@ end @*/
/*@ end @*/


}



