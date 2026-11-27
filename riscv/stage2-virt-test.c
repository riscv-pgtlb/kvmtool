// SPDX-License-Identifier: GPL-2.0-only
#include <errno.h>
#include <string.h>

#include "kvm/kvm.h"
#include "kvm/kvm-cpu.h"
#include "kvm/sbi.h"
#include "kvm/stage2-virt.h"
#include "kvm/stage2-virt-test.h"
#include "kvm/util.h"

static void stage2_virt_test__reset(struct kvm_cpu *vcpu)
{
	vcpu->stage2_virt_test_active = false;
	vcpu->stage2_virt_test_gpa = 0;
	vcpu->stage2_virt_test_size = 0;
}

static int stage2_virt_test__clear(struct kvm_cpu *vcpu)
{
	int ret;

	if (!vcpu->stage2_virt_test_active)
		return 0;

	ret = stage2_virt__clear_range(vcpu->kvm,
				       vcpu->stage2_virt_test_gpa,
				       vcpu->stage2_virt_test_size);
	stage2_virt_test__reset(vcpu);
	return ret;
}

void stage2_virt_test__cleanup(struct kvm_cpu *vcpu)
{
	int ret = stage2_virt_test__clear(vcpu);
	if (ret)
		pr_warning("Stage2Virt test cleanup failed: %s", strerror(-ret));
}

static long stage2_virt_test__begin(struct kvm_cpu *vcpu, u64 gpa, u64 size)
{
	int ret;

	if (vcpu->stage2_virt_test_active)
		return SBI_ERR_INVALID_PARAM;

	ret = stage2_virt__set_range(vcpu->kvm, gpa, size);
	if (ret == -EINVAL || ret == -EOVERFLOW)
		return SBI_ERR_INVALID_PARAM;
	if (ret == -EOPNOTSUPP)
		return SBI_ERR_NOT_SUPPORTED;
	if (ret)
		return SBI_ERR_FAILURE;

	vcpu->stage2_virt_test_gpa = gpa;
	vcpu->stage2_virt_test_size = size;
	vcpu->stage2_virt_test_active = true;
	pr_info("Stage2Virt test BEGIN: GPA=[0x%llx, 0x%llx)",
		(unsigned long long)gpa,
		(unsigned long long)(gpa + size));
	return SBI_SUCCESS;
}

static long stage2_virt_test__complete(struct kvm_cpu *vcpu,
				       u64 gpa, u64 size)
{
	int ret;

	if (!vcpu->stage2_virt_test_active ||
	    gpa != vcpu->stage2_virt_test_gpa ||
	    size != vcpu->stage2_virt_test_size)
		return SBI_ERR_INVALID_PARAM;

	ret = stage2_virt_test__clear(vcpu);
	if (ret)
		return SBI_ERR_FAILURE;

	pr_info("Stage2Virt test COMPLETE: GPA=[0x%llx, 0x%llx)",
		(unsigned long long)gpa,
		(unsigned long long)(gpa + size));
	return SBI_SUCCESS;
}

bool stage2_virt_test__sbi(struct kvm_cpu *vcpu)
{
	struct kvm_run *run = vcpu->kvm_run;
	unsigned long function = run->riscv_sbi.function_id;
	u64 gpa = run->riscv_sbi.args[0];
	u64 size = run->riscv_sbi.args[1];
	long result;

	run->riscv_sbi.ret[0] = SBI_ERR_NOT_SUPPORTED;
	run->riscv_sbi.ret[1] = 0;
	if (!vcpu->kvm->cfg.arch.stage2_virt_test)
		return true;
	if (vcpu->kvm->cfg.nrcpus != 1 || sizeof(unsigned long) != 8) {
		run->riscv_sbi.ret[0] = SBI_ERR_INVALID_PARAM;
		return true;
	}
	if (function > STAGE2_VIRT_TEST_ABORT)
		return true;
	if (run->riscv_sbi.args[2] || run->riscv_sbi.args[3] ||
	    run->riscv_sbi.args[4] || run->riscv_sbi.args[5]) {
		run->riscv_sbi.ret[0] = SBI_ERR_INVALID_PARAM;
		return true;
	}

	switch (function) {
	case STAGE2_VIRT_TEST_BEGIN:
		result = stage2_virt_test__begin(vcpu, gpa, size);
		break;
	case STAGE2_VIRT_TEST_COMPLETE:
		result = stage2_virt_test__complete(vcpu, gpa, size);
		break;
	case STAGE2_VIRT_TEST_ABORT:
		if (gpa || size) {
			result = SBI_ERR_INVALID_PARAM;
			break;
		}
		result = stage2_virt_test__clear(vcpu) ?
			 SBI_ERR_FAILURE : SBI_SUCCESS;
		break;
	default:
		result = SBI_ERR_NOT_SUPPORTED;
		break;
	}

	run->riscv_sbi.ret[0] = result;
	return true;
}
