/*@ begin PerfTuning (
  def build
  {
    arg build_command = 'gcc -O3 -openmp ';
    arg libs = '-lm -lrt';

  }

  def performance_counter
  {
    arg repetitions = 10;
  }
  
  def performance_params
  {
    # Cache tiling
    
    param T2_I[] = [1,16,32,64,128,256,512];
    param T2_J[] = [1,16,32,64,128,256,512];
    param T2_Ia[] = [1,64,128,256,512,1024,2048];
    param T2_Ja[] = [1,64,128,256,512,1024,2048];

    
    param T3_I[] = [1,16,32,64,128,256,512];
    param T3_J[] = [1,16,32,64,128,256,512];
    param T3_Ia[] = [1,64,128,256,512,1024,2048];
    param T3_Ja[] = [1,64,128,256,512,1024,2048];

    
    param T4_I[] = [1,16,32,64,128,256,512];
    param T4_J[] = [1,16,32,64,128,256,512];
    param T4_Ia[] = [1,64,128,256,512,1024,2048];
    param T4_Ja[] = [1,64,128,256,512,1024,2048];


    # Unroll-jam 
    param U1_I[]  = [1]+range(2,17,2); 
    param U2_I[]  = [1]+range(2,17,2); 
    param U2_J[]  = [1]+range(2,17,2); 
    param U3_I[]  = [1]+range(2,17,2);
    param U3_J[]  = [1]+range(2,17,2);
    param U4_I[]  = [1]+range(2,17,2);
    param U4_J[]  = [1]+range(2,17,2);

    # Scalar replacement

    # Vectorization


    # Parallelization

    # Constraints
    # Constraints
    constraint tileI2 = ((T2_Ia == 1) or (T2_Ia % T2_I == 0));
    constraint tileJ2 = ((T2_Ja == 1) or (T2_Ja % T2_J == 0));
    constraint tileI3 = ((T3_Ia == 1) or (T3_Ia % T3_I == 0));
    constraint tileJ3 = ((T3_Ja == 1) or (T3_Ja % T3_J == 0));
    constraint tileI4 = ((T4_Ia == 1) or (T4_Ia % T4_I == 0));
    constraint tileJ4 = ((T4_Ja == 1) or (T4_Ja % T4_J == 0));

    constraint unroll_limit_2 = (U2_I == 1) or (U2_J == 1);
    constraint unroll_limit_3 = (U3_I == 1) or (U3_J == 1);
    constraint unroll_limit_4 = (U4_I == 1) or (U4_J == 1);

  }
  
  def search
  {
   arg algorithm = 'Randomlocal';
   arg total_runs = 1000;
  }

  def input_params
  {
  let N=500;
  param tmax[] = [100];
  param nx[] = [N];
  param ny[] = [N]; 
  }

  def input_vars
  {
  decl static double ex[nx][ny+1] = random;
  decl static double ey[nx+1][ny] = random;
  decl static double hz[nx][ny] = random;
  }


  def validation {

    arg validation_file = 'validation.c';

  }




) @*/   


int i,j, k,t;
int it, jt, kt;
int ii, jj, kk;
int iii, jjj, kkk;

#define max(x,y)    ((x) > (y)? (x) : (y))
#define min(x,y)    ((x) < (y)? (x) : (y))


/*@ begin Loop (

for(t=0; t<=tmax-1; t++) {

  transform Composite(
    unrolljam = (['j'],[U1_I])
)
  for (j=0; j<=ny-1; j++)
    ey[0][j] = t;

  transform Composite(
      tile = [('i',T2_I,'ii'),('j',T2_J,'jj'),
             (('ii','i'),T2_Ia,'iii'),(('jj','j'),T2_Ja,'jjj')],
      unrolljam = (['i','j'],[U2_I,U2_J])
   )
  for (i=1; i<=nx-1; i++)
    for (j=0; j<=ny-1; j++)
      ey[i][j] = ey[i][j] - 0.5*(hz[i][j]-hz[i-1][j]);


  transform Composite(
      tile = [('i',T3_I,'ii'),('j',T3_J,'jj'),
             (('ii','i'),T3_Ia,'iii'),(('jj','j'),T3_Ja,'jjj')],
      unrolljam = (['i','j'],[U3_I,U3_J])
   )
  for (i=0; i<=nx-1; i++)
    for (j=1; j<=ny-1; j++)
      ex[i][j] = ex[i][j] - 0.5*(hz[i][j]-hz[i][j-1]);


  transform Composite(
      tile = [('i',T4_I,'ii'),('j',T4_J,'jj'),
             (('ii','i'),T4_Ia,'iii'),(('jj','j'),T4_Ja,'jjj')],
      unrolljam = (['i','j'],[U4_I,U4_J])
   )
  for (i=0; i<=nx-1; i++)
    for (j=0; j<=ny-1; j++)
      hz[i][j]=hz[i][j]-0.7*(ex[i][j+1]-ex[i][j]+ey[i+1][j]-ey[i][j]);
}

) @*/
/*@ end @*/

/*@ end @*/
