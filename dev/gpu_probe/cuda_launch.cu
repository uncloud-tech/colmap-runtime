/* Bounded sm_86 kernel check with exact, distinct result validation.
 *
 * Reused from the validated Task0 GPU preflight probe: 1024 elements, each
 * expected to be exactly 2*i+1 so all 1024 results are unique. A silent
 * no-op / wrong-device launch cannot pass. Prints machine-readable lines
 * consumed by photogram-dev gpu-smoke. */
#include <cuda_runtime.h>
#include <stdio.h>

#define N 1024

__global__ void scale(float *a, int n) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) a[i] = a[i] * 2.0f + 1.0f;
}

#define CK(call)                                                       \
  do {                                                                 \
    cudaError_t e_ = (call);                                           \
    if (e_ != cudaSuccess) {                                           \
      printf("FAIL %s: %s\n", #call, cudaGetErrorString(e_));          \
      return 1;                                                        \
    }                                                                  \
  } while (0)

int main(void) {
  float host[N];
  for (int i = 0; i < N; ++i) host[i] = (float)i;
  float *device = NULL;
  CK(cudaMalloc((void **)&device, N * sizeof(float)));
  CK(cudaMemcpy(device, host, N * sizeof(float), cudaMemcpyHostToDevice));
  scale<<<4, 256>>>(device, N);
  CK(cudaGetLastError());
  CK(cudaDeviceSynchronize());
  float out[N];
  CK(cudaMemcpy(out, device, N * sizeof(float), cudaMemcpyDeviceToHost));
  int bad = 0;
  int seen[N] = {0};
  int unique = 0;
  for (int i = 0; i < N; ++i) {
    float want = 2.0f * (float)i + 1.0f;
    if (out[i] != want) {
      if (bad < 3) printf("MISMATCH i=%d got=%f want=%f\n", i, out[i], want);
      ++bad;
    } else {
      int key = (int)out[i];
      if (key >= 0 && key < N && !seen[key]) {
        seen[key] = 1;
        ++unique;
      }
    }
  }
  CK(cudaFree(device));
  if (bad || unique != N) {
    printf("FAIL: %d of %d values wrong, %d unique\n", bad, N, unique);
    return 2;
  }
  printf("RESULT: 1024 unique values exactly 2*i+1\n");
  return 0;
}
