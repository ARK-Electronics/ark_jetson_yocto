# Power command to physical Ethernet carrier

`measure-boot.py --carrier-interface IFACE` observes the host end of a direct
Ethernet cable using read-only `/sys/class/net/IFACE/carrier` polling. Use a
dedicated physical Ethernet adapter whose cable peer has been independently
confirmed to be the JAJ. Keep that host interface administratively UP throughout
the capture. The tool does not configure networking, send network packets for
this observation, or identify the cable peer automatically.

Carrier is distinct from a UART prompt, an IP address, an SSH banner, CUDA or
application readiness. It does not establish completion of unspecified POST
checks. A switch or another connected peer would measure a different link.

## Capture

Select your own UART, supply and host Ethernet interface. Shut the target down
cleanly before using the explicit power-cycle option:

```sh
python3 scripts/measure-boot.py \
  --serial /dev/serial/by-id/YOUR_DEBUG_ADAPTER \
  --rigol /dev/usbtmcN --expected-serial YOUR_SUPPLY_SERIAL --channel 1 \
  --power-cycle --off-seconds 8 --duration 30 \
  --carrier-interface YOUR_ETHERNET_INTERFACE --output-dir carrier-run-1
```

UART is optional for carrier-only collection. Existing SSH/HTTP observations
can be added independently. `--power-on` instead accepts an already OFF supply.
Carrier observation requires one of these instrument-controlled power paths;
an unknown capture-start time cannot establish power-to-link timing.

Before any power change, the tool checks that the named interface is a physical
Ethernet netdev and is administratively UP. Immediately before sending ON, it
verifies supply output OFF and requires an actual carrier-down sample. An old
carrier-up state is rejected. Netdev/device directories are pinned and their
identity, interface index, type and administrative state are checked on every
read. A disappearing, replaced or invalid interface produces a capture error,
even if link was observed earlier. Supply identity/protection checks remain in
force; the tool never clears a protection latch.

Polling continues for the full capture duration. The private timeline contains
the first `carrier_ready` event, every observed `carrier_transition`, and the
last observed state. A later link reset therefore remains visible. A capture
ending with carrier down is not returned as ready. `stable_after_first_up`
means only that no subsequent down sample was observed and the final sample
was up; transitions shorter than the sampling interval can be missed.

## Timing and publication

The shared reference is immediately before the host SCPI output-ON command
write, **not a measured electrical power edge**. Supply-command/output latency
and the board's POR holdoff remain included; no delay is subtracted.

The carrier timestamp is completion of a host sysfs read. The nominal polling
interval is 20 ms, with additional scheduling and read time. Each capture
reports its post-reference sample count, largest completion-to-completion gap
(including the reference-to-first-observation gap), and longest sysfs read
duration. These statistics include the final read after the polling worker
stops; they add no per-poll timeline records. The USB Ethernet
adapter and its driver can delay reporting an actual wire-level link change.
This is an observer measurement, not a guarantee of 20 ms total accuracy or a
precise physical-link edge. Use appropriate electrical/PHY instrumentation if
the acceptance threshold requires tighter certainty.

Keep raw captures private: they include interface/device paths, fixture
identity and other capture configuration. Produce a sanitized report from at
least three complete runs:

```sh
python3 scripts/summarize-boot.py carrier-run-1 carrier-run-2 carrier-run-3 \
  --output carrier-summary.json
```

The report adds the first-carrier aggregate and per-run numeric transitions,
last-up time, final observed state, observed-drop count and actual sampling
statistics. It preserves both
an early link and any later flap; the first-carrier aggregate alone is not a
stable-link metric. Interface names, device paths and fixture identities are
omitted. Existing UART and SSH definitions remain unchanged. See
[validation.md](validation.md) for the other readiness milestones.
