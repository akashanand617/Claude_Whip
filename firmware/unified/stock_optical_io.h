#ifndef WHIP_STOCK_OPTICAL_IO_H
#define WHIP_STOCK_OPTICAL_IO_H
#include <stdint.h>

/* UNATTACHED exact-stock sample-reader I/O binding. Only FE cursor write (one
 * byte) and FF sample read (1..128 bytes) are admitted. Matches the two original
 * reader call ABIs: zero success, UINT32_MAX on any reported bus/mutex failure.
 * No heap, automatic recovery, retry, static state or lifecycle receipt.
 * Caller proves stock identity, valid owned buffer span, serialized acquisition
 * and original job lifetime. Thread mode and initially enabled IRQs required.
 * Each call takes/releases the existing bus mutex; the pair is NOT made atomic.
 * Bus status is not physical completion/timing/epoch or emitter-off evidence.
 */
uint32_t woi_samples_io(uint32_t reg, uint8_t *bytes, uint32_t length);
#endif
