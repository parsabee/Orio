void axpy(int n, double *y, double a, double *x) {
  register int i;

  /*@ begin Loop(transform Unroll(ufactor=5, parallelize=False)

  for (i=0; i<=n-1; i++)
    y[i]+=a*x[i];

  ) @*/

  for (i=0; i<=n-1; i++)
    y[i]+=a*x[i];

  /*@ end @*/
}
