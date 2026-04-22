
/*
 * Affine SpMV - Banded Sparse Matrix-Vector Multiplication
 *
 * Sparse matrix format: Banded (Diagonal) format
 *   - Matrix A is stored as val[M][BW] where:
 *       val[i][j] = A[i][i+j-BW/2]  (the j-th diagonal element of row i)
 *   - Band width = BW = 7 (3 lower diagonals + main diagonal + 3 upper diagonals)
 *   - Matrix size: M x N  (M rows, N=M+BW-1 cols to account for boundary)
 *
 * Computation:
 *   y[i] = sum_{j=0}^{BW-1}  val[i][j] * x[i + j]
 *
 * WHY this is AFFINE:
 *   - Loop bounds: i in [0, M), j in [0, BW)  -> all constant integers
 *   - val[i][j]: affine index (i, j)
 *   - x[i+j]: i+j is a LINEAR COMBINATION of loop iterators
 *   - y[i]: affine index (i only)
 *   -> All accesses are affine functions of {i, j}. PoCC can analyze this.
 *
 * Semantics: Represents a sparse matrix with at most BW non-zeros per row,
 *            located on 3 consecutive lower and upper diagonals plus the main diagonal.
 */

void kernel_nlp(float val[256][7], float x[263], float y[256])
{
  int i;
  int j;

  /* Banded SpMV */
  for (i = 0; i < 256; i++) {
    for (j = 0; j < 7; j++) {
      y[i] = y[i] + val[i][j] * x[i + j];
    }
  }
}
