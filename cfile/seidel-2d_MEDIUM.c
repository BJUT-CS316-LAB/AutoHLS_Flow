


void kernel_seidel_2d(int tsteps,int n,float A[400][400])
{
  int t;
  int i;
  int j;
    
  for (t = 0; t <= 99; t++) {
 
    for (i = 1; i <= 398; i++) {
      
      for (j = 1; j <= 398; j++) {
        A[i][j] = (A[i - 1][j - 1] + A[i - 1][j] + A[i - 1][j + 1] + A[i][j - 1] + A[i][j] + A[i][j + 1] + A[i + 1][j - 1] + A[i + 1][j] + A[i + 1][j + 1]) / 9.0;
      }
    }
  }
}
