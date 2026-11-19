// SPDX-License-Identifier: GPL-2.0-only
#include <linux/list.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#include "kvm/kvm.h"
#include "kvm/kvm-cpu.h"
#include "kvm/pmp-virt-test.h"
#include "kvm/sbi.h"

#define PV_PAGE_SIZE 4096ULL

void pmp_virt_test__cleanup(struct kvm_cpu *vcpu)
{
	if (vcpu->pv_test_active)
		close(vcpu->pv_test_fd);
	vcpu->pv_test_active = false;
}

/* Reject devices, reserved memory, and pages crossing memory-bank bounds. */
static void *test_page(struct kvm *kvm, u64 gpa)
{
	struct kvm_mem_bank *bank;

	if (gpa & (PV_PAGE_SIZE - 1))
		return NULL;
	list_for_each_entry(bank, &kvm->mem_banks, list) {
		u64 offset;

		if (bank->type != KVM_MEM_TYPE_RAM || gpa < bank->guest_phys_addr)
			continue;
		offset = gpa - bank->guest_phys_addr;
		if (offset <= bank->size && bank->size - offset >= PV_PAGE_SIZE)
			return (char *)bank->host_addr + offset;
	}
	return NULL;
}

bool pmp_virt_test__sbi(struct kvm_cpu *vcpu)
{
	struct kvm_run *run = vcpu->kvm_run;
	struct pv_guest_request request = { 0 };
	unsigned long function = run->riscv_sbi.function_id;
	u64 gpa = run->riscv_sbi.args[0];
	void *hva;
	int fd, error;

	run->riscv_sbi.ret[0] = SBI_ERR_NOT_SUPPORTED;
	run->riscv_sbi.ret[1] = 0;
	if (!vcpu->kvm->cfg.arch.pmp_virt_test)
		return true;
	if (vcpu->kvm->cfg.nrcpus != 1 || sizeof(unsigned long) != 8)
		goto invalid;
	if (function > PMP_VIRT_TEST_ABORT)
		return true;
	/* args[1] reports the fixed instruction result; others are reserved. */
	if (run->riscv_sbi.args[2] || run->riscv_sbi.args[3] ||
	    run->riscv_sbi.args[4] || run->riscv_sbi.args[5])
		goto invalid;
	if (function == PMP_VIRT_TEST_ABORT) {
		if (gpa || run->riscv_sbi.args[1])
			goto invalid;
		pmp_virt_test__cleanup(vcpu);
		run->riscv_sbi.ret[0] = SBI_SUCCESS;
		return true;
	}
	if (run->riscv_sbi.args[1] != 42)
		goto invalid;
	hva = test_page(vcpu->kvm, gpa);
	if (!hva || ((uintptr_t)hva & (PV_PAGE_SIZE - 1)))
		goto invalid;
	if (function == PMP_VIRT_TEST_BEGIN) {
		if (vcpu->pv_test_active)
			goto invalid;
		fd = open("/dev/pvtest", O_RDWR | O_CLOEXEC);
		if (fd < 0) {
			pr_warning("PMP.Virt VS/HS unavailable: /dev/pvtest: %s",
				   strerror(errno));
			return true;
		}
		request.operation = PMP_VIRT_TEST_BEGIN;
		request.address = (uintptr_t)hva;
		if (ioctl(fd, PV_GUEST_PROBE, &request) < 0) {
			error = errno;
			close(fd);
			pr_warning("PMP.Virt VS/HS BEGIN failed: %s", strerror(error));
			if (error != ENOTTY)
				run->riscv_sbi.ret[0] = SBI_ERR_FAILURE;
			return true;
		}
		/* The new host ioctl must check code/PTEs and retain the page pin. */
		if (!request.physical || (request.physical & (PV_PAGE_SIZE - 1)) ||
		    request.cause != 1) {
			close(fd);
			goto failure;
		}
		vcpu->pv_test_fd = fd;
		vcpu->pv_test_gpa = gpa;
		vcpu->pv_test_hva = (uintptr_t)hva;
		vcpu->pv_test_hpa = request.physical;
		vcpu->pv_test_active = true;
		pr_info("PMP.Virt VS/HS BEGIN: GPA=0x%llx HPA=0x%llx cause=1",
			(unsigned long long)gpa, (unsigned long long)request.physical);
	} else {
		if (!vcpu->pv_test_active || gpa != vcpu->pv_test_gpa ||
		    (uintptr_t)hva != vcpu->pv_test_hva)
			goto invalid;
		request.operation = PMP_VIRT_TEST_COMPLETE;
		request.address = vcpu->pv_test_hva;
		request.physical = vcpu->pv_test_hpa;
		error = ioctl(vcpu->pv_test_fd, PV_GUEST_PROBE, &request);
		pmp_virt_test__cleanup(vcpu);
		if (error < 0 || request.physical != vcpu->pv_test_hpa ||
		    request.cause != 1)
			goto failure;
		/* Guest result is reported, not independently observed by lkvm. */
		pr_info("PMP.Virt VS/HS COMPLETE: GPA=0x%llx HPA=0x%llx guest_report=42",
			(unsigned long long)gpa, (unsigned long long)request.physical);
	}
	run->riscv_sbi.ret[0] = SBI_SUCCESS;
	return true;
invalid:
	run->riscv_sbi.ret[0] = SBI_ERR_INVALID_PARAM;
	return true;
failure:
	run->riscv_sbi.ret[0] = SBI_ERR_FAILURE;
	return true;
}
