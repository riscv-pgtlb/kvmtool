/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef KVM_PMP_VIRT_TEST_H
#define KVM_PMP_VIRT_TEST_H

#include <stdbool.h>
#include <linux/types.h>
#include <sys/ioctl.h>

/* Local experimental SBI extension, not the firmware seal extension. */
#define PMP_VIRT_TEST_EXT 0x08000057UL
#define PMP_VIRT_TEST_BEGIN 0
#define PMP_VIRT_TEST_COMPLETE 1
#define PMP_VIRT_TEST_ABORT 2

/* Paired experimental host ABI: BEGIN pins until COMPLETE or file release.
 * This is distinct from the existing HU probe ioctl ('V', 0x56).
 */
struct pv_guest_request {
	__u64 operation;
	__u64 address;
	__u64 physical;
	__u64 cause;
};
#define PV_GUEST_PROBE _IOWR('V', 0x57, struct pv_guest_request)

struct kvm_cpu;
bool pmp_virt_test__sbi(struct kvm_cpu *vcpu);
void pmp_virt_test__cleanup(struct kvm_cpu *vcpu);
#endif
