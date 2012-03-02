void VecDot(int n, double *x, double *y, double r) {

    register int i;

    /*@ begin Loop (
          transform CUDA(threadCount=1024, maxBlocks=65535)
        for (i=0; i<=n-1; i++)
          r=r+x[i]*y[i];
    ) @*/

    for (i=0; i<=n-1; i++)
        r=r+x[i]*y[i];

    /*@ end @*/
}