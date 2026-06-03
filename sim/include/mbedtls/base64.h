#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int mbedtls_base64_decode(uint8_t* dst, size_t dlen, size_t* olen,
                          const uint8_t* src, size_t slen);
int mbedtls_base64_encode(uint8_t* dst, size_t dlen, size_t* olen,
                          const uint8_t* src, size_t slen);
#ifdef __cplusplus
}
#endif
