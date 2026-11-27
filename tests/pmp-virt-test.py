#!/usr/bin/env python3
"""Run native tests against the real SBI handler with mocked host ioctls."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = r'''
#ifndef PV_TEST_STUB_H
#define PV_TEST_STUB_H
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <linux/types.h>
typedef uint64_t u64;
struct kvm_mem_bank { u64 guest_phys_addr, size; void *host_addr; int type;
                      struct kvm_mem_bank *next; };
struct list_head { struct kvm_mem_bank *first; };
#define list_for_each_entry(p, h, member) for (p=(h)->first; p; p=p->next)
#define KVM_MEM_TYPE_RAM 1
struct kvm { struct { int nrcpus; struct { bool pmp_virt_test; } arch; } cfg;
             struct list_head mem_banks; };
struct kvm_run { struct { unsigned long function_id, args[6], ret[2]; } riscv_sbi; };
struct kvm_cpu { struct kvm *kvm; struct kvm_run *kvm_run;
 bool pv_test_active; int pv_test_fd; u64 pv_test_gpa, pv_test_hva, pv_test_hpa; };
#define SBI_SUCCESS 0
#define SBI_ERR_NOT_SUPPORTED -2L
#define SBI_ERR_FAILURE -1L
#define SBI_ERR_INVALID_PARAM -3L
static inline void test_log(const char *fmt, ...) { (void)fmt; }
#define pr_info test_log
#define pr_warning test_log
#endif
'''
TEST = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include "HANDLER"
_Static_assert(PMP_VIRT_TEST_EXT >= 0x08000000UL &&
               PMP_VIRT_TEST_EXT <= 0x08ffffffUL, "KVM forwarded SBI range");
_Static_assert(sizeof(struct pv_guest_request) == 32, "host ioctl ABI");
static int opens, closes, calls, fail_errno, wrong_cause;
static int test_number;
static void test_pass(const char *description) {
 printf("[TEST %02d] %-56s PASS\n", ++test_number, description);
}
int mock_open(const char *path, int flags, ...) {
 (void)path; (void)flags; opens++; return 7;
}
int mock_close(int fd) { assert(fd==7); closes++; return 0; }
int mock_ioctl(int fd, unsigned long cmd, ...) {
 va_list ap; struct pv_guest_request *r;
 assert(fd==7 && cmd==PV_GUEST_PROBE); calls++;
 if (fail_errno) { errno=fail_errno; return -1; }
 va_start(ap,cmd); r=va_arg(ap,struct pv_guest_request *); va_end(ap);
 r->physical=0x123000; r->cause=wrong_cause ? 12 : 1; return 0;
}
static long call(struct kvm_cpu *v, unsigned long op, u64 gpa) {
 v->kvm_run->riscv_sbi.function_id=op;
 v->kvm_run->riscv_sbi.args[0]=gpa;
 v->kvm_run->riscv_sbi.args[1]=42;
 assert(pmp_virt_test__sbi(v)); return (long)v->kvm_run->riscv_sbi.ret[0];
}
int main(void) {
 void *page=aligned_alloc(4096,8192); assert(page);
 struct kvm_mem_bank bank={.guest_phys_addr=0x80000000,.size=4096,
                          .host_addr=page,.type=KVM_MEM_TYPE_RAM};
 struct kvm k={.cfg.nrcpus=1,.mem_banks.first=&bank};
 struct kvm_run r={0}; struct kvm_cpu v={.kvm=&k,.kvm_run=&r};
 assert(call(&v,0,0x80000000)==SBI_ERR_NOT_SUPPORTED && opens==0);
 test_pass("disabled test extension is rejected");
 k.cfg.arch.pmp_virt_test=true;
 assert(call(&v,1,0x80000000)==SBI_ERR_INVALID_PARAM);
 test_pass("COMPLETE without active session is rejected");
 assert(call(&v,0,0x80000001)==SBI_ERR_INVALID_PARAM);
 test_pass("unaligned guest GPA is rejected");
 assert(call(&v,0,0x80001000)==SBI_ERR_INVALID_PARAM);
 test_pass("GPA outside guest RAM is rejected");
 bank.size=4095; assert(call(&v,0,0x80000000)==SBI_ERR_INVALID_PARAM);
 test_pass("incomplete guest RAM page is rejected");
 bank.size=4096; bank.type=2;
 assert(call(&v,0,0x80000000)==SBI_ERR_INVALID_PARAM); bank.type=1;
 test_pass("non-RAM memory bank is rejected");
 k.cfg.nrcpus=2; assert(call(&v,0,0x80000000)==SBI_ERR_INVALID_PARAM);
 test_pass("multi-vCPU test configuration is rejected");
 k.cfg.nrcpus=1; fail_errno=ENOTTY;
 assert(call(&v,0,0x80000000)==SBI_ERR_NOT_SUPPORTED && !v.pv_test_active);
 test_pass("missing host probe ioctl is reported as unsupported");
 fail_errno=0; wrong_cause=1;
 assert(call(&v,0,0x80000000)==SBI_ERR_FAILURE && !v.pv_test_active);
 test_pass("unexpected host fault cause is rejected");
 wrong_cause=0;
 assert(call(&v,0,0x80000000)==0 && v.pv_test_active);
 test_pass("BEGIN opens a same-page probe session");
 assert(call(&v,0,0x80000000)==SBI_ERR_INVALID_PARAM);
 test_pass("duplicate BEGIN is rejected");
 assert(call(&v,1,0x80001000)==SBI_ERR_INVALID_PARAM && v.pv_test_active);
 test_pass("COMPLETE with mismatched GPA is rejected");
 assert(call(&v,1,0x80000000)==0 && !v.pv_test_active);
 test_pass("COMPLETE closes the matching probe session");
 assert(call(&v,1,0x80000000)==SBI_ERR_INVALID_PARAM);
 test_pass("repeated COMPLETE is rejected");
 assert(call(&v,0,0x80000000)==0);
 test_pass("new BEGIN succeeds after completed session");
 fail_errno=EIO;
 assert(call(&v,1,0x80000000)==SBI_ERR_FAILURE && !v.pv_test_active);
 test_pass("COMPLETE ioctl failure cleans up session state");
 fail_errno=0; assert(call(&v,0,0x80000000)==0);
 test_pass("new BEGIN succeeds before ABORT test");
 r.riscv_sbi.args[0]=r.riscv_sbi.args[1]=0;
 r.riscv_sbi.function_id=2; assert(pmp_virt_test__sbi(&v));
 assert(!v.pv_test_active && (long)r.riscv_sbi.ret[0]==0);
 test_pass("ABORT clears an active probe session");
 pmp_virt_test__cleanup(&v); assert(opens==closes && calls>0);
 test_pass("cleanup balances host device open and close calls");
 assert(test_number == 19);
 printf("[SUMMARY] %d PMP.Virt mock tests passed\n", test_number);
 free(page); return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="kvm-pv-test-") as name:
    work = Path(name)
    for header in ("kvm/kvm.h", "kvm/kvm-cpu.h", "kvm/sbi.h", "linux/list.h"):
        path = work / header
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER if header == "kvm/kvm.h" else '#include "kvm/kvm.h"\n')
    source = work / "test.c"
    source.write_text(TEST.replace("HANDLER", str(ROOT / "riscv/pmp-virt-test.c")))
    binary = work / "test"
    subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                    "-Dopen=mock_open", "-Dclose=mock_close", "-Dioctl=mock_ioctl",
                    "-I", str(work), "-I", str(ROOT / "riscv/include"),
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("PMP.Virt SBI handler mock tests: PASS")
