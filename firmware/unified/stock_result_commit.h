#ifndef WHIP_STOCK_RESULT_COMMIT_H
#define WHIP_STOCK_RESULT_COMMIT_H
#include "health_adapter.h"

/* Unattached exact-STOCK HR positive-result commit, NOT a complete binding.
 * Replaces only the bounded stores witnessed at file 0xf456..0xf464, never the
 * whole processor, classification, algorithm or optical STOP/resume path.
 *
 * The caller must retain the ORIGINAL HR-producing work ticket and prove
 * measured provenance and metric/job association. Reconstructing a current
 * ticket at dequeue is forbidden. A plausible byte or ready flag is not proof.
 * This primitive does not assign a real inventory mask or reserve stock RAM.
 *
 * Caller must establish exact stock identity, valid initialized adapter/cache
 * memory, and that NMI/HardFault/DMA do not modify this state. Ordinary task and
 * maskable-IRQ writers cannot interleave the check and these four stores.
 * No bus, ROM, RTOS, heap, notification, storage or blocking call is made while
 * PRIMASK is held. Existing PRIMASK is restored, never blindly enabled.
 *
 * Value handling deliberately matches the stock positive signed-value branch:
 * positive int32 is truncated to a byte; auxiliary is copied as a halfword.
 * This is not physiological validation. Other result sinks/owner consumers,
 * untagged events, buffer lifetime and resume still need their own bindings.
 * Do NOT install a closed guard over default Health when inventory is unproved.
 */
bool wrc_commit_hr(const wh_adapter *h, wh_ticket original, bool measured,
                   int32_t value, uint16_t auxiliary);
#endif
