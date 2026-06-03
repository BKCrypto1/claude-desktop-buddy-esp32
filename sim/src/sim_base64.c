// Compact base64 decoder — RFC 4648, accepts standard alphabet, ignores
// whitespace, requires padding. Public-domain. Sufficient for xfer.h
// chunk decoding (the desktop sends standard base64).

#include <mbedtls/base64.h>

static int b64val(unsigned char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+')             return 62;
  if (c == '/')             return 63;
  return -1;
}

int mbedtls_base64_decode(uint8_t* dst, size_t dlen, size_t* olen,
                          const uint8_t* src, size_t slen) {
  size_t out = 0;
  int    quad[4];
  int    qi = 0;
  for (size_t i = 0; i < slen; i++) {
    unsigned char c = src[i];
    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') continue;
    if (c == '=') {
      quad[qi++] = -2;
      if (qi == 4) {
        size_t need = (quad[2] == -2 ? 1 : 2);
        if (dst && out + need > dlen) { *olen = out; return -0x002C; }
        if (dst) {
          dst[out++] = (uint8_t)((quad[0] << 2) | (quad[1] >> 4));
          if (need == 2) dst[out++] = (uint8_t)((quad[1] << 4) | (quad[2] >> 2));
        } else { out += need; }
        qi = 0;
      }
      continue;
    }
    int v = b64val(c);
    if (v < 0) { *olen = out; return -0x002A; }   // invalid char
    quad[qi++] = v;
    if (qi == 4) {
      if (dst && out + 3 > dlen) { *olen = out; return -0x002C; }
      if (dst) {
        dst[out++] = (uint8_t)((quad[0] << 2) | (quad[1] >> 4));
        dst[out++] = (uint8_t)((quad[1] << 4) | (quad[2] >> 2));
        dst[out++] = (uint8_t)((quad[2] << 6) |  quad[3]);
      } else { out += 3; }
      qi = 0;
    }
  }
  *olen = out;
  return (qi == 0) ? 0 : -0x002A;
}

int mbedtls_base64_encode(uint8_t* dst, size_t dlen, size_t* olen,
                          const uint8_t* src, size_t slen) {
  static const char* T =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  size_t need = ((slen + 2) / 3) * 4;
  if (!dst) { *olen = need; return -0x002A; }
  if (need + 1 > dlen) { *olen = need; return -0x002C; }
  size_t i = 0, o = 0;
  while (i + 3 <= slen) {
    uint32_t v = (src[i] << 16) | (src[i+1] << 8) | src[i+2];
    dst[o++] = T[(v >> 18) & 63];
    dst[o++] = T[(v >> 12) & 63];
    dst[o++] = T[(v >>  6) & 63];
    dst[o++] = T[ v        & 63];
    i += 3;
  }
  if (i < slen) {
    uint32_t v = src[i] << 16;
    if (i + 1 < slen) v |= src[i+1] << 8;
    dst[o++] = T[(v >> 18) & 63];
    dst[o++] = T[(v >> 12) & 63];
    dst[o++] = (i + 1 < slen) ? T[(v >> 6) & 63] : '=';
    dst[o++] = '=';
  }
  *olen = o;
  return 0;
}
