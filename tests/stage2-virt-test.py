#!/usr/bin/env python3
"""Run native tests against the Stage2Virt configuration with mocked ioctls."""
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]

KVM_STUB = r'''
#ifndef KVM_TEST_STUB_H
#define KVM_TEST_STUB_H
#include <stdbool.h>
#include <stdint.h>

typedef uint64_t u64;

#define KVM_MEM_TYPE_RAM       (1 << 0)
#define KVM_MEM_TYPE_DEVICE    (1 << 1)
#define KVM_MEM_TYPE_RESERVED  (1 << 2)
#define KVM_MEM_TYPE_READONLY  (1 << 3)

struct kvm_mem_bank {
 struct kvm_mem_bank *next;
 u64 guest_phys_addr;
 u64 size;
 int type;
};

struct list_head { struct kvm_mem_bank *first; };

struct kvm {
 struct {
  struct {
   bool stage2_virt;
   u64 stage2_virt_gpa;
   u64 stage2_virt_size;
  } arch;
 } cfg;
 int sys_fd;
 int vm_fd;
 struct list_head mem_banks;
};
#endif
'''

KERNEL_STUB = r'''
#ifndef LINUX_KERNEL_TEST_STUB_H
#define LINUX_KERNEL_TEST_STUB_H
#include <stdint.h>
#define U64_MAX UINT64_MAX
#define SZ_4K 0x00001000UL
#endif
'''

KVM_UAPI_STUB = r'''
#ifndef LINUX_KVM_TEST_STUB_H
#define LINUX_KVM_TEST_STUB_H
#include <stdint.h>

#define KVM_CHECK_EXTENSION 0x100
#define KVM_CAP_RISCV_STAGE2_VIRT 247
#define KVM_RISCV_SET_STAGE2_VIRT 0x200
#define KVM_RISCV_STAGE2_VIRT_ENABLE (1ULL << 0)

struct kvm_riscv_stage2_virt {
 uint64_t guest_phys_addr;
 uint64_t memory_size;
 uint64_t flags;
 uint64_t reserved[5];
};
#endif
'''

LIST_STUB = r'''
#ifndef LINUX_LIST_TEST_STUB_H
#define LINUX_LIST_TEST_STUB_H
#define list_for_each_entry(pos, head, member) \
 for ((pos) = (head)->first; (pos); (pos) = (pos)->next)
#endif
'''

UTIL_STUB = r'''
#ifndef KVM_UTIL_TEST_STUB_H
#define KVM_UTIL_TEST_STUB_H
static inline void test_log(const char *format, ...)
{
 (void)format;
}
#define pr_info test_log
#endif
'''

TEST = r'''
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <linux/kvm.h>

static int capability_result = 1;
static int capability_errno;
static int configure_errno;
static int capability_calls;
static int configure_calls;
static int test_number;
static struct kvm_riscv_stage2_virt captured_request;

static void test_pass(const char *description)
{
 printf("[TEST %02d] %-56s PASS\n", ++test_number, description);
}

int mock_ioctl(int fd, unsigned long command, ...)
{
 va_list arguments;

 if (command == KVM_CHECK_EXTENSION) {
  assert(fd == 10);
  capability_calls++;
  if (capability_errno) {
   errno = capability_errno;
   return -1;
  }
  return capability_result;
 }

 if (command == KVM_RISCV_SET_STAGE2_VIRT) {
  struct kvm_riscv_stage2_virt *request;

  assert(fd == 11);
  configure_calls++;
  va_start(arguments, command);
  request = va_arg(arguments, struct kvm_riscv_stage2_virt *);
  va_end(arguments);
  captured_request = *request;
  if (configure_errno) {
   errno = configure_errno;
   return -1;
  }
  return 0;
 }

 assert(!"unexpected ioctl command");
 return -1;
}

#include "HANDLER"

_Static_assert(KVM_CAP_RISCV_STAGE2_VIRT == 247, "capability ABI");
_Static_assert(sizeof(struct kvm_riscv_stage2_virt) == 64,
               "Stage2Virt request ABI");

static void reset_ioctls(void)
{
 capability_result = 1;
 capability_errno = 0;
 configure_errno = 0;
 capability_calls = 0;
 configure_calls = 0;
 memset(&captured_request, 0xa5, sizeof(captured_request));
}

static void set_valid_config(struct kvm *kvm, struct kvm_mem_bank *bank)
{
 memset(kvm, 0, sizeof(*kvm));
 memset(bank, 0, sizeof(*bank));
 bank->guest_phys_addr = 0x80000000ULL;
 bank->size = 0x20000000ULL;
 bank->type = KVM_MEM_TYPE_RAM;
 kvm->cfg.arch.stage2_virt = true;
 kvm->cfg.arch.stage2_virt_gpa = 0x90000000ULL;
 kvm->cfg.arch.stage2_virt_size = 0x1000ULL;
 kvm->sys_fd = 10;
 kvm->vm_fd = 11;
 kvm->mem_banks.first = bank;
}

int main(void)
{
 struct kvm_mem_bank bank;
 struct kvm kvm;
 int index;

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__check_capability(&kvm) == 0);
 assert(capability_calls == 1 && configure_calls == 0);
 test_pass("capability query succeeds");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 capability_errno = EIO;
 assert(stage2_virt__check_capability(&kvm) == -EIO);
 assert(capability_calls == 1 && configure_calls == 0);
 test_pass("capability ioctl error is propagated");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 capability_result = 0;
 assert(stage2_virt__check_capability(&kvm) == -EOPNOTSUPP);
 assert(capability_calls == 1 && configure_calls == 0);
 test_pass("unsupported capability is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__set_range(&kvm, 0x90000000ULL, 0x1000ULL) == 0);
 assert(capability_calls == 1 && configure_calls == 1);
 assert(captured_request.guest_phys_addr == 0x90000000ULL);
 assert(captured_request.memory_size == 0x1000ULL);
 assert(captured_request.flags == KVM_RISCV_STAGE2_VIRT_ENABLE);
 for (index = 0; index < 5; index++)
  assert(captured_request.reserved[index] == 0);
 test_pass("dynamic range enable builds the expected request");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__clear_range(&kvm, 0x90000000ULL, 0x1000ULL) == 0);
 assert(capability_calls == 0 && configure_calls == 1);
 assert(captured_request.guest_phys_addr == 0x90000000ULL);
 assert(captured_request.memory_size == 0x1000ULL);
 assert(captured_request.flags == 0);
 for (index = 0; index < 5; index++)
  assert(captured_request.reserved[index] == 0);
 test_pass("dynamic range disable clears the enable flag");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__set_range(&kvm, 0x90000001ULL, 0x1000ULL) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("unaligned GPA is rejected before ioctl");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__set_range(&kvm, 0x90000000ULL, 0x1001ULL) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("unaligned range size is rejected before ioctl");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__set_range(&kvm, 0x90000000ULL, 0) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("zero-sized range is rejected before ioctl");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__set_range(&kvm, UINT64_MAX - 0xfffULL,
                               0x2000ULL) == -EOVERFLOW);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("overflowing dynamic range is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__set_range(&kvm, 0xa0000000ULL, 0x1000ULL) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("dynamic range outside guest RAM is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 configure_errno = ENOTTY;
 assert(stage2_virt__clear_range(&kvm, 0x90000000ULL, 0x1000ULL) == -ENOTTY);
 assert(capability_calls == 0 && configure_calls == 1);
 assert(captured_request.flags == 0);
 test_pass("disable ioctl error is propagated");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 kvm.cfg.arch.stage2_virt = false;
 assert(stage2_virt__configure(&kvm) == 0);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("disabled static configuration is a no-op");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 assert(stage2_virt__configure(&kvm) == 0);
 assert(capability_calls == 1 && configure_calls == 1);
 assert(captured_request.guest_phys_addr == 0x90000000ULL);
 assert(captured_request.memory_size == 0x1000ULL);
 assert(captured_request.flags == KVM_RISCV_STAGE2_VIRT_ENABLE);
 for (index = 0; index < 5; index++)
  assert(captured_request.reserved[index] == 0);
 test_pass("static configuration enables the requested range");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 bank.type = KVM_MEM_TYPE_DEVICE;
 assert(stage2_virt__configure(&kvm) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("device memory range is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 bank.type = KVM_MEM_TYPE_RAM | KVM_MEM_TYPE_READONLY;
 assert(stage2_virt__configure(&kvm) == 0);
 assert(capability_calls == 1 && configure_calls == 1);
 test_pass("read-only RAM bank is accepted");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 kvm.cfg.arch.stage2_virt_gpa = 0xa0000000ULL;
 assert(stage2_virt__configure(&kvm) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("range starting past guest RAM is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 kvm.cfg.arch.stage2_virt_gpa = 0x9ffff000ULL;
 kvm.cfg.arch.stage2_virt_size = 0x2000ULL;
 assert(stage2_virt__configure(&kvm) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("range crossing guest RAM end is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 kvm.cfg.arch.stage2_virt_size = 0;
 assert(stage2_virt__configure(&kvm) == -EINVAL);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("zero-sized static range is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 kvm.cfg.arch.stage2_virt_gpa = UINT64_MAX - 0xfffULL;
 kvm.cfg.arch.stage2_virt_size = 0x2000ULL;
 assert(stage2_virt__configure(&kvm) == -EOVERFLOW);
 assert(capability_calls == 0 && configure_calls == 0);
 test_pass("overflowing static range is rejected");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 capability_errno = EIO;
 assert(stage2_virt__configure(&kvm) == -EIO);
 assert(capability_calls == 1 && configure_calls == 0);
 test_pass("static capability ioctl error is propagated");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 capability_result = 0;
 assert(stage2_virt__configure(&kvm) == -EOPNOTSUPP);
 assert(capability_calls == 1 && configure_calls == 0);
 test_pass("static configuration requires host capability");

 set_valid_config(&kvm, &bank);
 reset_ioctls();
 configure_errno = ENOTTY;
 assert(stage2_virt__configure(&kvm) == -ENOTTY);
 assert(capability_calls == 1 && configure_calls == 1);
 test_pass("static configuration ioctl error is propagated");

 assert(test_number == 22);
 printf("[SUMMARY] %d Stage2Virt mock tests passed\n", test_number);

 return 0;
}
'''


with tempfile.TemporaryDirectory(prefix="kvm-stage2-virt-test-") as name:
    work = Path(name)
    headers = {
        "kvm/kvm.h": KVM_STUB,
        "kvm/util.h": UTIL_STUB,
        "linux/kernel.h": KERNEL_STUB,
        "linux/kvm.h": KVM_UAPI_STUB,
        "linux/list.h": LIST_STUB,
    }
    for filename, contents in headers.items():
        path = work / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    source = work / "test.c"
    source.write_text(TEST.replace("HANDLER", str(ROOT / "riscv/stage2-virt.c")))
    binary = work / "test"
    subprocess.run([
        "cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
        "-Dioctl=mock_ioctl", "-I", str(work),
        "-I", str(ROOT / "riscv/include"), str(source), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)

print("Stage2Virt configuration mock tests: PASS")
