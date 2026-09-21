# ARK target benchmark and readiness package

`ark-bench` is a small native benchmark package for Tegra234/Orin (SM87). It uses meta-tegra's CUDA compiler/sysroot class and links the shared CUDA runtime. It does not install the CUDA compiler or full toolkit on the target. Its CPU benchmark links OpenSSL libcrypto. The image must provide working NVIDIA GPU, power, and fan support.

The recipe enables two independent milestone services. Neither changes clock settings, power modes, authentication, networking, or filesystem contents outside `/run/ark-bench`.

| Marker | Exact meaning |
|---|---|
| `ARK_OS_READY uptime_s=...` | `multi-user.target` has been reached and the observer process can run. This does not assert that SSH, a camera, a model, or an application is usable. |
| `ARK_CUDA_READY uptime_s=...` | After successful `nvpmodel.service`, this process has initialized CUDA, run an integer-add kernel, copied its output, and verified all 65,536 results. |

Timestamps come from `/proc/uptime`, whose displayed precision is normally 10 ms. They are Linux uptime, **not power-on time**. Capture the console alongside an external power-reference timestamp to measure full cold boot. `StandardOutput=journal` preserves each marker in the journal, and the helper explicitly writes the same line to `/dev/ttyTCU0` for the JAJ debug UART. This avoids dual-console systems choosing `tty0` for `journal+console`. A systemd drop-in can override `Environment=ARK_READINESS_TTY=/dev/ttyTCU0` for another board; `/dev/null` suppresses the extra console output. Only character devices are written. A missing/unwritable UART is reported in the journal. JSON counterparts and the CUDA result are under `/run/ark-bench`. An unsuccessful CUDA probe produces no CUDA-ready file/marker. A dependency failure or timeout is visible through `systemctl status ark-cuda-ready.service` and the journal. A completed probe error prints `ARK_CUDA_FAILED`.

Both observers use `DefaultDependencies=no`, explicit shutdown ordering, and `After=multi-user.target`. This prevents their `WantedBy=multi-user.target` links from adding the normal opposing target ordering. The CUDA observer also waits for `systemd-modules-load.service` and requires `nvpmodel.service`; it does not bypass NVIDIA power initialization. The startup smoke initializes a GPU context, so subsequent benchmark initialization is a **new process on an already booted GPU**, not first GPU use since power-on.

The JAJ image also requires `ark-grow-rootfs.service` before either readiness observer. First boot after flashing grows the mounted ext4 APP filesystem to the already allocated NVMe partition, and that provisioning time is included in its markers. Exclude that first boot from boot-time comparisons. Confirm `/var/lib/ark-grow-rootfs/completed` and `df -h /` before collecting subsequent cold boots. Growth failure suppresses both ready markers and is retried on the next boot.

## Run benchmarks

```sh
ark-cpu-bench --mib 256 --repeats 3
ark-cuda-bench --smoke
ark-cuda-bench --elements 4194304 --iterations 200 --repeats 3
```

Each executable emits one JSON object and exits nonzero on errors or incorrect computation.

- CPU: SHA-256 over a repeated 1 MiB block containing bytes 0–255 in order. Workloads of 64, 256, and 1,024 MiB have independently generated fixed checksums. It checks the standard `abc` known answer, excludes one full workload warmup from measured samples, and verifies every measured digest. `mib_per_second` is single-thread OpenSSL SHA-256 throughput, potentially using CPU crypto instructions; it is not general CPU or inference performance.
- CUDA: unsigned integer vector addition with deterministic inputs. It reports context/runtime initialization, allocation, input copy, first kernel, first output copy, and five-kernel warmup separately. CUDA event timings cover each repeated launch batch. Every output element is checked after the first kernel and after the measured batches. `logical_effective_gb_per_second` counts two logical input reads plus one output write per element; cache effects mean it is **not measured physical DRAM bandwidth**. It does not represent matrix, Tensor Core, model, or camera throughput.

The default CUDA benchmark uses 48 MiB of device buffers plus 48 MiB of host vectors. The smoke uses much less. Arguments are bounded; the systemd smoke also has a 60-second timeout. No disk benchmark or persistent scratch data is created.

Record the selected `nvpmodel`, actual clocks under load, temperature, background services, image/kernel/toolkit versions, and memory state for comparisons. These programs leave the current policy unchanged. If deliberately testing fixed maximum clocks, choose the power mode first and manage `jetson_clocks` explicitly outside this package; label those results separately.

From a host with an existing verified SSH key connection:

```sh
python3 scripts/bench-target.py --target USER@HOST --output-dir results-new
```

Use `--sudo` only when existing noninteractive sudo access is appropriate. The collector executes fixed queries and the two benchmarks, records raw output plus parsed JSON, and checks that the boot ID remained the same. `host_request_wall_s` includes SSH overhead; use each native result's timing fields for benchmark comparisons. Missing readiness files or policy-query permissions remain visible in the report. A timeout stops further submissions; check for a remaining remote command before repeating it. The collector does not reconfigure SSH or accept unknown host keys.

## Summarize cold-boot captures

After independently capturing at least three comparable runs with `scripts/measure-boot.py`, summarize their directories on the host:

```sh
python3 scripts/summarize-boot.py capture-1 capture-2 capture-3 \
    --terminal-kind login --output cold-boot-summary.json
```

For a shell prompt, select `--terminal-kind shell` and provide an explicit `--terminal-regex`; seeing that prompt does not prove a command was executed. The login mode recognizes a plain hostname/login prompt and can also take a custom expression. The expression itself is excluded from the report.

The report retains each run's observations and each metric's included samples, median, range, missing/excluded counts, and whether at least three valid observations exist. Missing milestones stay null. A timeout may still contain useful partial observations; supply faults and erroneous/interrupted captures are excluded from aggregates. Exit 0 means the selected captures were usable for summarization, not that every milestone was observed or a performance target was met. Exit 1 records an unusable capture in the report; exit 2 indicates an argument/output problem. Existing output files are refused.

Only the explicit host SCPI command-send reference is accepted. Output-switching delay and board POR holdoff remain included; no approximately two-second holdoff is subtracted. UART matches use receive-chunk timestamps, including split markers. Linux uptime printed by the marker remains a separate field. Capture-only sessions with an unknown power edge are not reclassified as cold-power measurements. Repeated visible Linux-start banners invalidate a run; reboots that leave no observable banner cannot be inferred. Original fixture identities, network addresses, directory names, raw UART text, and private configuration are not copied into the sanitized report.

## Verification status

Host tests compile and run the CPU executable, compare all three datasets with Python hashlib, reject invalid workloads, exercise readiness success/failure and stale-file removal, and validate the systemd dependency graph:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s meta-ark/recipes-support/ark-bench -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_summarize_boot.py' -v
```

The CUDA source has compiled and passed real integer-vector computation checks on the existing Ubuntu R39.2.1 JAJ image. The CPU baseline also passed there. The actual Yocto image build and its GPU/runtime qualification remain pending; Ubuntu results do not qualify the Yocto image. The CMake `ARK_ENABLE_CUDA=OFF` switch exists solely for host CPU tests; the target recipe explicitly enables CUDA and emits native SM87 code.
