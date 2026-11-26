/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef KVM__RISCV_STAGE2_VIRT_H
#define KVM__RISCV_STAGE2_VIRT_H

struct kvm;

int stage2_virt__configure(struct kvm *kvm);

#endif
