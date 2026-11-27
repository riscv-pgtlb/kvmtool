// SPDX-License-Identifier: GPL-2.0-only
#include <errno.h>
#include <linux/kernel.h>
#include <linux/kvm.h>
#include <linux/list.h>
#include <stdint.h>
#include <sys/ioctl.h>

#include "kvm/kvm.h"
#include "kvm/stage2-virt.h"
#include "kvm/util.h"

static bool stage2_virt__range_is_ram(struct kvm *kvm, u64 start, u64 size)
{
	struct kvm_mem_bank *bank;
	if (!size || start > UINT64_MAX - size)
		return false;
	list_for_each_entry(bank, &kvm->mem_banks, list) {
		u64 offset;
		if ((bank->type & ~KVM_MEM_TYPE_READONLY) != KVM_MEM_TYPE_RAM ||
		    start < bank->guest_phys_addr || size > bank->size)
			continue;
		offset = start - bank->guest_phys_addr;
		if (offset <= bank->size - size)
			return true;
	}
	return false;
}
static int stage2_virt__validate_range(struct kvm *kvm,
				       u64 gpa, u64 size)
{
	if (!size)
		return -EINVAL;
	if ((gpa & (SZ_4K - 1)) || (size & (SZ_4K - 1)))
		return -EINVAL;
	if (gpa > UINT64_MAX - size)
		return -EOVERFLOW;
	if (!stage2_virt__range_is_ram(kvm, gpa, size))
		return -EINVAL;
	return 0;
}

int stage2_virt__check_capability(struct kvm *kvm)
{
	int ret;
	ret = ioctl(kvm->sys_fd, KVM_CHECK_EXTENSION, KVM_CAP_RISCV_STAGE2_VIRT);
	if (ret < 0)
		return -errno;
	if (!ret)
		return -EOPNOTSUPP;
	return 0;
}

int stage2_virt__set_range(struct kvm *kvm, u64 gpa, u64 size)
{
	struct kvm_riscv_stage2_virt request = {
		.guest_phys_addr = gpa,
		.memory_size = size,
		.flags = KVM_RISCV_STAGE2_VIRT_ENABLE,
	};
	int ret;
	ret = stage2_virt__validate_range(kvm, gpa, size);
	if (ret)
		return ret;
	ret = stage2_virt__check_capability(kvm);
	if (ret)
		return ret;
	ret = ioctl(kvm->vm_fd, KVM_RISCV_SET_STAGE2_VIRT, &request);
	if (ret < 0)
		return -errno;
	pr_info("Stage2Virt enabled for GPA [0x%llx, 0x%llx)",
		(unsigned long long)gpa,
		(unsigned long long)(gpa + size));
	return 0;
}

int stage2_virt__clear_range(struct kvm *kvm, u64 gpa, u64 size)
{
	struct kvm_riscv_stage2_virt request = {
		.guest_phys_addr = gpa,
		.memory_size = size,
		.flags = 0,
	};
	int ret;
	ret = stage2_virt__validate_range(kvm, gpa, size);
	if (ret)
		return ret;
	ret = ioctl(kvm->vm_fd, KVM_RISCV_SET_STAGE2_VIRT, &request);
	if (ret < 0)
		return -errno;
	pr_info("Stage2Virt disabled for GPA [0x%llx, 0x%llx)",
		(unsigned long long)gpa,
		(unsigned long long)(gpa + size));
	return 0;
}
// 用于静态启动参数
int stage2_virt__configure(struct kvm *kvm)
{
	if (!kvm->cfg.arch.stage2_virt)
		return 0;
	return stage2_virt__set_range(
		kvm,
		kvm->cfg.arch.stage2_virt_gpa,
		kvm->cfg.arch.stage2_virt_size);
}
