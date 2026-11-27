/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef KVM__RISCV_STAGE2_VIRT_TEST_H
#define KVM__RISCV_STAGE2_VIRT_TEST_H

#include <stdbool.h>

/* Local experimental SBI extension forwarded by KVM to userspace. */
#define STAGE2_VIRT_TEST_EXT		0x08000058UL
#define STAGE2_VIRT_TEST_BEGIN		0
#define STAGE2_VIRT_TEST_COMPLETE	1
#define STAGE2_VIRT_TEST_ABORT		2

struct kvm_cpu;

bool stage2_virt_test__sbi(struct kvm_cpu *vcpu);
void stage2_virt_test__cleanup(struct kvm_cpu *vcpu);

#endif
