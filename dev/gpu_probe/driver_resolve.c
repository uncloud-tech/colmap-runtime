/* Resolve the REAL host libcuda.so.1 via dlopen/dlsym/dladdr.
 *
 * Reused from the validated Task0 GPU preflight probe: a wheel-provided
 * libcuda stub must never satisfy the loader and cuInit must succeed on the
 * actual driver. Prints machine-readable lines consumed by photogram-dev. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

int main(void) {
  void *handle = dlopen("libcuda.so.1", RTLD_NOW | RTLD_LOCAL);
  if (!handle) {
    printf("FAILED dlopen libcuda.so.1: %s\n", dlerror());
    return 1;
  }
  void *symbol = dlsym(handle, "cuInit");
  if (!symbol) {
    printf("FAILED dlsym cuInit: %s\n", dlerror());
    return 2;
  }
  Dl_info info;
  if (!dladdr(symbol, &info) || !info.dli_fname) {
    printf("FAILED dladdr\n");
    return 3;
  }
  printf("LIBCUDA_RESOLVED=%s\n", info.dli_fname);
  typedef int (*cu_init_t)(unsigned);
  int rc = ((cu_init_t)symbol)(0);
  printf("cuInit rc=%d\n", rc);
  return rc == 0 ? 0 : 4;
}
