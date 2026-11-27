#!/usr/bin/env python3
"""Run native tests against the Stage2Virt runtime SBI handler."""
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]

KVM_STUB = r'''
#ifndef KVM_STAGE2_VIRT_RUNTIME_TEST_STUB_H
#define KVM_STAGE2_VIRT_RUNTIME_TEST_STUB_H
#include <stdbool.h>
#include <stdint.h>

typedef uint64_t u64;

struct kvm {
 struct {
  int nrcpus;
  struct { bool stage2_virt_test; } arch;
 } cfg;
};

struct kvm_run {
 struct {
  unsigned long function_id;
  unsigned long args[6];
  unsigned long ret[2];
 } riscv_sbi;
};

struct kvm_cpu {
 struct kvm *kvm;
 struct kvm_run *kvm_run;
 bool stage2_virt_test_active;
 u64 stage2_virt_test_gpa;
 u64 stage2_virt_test_size;
};
#endif
'''

SBI_STUB = r'''
#ifndef KVM_STAGE2_VIRT_RUNTIME_SBI_STUB_H
#define KVM_STAGE2_VIRT_RUNTIME_SBI_STUB_H
#define SBI_SUCCESS 0
#define SBI_ERR_FAILURE -1L
#define SBI_ERR_NOT_SUPPORTED -2L
#define SBI_ERR_INVALID_PARAM -3L
#endif
'''

STAGE2_VIRT_STUB = r'''
#ifndef KVM_STAGE2_VIRT_RUNTIME_API_STUB_H
#define KVM_STAGE2_VIRT_RUNTIME_API_STUB_H
#include "kvm/kvm.h"
int stage2_virt__set_range(struct kvm *kvm, u64 gpa, u64 size);
int stage2_virt__clear_range(struct kvm *kvm, u64 gpa, u64 size);
#endif
'''

UTIL_STUB = r'''
#ifndef KVM_STAGE2_VIRT_RUNTIME_UTIL_STUB_H
#define KVM_STAGE2_VIRT_RUNTIME_UTIL_STUB_H
static inline void test_log(const char *format, ...)
{
 (void)format;
}
#define pr_info test_log
#define pr_warning test_log
#endif
'''

TEST = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "kvm/kvm.h"
#include "kvm/sbi.h"
#include "kvm/stage2-virt.h"

static int set_result;
static int clear_result;
static int set_calls;
static int clear_calls;
static u64 captured_set_gpa;
static u64 captured_set_size;
static u64 captured_clear_gpa;
static u64 captured_clear_size;
static int test_number;

int stage2_virt__set_range(struct kvm *kvm, u64 gpa, u64 size)
{
 assert(kvm != NULL);
 set_calls++;
 captured_set_gpa = gpa;
 captured_set_size = size;
 return set_result;
}

int stage2_virt__clear_range(struct kvm *kvm, u64 gpa, u64 size)
{
 assert(kvm != NULL);
 clear_calls++;
 captured_clear_gpa = gpa;
 captured_clear_size = size;
 return clear_result;
}

#include "HANDLER"

_Static_assert(STAGE2_VIRT_TEST_EXT >= 0x08000000UL &&
               STAGE2_VIRT_TEST_EXT <= 0x08ffffffUL,
               "KVM forwarded SBI range");

static void test_pass(const char *description)
{
 printf("[TEST %02d] %-56s PASS\n", ++test_number, description);
}

static void reset_mocks(void)
{
 set_result = 0;
 clear_result = 0;
 set_calls = 0;
 clear_calls = 0;
 captured_set_gpa = 0;
 captured_set_size = 0;
 captured_clear_gpa = 0;
 captured_clear_size = 0;
}

static void reset_vcpu(struct kvm *kvm, struct kvm_run *run,
                       struct kvm_cpu *vcpu)
{
 memset(kvm, 0, sizeof(*kvm));
 memset(run, 0, sizeof(*run));
 memset(vcpu, 0, sizeof(*vcpu));
 kvm->cfg.nrcpus = 1;
 kvm->cfg.arch.stage2_virt_test = true;
 vcpu->kvm = kvm;
 vcpu->kvm_run = run;
}

static long call(struct kvm_cpu *vcpu, unsigned long function,
                 u64 gpa, u64 size)
{
 struct kvm_run *run = vcpu->kvm_run;

 memset(run->riscv_sbi.args, 0, sizeof(run->riscv_sbi.args));
 run->riscv_sbi.function_id = function;
 run->riscv_sbi.args[0] = gpa;
 run->riscv_sbi.args[1] = size;
 assert(stage2_virt_test__sbi(vcpu));
 return (long)run->riscv_sbi.ret[0];
}

int main(void)
{
 const u64 gpa = 0x90000000ULL;
 const u64 size = 0x1000ULL;
 struct kvm kvm;
 struct kvm_run run;
 struct kvm_cpu vcpu;

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 kvm.cfg.arch.stage2_virt_test = false;
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) ==
        SBI_ERR_NOT_SUPPORTED);
 assert(set_calls == 0 && clear_calls == 0);
 test_pass("disabled runtime extension is rejected");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 kvm.cfg.nrcpus = 2;
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) ==
        SBI_ERR_INVALID_PARAM);
 assert(set_calls == 0);
 test_pass("multi-vCPU runtime test is rejected");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 assert(call(&vcpu, STAGE2_VIRT_TEST_ABORT + 1, 0, 0) ==
        SBI_ERR_NOT_SUPPORTED);
 assert(set_calls == 0 && clear_calls == 0);
 test_pass("unknown runtime function is not supported");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 run.riscv_sbi.function_id = STAGE2_VIRT_TEST_BEGIN;
 run.riscv_sbi.args[0] = gpa;
 run.riscv_sbi.args[1] = size;
 run.riscv_sbi.args[2] = 1;
 assert(stage2_virt_test__sbi(&vcpu));
 assert((long)run.riscv_sbi.ret[0] == SBI_ERR_INVALID_PARAM);
 assert(set_calls == 0);
 test_pass("non-zero reserved SBI argument is rejected");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) == SBI_SUCCESS);
 assert(set_calls == 1 && clear_calls == 0);
 assert(captured_set_gpa == gpa && captured_set_size == size);
 assert(vcpu.stage2_virt_test_active);
 assert(vcpu.stage2_virt_test_gpa == gpa);
 assert(vcpu.stage2_virt_test_size == size);
 test_pass("BEGIN enables and records the runtime range");

 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) ==
        SBI_ERR_INVALID_PARAM);
 assert(set_calls == 1 && vcpu.stage2_virt_test_active);
 test_pass("duplicate BEGIN is rejected");

 assert(call(&vcpu, STAGE2_VIRT_TEST_COMPLETE, gpa + size, size) ==
        SBI_ERR_INVALID_PARAM);
 assert(clear_calls == 0 && vcpu.stage2_virt_test_active);
 test_pass("COMPLETE with mismatched GPA is rejected");

 assert(call(&vcpu, STAGE2_VIRT_TEST_COMPLETE, gpa, size * 2) ==
        SBI_ERR_INVALID_PARAM);
 assert(clear_calls == 0 && vcpu.stage2_virt_test_active);
 test_pass("COMPLETE with mismatched size is rejected");

 assert(call(&vcpu, STAGE2_VIRT_TEST_COMPLETE, gpa, size) == SBI_SUCCESS);
 assert(clear_calls == 1);
 assert(captured_clear_gpa == gpa && captured_clear_size == size);
 assert(!vcpu.stage2_virt_test_active);
 assert(vcpu.stage2_virt_test_gpa == 0 && vcpu.stage2_virt_test_size == 0);
 test_pass("matching COMPLETE disables and resets the session");

 assert(call(&vcpu, STAGE2_VIRT_TEST_COMPLETE, gpa, size) ==
        SBI_ERR_INVALID_PARAM);
 assert(clear_calls == 1);
 test_pass("COMPLETE without active session is rejected");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 set_result = -EINVAL;
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) ==
        SBI_ERR_INVALID_PARAM);
 assert(!vcpu.stage2_virt_test_active);
 test_pass("invalid range error maps to invalid SBI parameter");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 set_result = -EOVERFLOW;
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) ==
        SBI_ERR_INVALID_PARAM);
 assert(!vcpu.stage2_virt_test_active);
 test_pass("range overflow maps to invalid SBI parameter");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 set_result = -EOPNOTSUPP;
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) ==
        SBI_ERR_NOT_SUPPORTED);
 assert(!vcpu.stage2_virt_test_active);
 test_pass("missing host capability maps to SBI not supported");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 set_result = -EIO;
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) == SBI_ERR_FAILURE);
 assert(!vcpu.stage2_virt_test_active);
 test_pass("host enable failure maps to generic SBI failure");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 assert(call(&vcpu, STAGE2_VIRT_TEST_ABORT, gpa, 0) ==
        SBI_ERR_INVALID_PARAM);
 assert(clear_calls == 0);
 test_pass("ABORT with non-zero arguments is rejected");

 assert(call(&vcpu, STAGE2_VIRT_TEST_ABORT, 0, 0) == SBI_SUCCESS);
 assert(clear_calls == 0);
 test_pass("ABORT without active session is idempotent");

 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) == SBI_SUCCESS);
 assert(call(&vcpu, STAGE2_VIRT_TEST_ABORT, 0, 0) == SBI_SUCCESS);
 assert(clear_calls == 1 && !vcpu.stage2_virt_test_active);
 test_pass("ABORT disables and resets an active session");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) == SBI_SUCCESS);
 clear_result = -EIO;
 assert(call(&vcpu, STAGE2_VIRT_TEST_COMPLETE, gpa, size) ==
        SBI_ERR_FAILURE);
 assert(clear_calls == 1 && !vcpu.stage2_virt_test_active);
 test_pass("COMPLETE clear failure still resets local state");

 reset_vcpu(&kvm, &run, &vcpu);
 reset_mocks();
 assert(call(&vcpu, STAGE2_VIRT_TEST_BEGIN, gpa, size) == SBI_SUCCESS);
 stage2_virt_test__cleanup(&vcpu);
 assert(clear_calls == 1 && !vcpu.stage2_virt_test_active);
 test_pass("vCPU cleanup disables an active runtime range");

 stage2_virt_test__cleanup(&vcpu);
 assert(clear_calls == 1);
 test_pass("vCPU cleanup without active session is a no-op");

 assert(test_number == 20);
 printf("[SUMMARY] %d Stage2Virt runtime tests passed\n", test_number);
 return 0;
}
'''


with tempfile.TemporaryDirectory(prefix="kvm-stage2-virt-runtime-test-") as name:
    work = Path(name)
    headers = {
        "kvm/kvm.h": KVM_STUB,
        "kvm/kvm-cpu.h": '#include "kvm/kvm.h"\n',
        "kvm/sbi.h": SBI_STUB,
        "kvm/stage2-virt.h": STAGE2_VIRT_STUB,
        "kvm/util.h": UTIL_STUB,
    }
    for filename, contents in headers.items():
        path = work / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    source = work / "test.c"
    source.write_text(TEST.replace(
        "HANDLER", str(ROOT / "riscv/stage2-virt-test.c")))
    binary = work / "test"
    subprocess.run([
        "cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
        "-I", str(work), "-I", str(ROOT / "riscv/include"),
        str(source), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)

print("Stage2Virt runtime SBI handler mock tests: PASS")
