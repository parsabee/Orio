
/*@ begin PerfTuning (        
  def build
  {
    arg build_command = 'gcc -O3 -fopenmp ';
    arg libs = '-lm -lrt';
  }
   
  def performance_counter         
  {
    arg repetitions = 10;
  }
  
  def performance_params
  {
    param T1_I[] = [1,16,32,64,128,256,512];
    param T1_J[] = [1,16,32,64,128,256,512];
    param T2_I[] = [1,64,128,256,512,1024,2048];
    param T2_J[] = [1,64,128,256,512,1024,2048];


    param U_I[] = [1]+range(2,17,2);
    param U_J[] = [1]+range(2,17,2);


    constraint tileI = ((T2_I == 1) or (T2_I % T1_I == 0));
    constraint tileJ = ((T2_J == 1) or (T2_J % T1_J == 0));

    constraint reg_capacity = (2*U_I*U_J + 2*U_I + 2*U_J <= 130);
  }

  def search
  {
    arg algorithm = 'Randomlocal';
    arg total_runs = 1000;
  }
  
  def input_params
  {
    let SIZE = 1000;
    param MSIZE = SIZE;
    param NSIZE = SIZE;
    param M = SIZE;
    param N = SIZE;
  }

  def input_vars
  {
    decl static double a[M][N] = random;
    decl static double y_1[N] = random;
    decl static double x1[M] = 0;
  }

            
) @*/

int i, j;
int ii, jj;
int iii, jjj;

#define max(x,y)    ((x) > (y)? (x) : (y))
#define min(x,y)    ((x) < (y)? (x) : (y))



/*@ begin Loop(
  transform Composite(
    tile = [('i',T1_I,'ii'),('j',T1_J,'jj'),(('ii','i'),T2_I,'iii'),(('jj','j'),T2_J,'jjj')],
    unrolljam = (['i','j'],[U_I,U_J])
  )
for (i=0;i<=N-1;i++)
  for (j=0;j<=N-1;j++) 
  { 
    x1[i]=x1[i]+a[i][j]*y_1[j]; 
  } 

) @*/


/*@ end @*/
/*@ end @*/


