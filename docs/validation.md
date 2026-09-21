# Bench validation

## Status

The public source and host checks are available. The complete Yocto image is
still being built. **Yocto has not yet been flashed or hardware-qualified.**
The numbers below are the Ubuntu comparison baseline, not Yocto results.

The image graph passes a no-network BitBake dry run (5,426 simulated tasks).
The actual kernel, firmware packaging, CUDA cross-build and target tests are
tracked separately; a dry run does not establish hardware compatibility.

## Ubuntu baseline — 2026-09-21

ARK Just a Jetson with Orin NX 16GB, Ubuntu 24.04, L4T R39.2.1,
Linux 6.8.12-1021-tegra, and the existing fast-boot firmware/rootfs from
[ark_jetson_kernel PR 109](https://github.com/ARK-Electronics/ark_jetson_kernel/pull/109).
The ARK-OS stack remains installed. Only the boot-measurement marker services
were added temporarily; they were removed after measurement.

| Cold-boot milestone | Median | Observed range (3 boots) |
|---|---:|---:|
| Linux multi-user target marker | 13.597 s | 13.363–13.676 s |
| First verified CUDA integer computation | 13.847 s | 13.618–13.932 s |
| UART login prompt displayed | 13.927 s | 13.674–14.001 s |
| USB-network SSH identification banner | 11.982 s | 11.634–14.783 s |

These are host monotonic times from sending the supply's output-on command.
They include the board's roughly two-second POR circuit delay. The electrical
power edge was not measured. UART times include serial transmission/host read
latency; Linux uptime values are retained separately in the JSON.

A login prompt does not measure successful authentication. An SSH banner does
not establish that an application is ready. The CUDA milestone requires an
actual GPU kernel plus full output verification; it is independent of ARK-OS
API readiness and is not a model-loading or inference benchmark.

The first instrument trial routed markers to the display console and is not
included. Another trial lost the supply's USB connection before power-on and
is also excluded. The third accepted sample powered on after that connection
was re-established, so its power-off interval was longer than the first two
(minimum eight seconds). All accepted runs include a complete power removal
and a successful CUDA result. No camera is connected.

[Sanitized boot samples](results/ubuntu-r39-baseline-boot.json) preserve each
accepted observation and aggregation rules. Device identities and raw UART
logs are excluded.

## Ubuntu performance baseline

Both tests used native MAXN_SUPER mode 0 with `jetson_clocks`. The same C++/CUDA
sources are packaged by the Yocto `ark-bench` recipe. Ubuntu compilation used
GCC 13.3.0, nvcc 13.2.86, Release optimization and SM87.

| Test | Result | Scope |
|---|---:|---|
| SHA-256 | 1,204.6–1,205.0 MiB/s | One CPU thread; 256 MiB per timed sample; OpenSSL 3.0.13 |
| CUDA vector add | 95.61–95.65 GB/s | Logical effective bandwidth; 4,194,304 uint32 elements; 200 launches/sample |
| CUDA smoke | Pass | All 65,536 output elements verified |

Each throughput test records three timing samples in one process after warmup.
Vector-add bandwidth counts two reads and one write; it is neither inference
throughput nor a measurement of physical DRAM bus traffic. Initialization,
allocation, copies and first-kernel timing are reported separately.

[Numeric performance samples](results/ubuntu-r39-baseline-performance.json)
include CUDA/runtime versions and correctness checks. The Yocto compiler and
OpenSSL version differ, so comparisons will identify those differences rather
than attribute every change solely to the operating system.

Historical Bonsai model measurements and the exact matching commands are in
[bonsai.md](bonsai.md). Fresh Yocto measurements remain pending.

## Repeating the measurements

Use `scripts/measure-boot.py --help` for explicit UART and power-supply selection.
Halt/shut down the target cleanly before cutting power, and verify storage is
read-only. The tool preserves supply voltage/current/protection settings and
checks the selected instrument's identity. Its raw output must remain private.

Aggregate three new run directories with:

```sh
python3 scripts/summarize-boot.py run-1 run-2 run-3 \
  --terminal-kind login --output boot-summary.json
```

The summarizer excludes instrument failures, distinguishes host and target
clocks, and leaves missing milestones empty. Use `scripts/bench-target.py`
with an explicitly trusted SSH host key to collect CPU/CUDA results from a
running image. See the [benchmark package](../meta-ark/recipes-support/ark-bench/README.md)
for exact workload definitions.
