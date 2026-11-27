/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef KVM__RISCV_STAGE2_VIRT_H
#define KVM__RISCV_STAGE2_VIRT_H

#include <linux/types.h>

struct kvm;

int stage2_virt__check_capability(struct kvm *kvm);
int stage2_virt__set_range(struct kvm *kvm, u64 gpa, u64 size);
int stage2_virt__clear_range(struct kvm *kvm, u64 gpa, u64 size);
int stage2_virt__configure(struct kvm *kvm);

#endif
