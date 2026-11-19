# Experimental PMP.Virt VS/HS coordination

This implements a default-off userspace coordination endpoint, one part of a cooperative
VS/HS same-page test. Run RV64 lkvm with `--pmp-virt-test -c 1`. No additional
virtual device is needed: RISC-V KVM forwards experimental SBI calls to lkvm.

## Guest protocol

Local experimental extension: `0x08000057` (distinct from the M-mode firmware
seal extension `0x0a000056`). SBI BASE probe function 3 reports this extension
when the lkvm switch is enabled. Availability does not prove host ioctl support.

| Function | Arguments | Meaning |
| --- | --- | --- |
| 0 BEGIN | a0=page-aligned GPA, a1=42, a2..a5=0 | Guest has executed the fixed page once. Resolve one full 4 KiB ordinary RAM page and synchronously request HS probing/pinning. |
| 1 COMPLETE | Same GPA, a1=42, a2..a5=0 | Guest reports a second execution after BEGIN returned successfully. Validate host pin/mapping continuity and release the session. |
| 2 ABORT | a0..a5=0 | Release the session without a successful completion. |

The handler returns SBI error in a0, value zero in a1. Disabled support or an
old host ioctl returns NOT_SUPPORTED. Invalid sequence/arguments return
INVALID_PARAM. A failed host check returns FAILURE. There is only one session
per vCPU; the feature requires one vCPU. BEGIN must return successfully before
the guest executes again and issues COMPLETE. ABORT or VM teardown closes the
host descriptor. Invalid requests do not implicitly replace an existing session.

Guest RAM resolution checks page alignment, RAM type and whole-page bounds.
GPA is not HPA. Guest a1=42 is a report, not an independent observation of VS
execution. This is a cooperative test protocol, not attestation against a
malicious guest. It must not be used as a general arbitrary-memory execution
interface.

## Paired host kernel interface

`riscv/include/kvm/pmp-virt-test.h` specifies proposed ioctl
`PV_GUEST_PROBE = _IOWR('V', 0x57, struct pv_guest_request)` on `/dev/pvtest`.
The four u64 fields are operation, address (host userspace VA), physical (HPA),
and cause. This is separate from the existing HU test ioctl number 0x56, which
rejects writable guest RAM mappings and cannot be reused unchanged.

Host implementation requirements:

- Check privileges, boot probe readiness, single CPU and request validity.
- BEGIN: resolve/pin the supplied page, validate the exact fixed instructions,
  create an HS executable non-user alias, verify the alias PTEs, synchronize
  translations/instructions and perform the controlled HS instruction probe.
- Return success only for the expected instruction access fault (cause 1), with
  the pinned HPA. Keep the reference/pin and session state attached to the file.
- COMPLETE: re-resolve/validate that the supplied VA still maps to the same
  pinned page, revalidate code and required state, return that HPA and cause 1,
  and release the session. Reject a changed frame or stale session.
- File release must clean up an unfinished BEGIN, including error/abort paths.
- Audit synchronization, page pin API and VM backing constraints; do not treat
  mlock, a printed GPA, or a userspace VA as evidence of fixed HPA identity.

The paired host implementation is in Linux arch/riscv/kernel/pv_access.c.
An older host lacks this ioctl and BEGIN returns NOT_SUPPORTED. No overall PASS is emitted by this endpoint. BEGIN and COMPLETE
logs are intermediate evidence only. A complete regression must combine the
trusted probe results, guest before/after results, matching page identity, and
normal test/VM termination.

## Paired guest and remaining integration

The paired guest `pv_guest_test.c` issues BEGIN, repeats the VS call, then
issues COMPLETE (or ABORT on failure). The page remains allocated across all
phases and is freed after completion. SDK launch scripts, version locks and
regression parsers have not yet been integrated.

## Validation

Cross-build lkvm-static using the project's RISC-V toolchain and libfdt.
Run `python3 tests/pmp-virt-test.py` for native tests of the real SBI handler
with mocked open/ioctl/close operations. These tests do not validate KVM exits,
hardware permissions, kernel pin lifetime or actual guest execution.


Only ordinary anonymous RAM is supported by the host prototype; hugetlbfs or
file-backed mappings are rejected. BEGIN and COMPLETE each verify mapping,
payload, executable alias and cause. The retained long-term pin prevents
migration/reuse but does not prevent malicious remapping or modification by
other actors. The experiment assumes a cooperative guest and hypervisor.
