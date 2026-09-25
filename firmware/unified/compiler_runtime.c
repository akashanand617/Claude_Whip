/* Freestanding ARM EABI primitives shared by the proof and placement links.
 * No ROM, allocator, libc or stock RAM dependencies. Volatile byte accesses
 * prevent the compiler from replacing these implementations with themselves.
 * uidiv's zero-denominator result is defined as zero here; firmware callers
 * must reject zero denominators before use (see ws_profile_valid).
 */
#include <stddef.h>
#include <stdint.h>

void __aeabi_memclr4(void *destination, size_t length) {
    volatile unsigned char *p = destination;
    while (length--) *p++ = 0;
}
void __aeabi_memcpy(void *destination, const void *source, size_t length) {
    volatile unsigned char *d = destination;
    const volatile unsigned char *s = source;
    while (length--) *d++ = *s++;
}
void __aeabi_memcpy4(void *destination, const void *source, size_t length) {
    __aeabi_memcpy(destination, source, length);
}
void __aeabi_memmove4(void *destination, const void *source, size_t length) {
    volatile unsigned char *d = destination;
    const volatile unsigned char *s = source;
    if ((uintptr_t)destination > (uintptr_t)source) {
        while (length) {
            --length;
            d[length] = s[length];
        }
    } else {
        while (length--) *d++ = *s++;
    }
}
uint32_t __aeabi_uidiv(uint32_t numerator, uint32_t denominator) {
    if (denominator == 0u) return 0u;
    uint32_t quotient = 0u, remainder = 0u;
    for (unsigned bit = 32u; bit > 0u; --bit) {
        uint32_t carry = remainder >> 31u;
        remainder = (remainder << 1u) | ((numerator >> (bit - 1u)) & 1u);
        if (carry || remainder >= denominator) {
            remainder -= denominator;
            quotient |= UINT32_C(1) << (bit - 1u);
        }
    }
    return quotient;
}
