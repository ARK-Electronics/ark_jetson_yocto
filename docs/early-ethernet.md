# Early Ethernet link investigation

The requested target is **less than 6 seconds from power applied to an
established physical Ethernet cable link that remains established through Linux
startup**, including the approximately 2-second power-on-reset (POR) holdoff.
Continuous link is required; the power-on self-test (POST) list remains undefined.
**The current profile does not meet the requirement:** all three cold boots
showed initial peer carrier before 6 seconds on the SCPI reference, followed by
an outage during Linux startup. Neither electrical power nor physical link edges
were instrumented, so exact power-edge-to-link timing is also unverified.

The JAJ Ethernet cable connects directly to a PC USB Ethernet adapter
(ASIX AX88179B, USB product `0b95:1790`). One experimental JAJ-origin unicast
frame received by that adapter verified the connection before the timed runs.
The adapter's existing manual host profile, with DHCP and IPv6 disabled, was
unchanged. SSH control used the separate USB gadget. Final target-state
verification reported carrier up at 1000 Mb/s full duplex; speed and duplex were
not sampled at each first-up event.

The [three-run result](results/yocto-r39-ethernet-boot.json) used the same combined
`kas/jaj.yml:kas/bonsai.yml:kas/fastboot.yml:kas/no-camera.yml:local.yml` image and
retained custom minimal R39.2.1 UEFI/QSPI as the
[optimized boot result](results/yocto-r39-fast-boot.json). No firmware or image
changes were made for this Ethernet experiment. All three boots passed CUDA smoke
and native boot verification. No camera or FFC endpoint was attached; Linux C7
remained enabled at Gen2. This does not qualify the generated full UEFI firmware.

All times below are seconds from host **SCPI power-on command send**, including
command/output latency and POR. No POR estimate was subtracted. Each run had a
fresh supply-output-OFF/carrier-down baseline and one observed down/up cycle
after the first up. Carrier remained observed up from the final up through the
approximately 40-second capture end; shorter unsampled flaps cannot be excluded.

| Cold run | First peer up | Later down | Final peer up | Observed outage |
| --- | ---: | ---: | ---: | ---: |
| 1 | 5.711963 | 13.912505 | 16.719196 | 2.806692 |
| 2 | 5.587105 | 13.785726 | 16.345469 | 2.559743 |
| 3 | 5.402599 | 13.866662 | 16.677996 | 2.811334 |

First-up median was **5.587105 s**, range **5.402599–5.711963 s**. Final-up
median was **16.677996 s**, range **16.345469–16.719196 s**. An initial up
followed by an outage does not satisfy continuous-link readiness.

The read-only observer requested 20 ms polling. It recorded 1,965 / 1,966 / 1,964
post-reference samples, including the final read. Maximum completion-to-completion
gaps, including reference-to-first-sample, were **20.819 / 39.961 / 42.978 ms**;
maximum read durations were **0.690 / 0.471 / 0.512 ms**. Exact counts, times and
transitions are in the result JSON. These describe software sampling coverage,
not electrical accuracy: peer PHY/driver reporting, USB delivery and scheduling
add latency. Short down/up cycles between reads may be missed. DHCP, SSH banners,
UART login prompts, CUDA markers and POST completion are separate milestones.

Same-boot UART and Linux diagnostics place initial peer carrier in the firmware
part of startup. UEFI banners arrived at SCPI +2.949–2.962 s, and the completed
L4TLauncher direct-boot messages at +5.594–5.618 s. First carrier at +5.403–5.712 s
therefore does not wait for Linux r8168 initialization. This does not identify
which earlier power/reset/firmware action allowed the PHY to negotiate.

Subtracting the reported Linux uptime from the received OS/CUDA marker gives
approximate host-to-Linux offsets of 7.051–7.091 s across the runs. This is a
diagnostic alignment, not a calibrated conversion: marker execution, UART chunk
receipt and two-decimal uptime rounding contribute uncertainty. With that
alignment, C8's Linux initialization and first PCIe link reports fall near
SCPI +8.17–8.41 s. The peer observer saw no down sample there. The later
+13.786–13.913 s peer drop follows native r8168 interface opening near
+12.65–12.82 s. This timing and the reset paths below make native PHY
initialization a concrete candidate for the outage, not a proven causal trace.

| Same-boot Linux diagnostic, seconds of Linux uptime | Run 1 | Run 2 | Run 3 |
| --- | ---: | ---: | ---: |
| C8 joins IOMMU group | 1.122889 | 1.129788 | 1.101278 |
| First C8 PCIe Gen1 x1 link report | 1.339672 | 1.351864 | 1.319804 |
| r8168 driver loaded | 5.596877 | 5.599851 | 5.469093 |
| r8168 interface-open diagnostic | 5.714946 | 5.761377 | 5.577221 |
| r8168 local Ethernet link-up notification | 9.869099 | 8.909131 | 9.741082 |

The local r8168 up notification is not the peer's first physical-link edge. In
run 2 it precedes the peer's final up observation by about 0.38 s under the
approximate alignment; in runs 1 and 3 it follows it by about 0.15–0.21 s.
Different endpoint status/reporting and clock alignment prevent treating these
as simultaneous measurements or applying a fixed correction.

The observed Ethernet path is the Orin NX module's Realtek PCIe NIC, PCI identity
`10ec:8168`, at `0008:01:00.0`, behind Tegra PCIe **C8** at `140a0000.pcie`.
Linux uses NVIDIA's packaged Realtek `r8168` driver, version `8.053.00-NAPI`.
NVIDIA identifies the NX/Nano module's integrated device as RTL8111HNI; the JAJ
provides the carrier connection to RJ45. This is separate from Tegra's EQOS MAC
and an external MDIO PHY. See NVIDIA's [module PHY identification](https://forums.developer.nvidia.com/t/ethernet-compliance-testing/268689/7)
and [R39.2.1 NX/Nano PCIe topology](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html#configuring-the-pcie-controller).

The built JAJ DTB confirms C8 is `okay`, with PCI domain 8 and `p2u_gbe_2/3`;
the observed endpoint negotiates PCIe Gen1 x1. The SoC EQOS node at
`/bus@0/ethernet@2310000` is `disabled`. A PCIe link-up message describes the
SoC-to-NIC connection, not the Ethernet cable link.

C8 inherits `vpcie3v3-supply` from `VDD_3V3_PCIE`, controlled by AON GPIO AA5.
The imported [MB1 GPIO configuration](../meta-ark/recipes-bsp/ark-jaj-bct/files/tegra234-mb1-bct-gpio-ark-jaj.dtsi)
already drives AA5 high. The [pinmux configuration](../meta-ark/recipes-bsp/ark-jaj-bct/files/tegra234-mb1-bct-pinmux-ark-jaj.dtsi)
assigns AG2/AG3 to the C8 CLKREQ/PERST functions. These software descriptions do
not measure rail rise or reset release, nor establish the NIC's strap/eFuse
configuration. Exact power/reset ownership at the component pins still requires
the module/carrier electrical documentation and measurement.

The following are saved **Linux monotonic diagnostic timestamps**, in seconds.
The optimized trace is the first boot after flashing, including filesystem
growth. The base trace is a separate pre-reflash boot. They are neither three-run
physical-link measurements nor power-edge timestamps.

| Diagnostic event | Base trace | Optimized provisioning trace |
| --- | ---: | ---: |
| C8 PCIe probe begins | 5.836132 | 1.730439 |
| First C8 PCIe Gen1 x1 link report | 6.050866 | 1.947651 |
| Realtek PCI endpoint enumerated | 6.060118 | 1.954830 |
| NVMe APP filesystem mounted | 9.342893 | 4.682913 |
| r8168 driver loaded | 11.240762 | 6.094846 |
| r8168 interface-open diagnostic | 11.492383 | 6.215515 |
| r8168 Ethernet link-up notification | 15.631976 | 9.356962 |

The `eth0: ... IRQ ...` line comes from `rtl8168_open()`, before its hardware
reset, PLL/PHY power-up, PHY configuration and speed/autonegotiation setup. The
link-up notification comes from `rtl8168_check_link_status()` after reading the
NIC's link status. The driver also schedules link-change work with a `1 * HZ`
interval. Interrupts and scheduled work both affect observation timing: the log
is a software observation, not the first electrical link edge, and a fixed
one-second correction would be unjustified. Source: R39.2.1
[`r8168_n.c`](https://gitlab.com/nvidia/nv-tegra/linux-nv-oot/-/blob/e71bacb7c611f880c5f341263967f13de54de3a9/drivers/net/ethernet/realtek/r8168/r8168_n.c),
functions `rtl8168_open`, `rtl8168_phy_power_up`,
`rtl8168_check_link_status` and `rtl8168_schedule_linkchg_work`, plus
[`r8168.h`](https://gitlab.com/nvidia/nv-tegra/linux-nv-oot/-/blob/e71bacb7c611f880c5f341263967f13de54de3a9/drivers/net/ethernet/realtek/r8168/r8168.h).

MB1, MB2, UEFI and the Linux DTB have different responsibilities:

- MB1 runs on BPMP, configures platform pins/pad voltages, memory and security,
  and loads MB2. NVIDIA supplies MB1 as a signed binary with board behavior
  controlled through BCT data. Cold-boot MB2 runs on CCPLEX before UEFI. The
  documented boot flow does not establish an existing Realtek PHY initialization
  path in MB1 or MB2. See [NVIDIA's Orin boot architecture](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/AR/BootArchitecture/JetsonOrinSeriesBootFlow.html).
- The retained custom minimal R39 firmware has PCIe enabled and networking
  disabled. Its recorded build options have no PCIe-controller exclusion; only
  the single-launcher boot-order source fix is recorded. There is no evidence
  that this profile deliberately defers C8 to Linux, but PCIe discovery alone
  does not establish that firmware initializes the Ethernet PHY. The
  [reviewed R39 profile](https://github.com/ARK-Electronics/ark_jetson_kernel/blob/adf6376842a524531438362e7cf48826cb6e7dfe/products/JAJ/fastboot/r39.2.1/jaj_nvme.defconfig)
  retains the native security and persistent-variable components.
- For a device-tree boot, the native UEFI PCIe driver's `OnExitBootServices()`
  invokes controller teardown when ACPI is absent. Its path turns off the PCIe
  link/reference clock and resets/disables the controller; PERST is additionally
  asserted if entry to L2 fails. Linux's `tegra_pcie_dw_start_link()` then asserts
  and releases PERST during its own initialization. These paths can disturb
  endpoint state, but the three captures show no sampled cable drop near C8's
  Linux PCIe initialization; the observed outage occurs later. This does not
  exclude a shorter unsampled disturbance. See the pinned [UEFI PCIe source](https://github.com/NVIDIA/edk2-nvidia/blob/7e9f9ec4de8d979807683a7b4605a15ec3299b89/Silicon/NVIDIA/Drivers/PcieDWControllerDxe/PcieControllerDxe.c)
  and [Linux PCIe source](https://gitlab.com/nvidia/nv-tegra/3rdparty/canonical/linux-noble/-/blob/78272943bba3a47e633b28963b0cda60de503500/drivers/pci/controller/dwc/pcie-tegra194.c).
- R39 Orin uses the 6.8 kernel and separate NVIDIA module/device-tree sources.
  Keep C8's Linux configuration, the UEFI-embedded DTB and early BCT settings
  distinct. An extlinux `FDT` or `OVERLAYS` change affects the kernel handoff;
  it does not update the already executed MB1/MB2 BCT or UEFI's earlier discovery.
  NVIDIA describes the upstream/`nv-platform` DT layers and overlay scope in
  [the R39 porting guide](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html#porting-the-linux-kernel-device-tree).
  OE4T documents the kernel/UEFI migration in its
  [pinned R39 release notes](https://github.com/OE4T/meta-tegra/blob/2e37d1673d25fb92440bcf6db8dcf1076e822037/docs/release-notes/JetPack-7.2-L4T-R39.2.0-Notes.md).
  The newer BCT Platform Configuration Profile mechanism is documented for
  T264 and later, not this T234 Orin module; see [its platform scope](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/SD/Bootloader/PlatformConfigurationProfile.html).

Autonegotiation is performed by the PHY once its power, reset, clock and
configuration permit it. The measured first up establishes pre-Linux peer
carrier on these cold boots, but does not distinguish autonomous PHY behavior
from earlier firmware programming. Wake-on-LAN under standby power would not
establish behavior after full power removal.

The pinned native `r8168` source does not merely adopt an existing link:
`rtl8168_open()` calls hardware reset, PHY power-up and `rtl8168_hw_phy_config()`.
The latter invokes `phy_reset_enable`; `rtl8168_xmii_reset_enable()` clears link
advertisement and requests PHY reset. Opening also calls `rtl8168_set_speed()`;
with the native autonegotiation setting, `rtl8168_set_speed_xmii()` calls
`rtl8168_phy_restart_nway()`, which requests reset and autonegotiation restart.
The three traces contain no ESD-reset or reset-task diagnostic. These normal
initialization paths are enough to justify investigating the handoff without
assuming an error-recovery event.

No skip-PHY-reset or preserve-existing-link module parameter is present in this
pinned driver. EEE, ASPM and shutdown/Wake-on-LAN controls do not bypass the normal
open reset/autonegotiation sequence. Disabling autonegotiation is not a valid
preservation recipe: the native forced-speed branch supports only 10/100 Mb/s,
and earlier PHY initialization still resets it. A preservation change would
need to retain required PHY firmware/calibration and MAC/DMA initialization,
validate the exact chip revision and state, and demonstrate functional traffic
and normal recovery. No such change was implemented or qualified here. Source:
[`r8168_n.c`](https://gitlab.com/nvidia/nv-tegra/linux-nv-oot/-/blob/e71bacb7c611f880c5f341263967f13de54de3a9/drivers/net/ethernet/realtek/r8168/r8168_n.c).

A subsequent **single instrumented cold boot** localized the driver sequence;
its [numeric diagnostic record](results/yocto-r39-ethernet-diagnostic.json) is
separate from the three-run stock-driver result. The
[diagnostic source](../experiments/r8168-phy-diagnostic/) adds opt-in observations
without removing native initialization. The detected chip is `CFG_METHOD_30`:
its C enum value and zero-based chipset-table index both print as `29`.

| Diagnostic event | Linux uptime, s | Observed state |
| --- | ---: | --- |
| Before probe exit from out-of-band mode | 5.175878 | Live MCU version `0x0000`, required `0x0083`, read completed |
| Before PHY configuration | 5.322556 | Local link up; advertisement `0x01e1`, gigabit control `0x0200` |
| Immediately before native PHY reset | 5.322574 | Live MCU version still `0x0000`, read completed |
| After native PHY-reset helper | 5.323666 | Local link down; BMSR `0x7989`, advertisement `0x0001`, gigabit control `0x0000` |
| Native MCU programming path completed | 5.325358 | Cached version `0x0083`, native loaded flag set |
| After speed/autonegotiation setup | 5.361207 | Local link still down; advertisement `0x0de1`, gigabit control `0x0200` |

Local link was up at every sampled probe/open exit-from-out-of-band, MAC-reset
and power-up checkpoint before the native PHY-reset helper. That helper also
clears advertisement; its following snapshot is the first local down observed.
The peer adapter recorded first up at SCPI **+5.607270 s**, down at
**+13.283339 s**, and recovery at **+15.844018 s**, an observed **2.560679 s**
outage. Its 1,967 samples had a maximum completion gap of **37.673 ms** and
maximum read duration of **0.536 ms**. These local and peer observations use
different clocks and reporting paths; they do not assign the entire peer outage
to one instruction or measure a physical link edge.

The pre-reset reads show that the required MCU version was not reported before
this r8168 PHY reset. They do not prove RAM integrity, contents immediately after
POR, or state before UEFI/C8 initialization. The native programming marker
records execution and cached state, not independent verification of every
firmware word. BMSR reads consume latched history; the MCU getter uses indirect
address selection and restores the cached page. The added reads/logging affect
timing, and one boot is insufficient for a new performance claim.

The diagnostic also reports required ADC calibration (`adc_required=1`, offset
`0x5698`) and a changed link advertisement. Early carrier therefore does not
establish that the native required firmware, calibration and negotiated policy
are already complete. **No reset- or firmware-skipping experiment is justified
by these observations.** The next implementation needs a vendor-qualified
link-preserving initialization sequence, or full required PHY initialization
before the accepted first link plus a verified Linux handoff. Native firmware,
ADC/tuning, EEE, MAC/DMA and recovery behavior must remain correct.

A concrete follow-up is available: the retained source tree includes the
[vendor Realtek AArch64 PCIe UNDI driver](https://github.com/tianocore/edk2-non-osi/blob/c07d24e45c87d175ad1dc5d74b2c7feed9356503/Drivers/Realtek/Bus/Pcie/PcieNetworking/RtkUndiDxe.inf),
while the measured minimal UEFI profile disables networking. A controlled UEFI
variant could test whether that driver performs the required PHY initialization
earlier. Its firmware version, calibration, shutdown and Linux-handoff behavior
are unverified; enabling it does not itself establish continuous link or the
six-second target. No firmware change was made for the measurements above.

Separate post-startup stock-driver traffic checks transferred **128 MiB in each
direction** at **936.98 / 941.11 Mb/s**, with both payload SHA-256 checks passing.
The diagnostic driver also passed that transfer check at **937.36 / 941.43 Mb/s**.
These verify functioning traffic after startup, not traffic during handoff or
continuous early link.

The stock driver was subsequently restored and verified on a distinct cold boot:
its original module hash matched, the diagnostic parameter and records were
absent, CUDA smoke and native boot verification passed, MAXN_SUPER mode 0 and the
native fan were active, and no systemd units were failed. The temporary shutdown
hook was removed. The restored link reported 1000 Mb/s full duplex and passed
another 128 MiB transfer each way at **937.51 / 941.01 Mb/s**, with matching
payload checksums. This restoration check does not replace the three-run timing
baseline or resolve its continuous-link failure.

The next work should establish a supported, measurable handoff:

1. Define the POST list. Continuous link through firmware-to-Linux handoff is
   required; retain every observed flap and record speed/duplex qualification.
2. Use the direct peer adapter's read-only carrier capture to measure observed
   link transitions relative to SCPI command send, recording sampling gaps and
   observer limitations. To assess the actual power-applied requirement, also
   capture input power at a defined threshold on the same time reference and
   characterize peer reporting delay, or use a validated link indication/PHY
   signal with electrical capture. An RJ45 LED needs its actual link/activity
   function and polarity confirmed. Keep POR in the elapsed time. The electrical
   power edge remains unmeasured; SCPI plus peer-carrier timestamps alone do not
   establish exact power-edge-to-link timing.
3. Correlate every link transition with MB1, MB2, UEFI, Linux C8 probing and
   `r8168_open()`. Measure rail/reset/clock timing where accessible. This separates
   a power/reset dependency from PHY initialization, autonegotiation and a late
   software observer. Record all down/up transitions through OS handoff.
4. Investigate r8168's normal PHY reset/configuration and autonegotiation path
   before changing MB1/MB2. Capture or instrument the exact reset writes and
   negotiation state in a controlled diagnostic test, then seek a supported
   link-preserving handoff for the identified chip revision. Loading the driver
   earlier alone can move a reset earlier but does not eliminate it. Do not skip
   required PHY firmware/calibration, disable the driver, enable unrelated EQOS,
   or remove authentication/security stages to claim continuous link.
5. Re-measure complete cold cycles against the electrical reference after each
   change. Preserve Linux FFC C7 support, CUDA power policy and native boot/security
   verification. Any attached FFC endpoint needs separate qualification.

The three-run baseline changed no firmware, BCT or driver settings; subsequent
driver instrumentation was temporary and the stock driver was restored. The
cable was rewired for the direct peer observer, retaining the host adapter's
existing profile. The current profile fails the required continuous-link criterion.

A subsequent UEFI variant **failed the target in one instrumented cold boot**.
The [variant source and build inputs](../experiments/uefi-realtek/) enable only
`NETWORKING` and `NETWORKING_DEVICE_REALTEK` relative to the retained minimal
profile. The resolved security, TPM, persistent-variable, PCIe and remaining
configuration symbols are unchanged. The RELEASE image contains the vendor
Realtek PCIe UNDI 2.075 driver; its SHA-256 is recorded in the
[numeric cold diagnostic result](results/yocto-r39-uefi-realtek-diagnostic.json).
Only bootloader slot A was flashed for the experiment. MB1/MB2/BCT were not tuned;
the kernel, root filesystem, diagnostic r8168 module and direct peer observer
matched the earlier single instrumented cold boot. This is a separate temporary
firmware experiment, not a change to the three-run baseline above.

| Variant cold observation | Seconds from SCPI command send |
| --- | ---: |
| First peer carrier up | 9.895970 |
| Later peer carrier down | 18.084330 |
| Peer carrier recovery | 20.908683 |
| Observed outage duration | 2.824353 |

The first up was 4.288700 s later, and final recovery 5.064665 s later, than the
prior single instrumented cold boot. These are single-run differences, not a
repeated performance estimate or identification of the responsible UEFI stage.
The requested 20 ms observer recorded 1,971 samples, a maximum completion gap of
47.258 ms and maximum read duration of 0.452 ms. Carrier was observed up after
recovery through the 40.028354 s final read. Both initial timing and continuity
failed; CUDA smoke and native boot verification nevertheless passed.

The cold driver snapshots again reported live MCU version `0x0000`, required
`0x0083`, with completed reads before probe exit from out-of-band mode at Linux
5.294210 s and immediately before PHY reset at 5.425840 s. Before that reset,
local status `0x93` indicated a 1000 Mb/s full-duplex link, with advertisement
`0x01e1` and gigabit control `0x0200`. After the native reset helper at
5.426940 s, local link was down, advertisement was `0x0001` and gigabit control
was zero. Native MCU version checking returned a mismatch; its programming path
completed at 5.428742 s with cached version `0x0083` and the loaded flag set.
Native final advertisement became `0x0de1`, retaining gigabit control `0x0200`.
The complete numeric snapshots are retained in the result.

A preceding **warm recovery reboot** had reported live MCU `0x0083` and a native
version match. Prior Linux could have left that RAM state in place, so the warm
result is not evidence that UEFI loaded the required firmware. Its early local
status `0xe6` also indicated **10 Mb/s half duplex**, with advertisement `0x0c21`
and no gigabit advertisement, unlike the later native gigabit policy. The
logged `eee=1` is cached requested policy, not proof of active hardware EEE;
pause advertisement bits likewise do not independently qualify negotiated flow
control. The warm observations are separate from the cold timing aggregates.

The cold result establishes that this variant did not deliver a matching
Linux-visible MCU version or continuous link under six seconds. It does **not**
prove that the UEFI driver never initialized the PHY: vendor programming,
SNP shutdown/stop, ExitBootServices and PCIe handoff may leave different later
state. A completed version read is not a RAM-integrity or calibration test.
No reset-, firmware- or calibration-skipping Linux patch was justified or tested.
A future attempt still needs vendor-qualified early initialization and handoff,
including the required firmware, ADC/tuning, advertisement, EEE, MAC/DMA and
normal recovery behavior.

The retained UEFI was subsequently restored to slot A, and the original stock
r8168 module hash was verified after a distinct full power-cycle boot. Diagnostic
parameters/configuration and log records were absent. CUDA smoke and both native
boot services passed, MAXN_SUPER mode 0 and the native fan were active, no systemd
units were failed, and the temporary shutdown hook was removed. The restored
link reported 1000 Mb/s full duplex. Separate post-startup 128 MiB transfers in
each direction passed both payload checksums at **937.27 / 940.86 Mb/s**. This
confirms restored operation after startup; it does not replace the three-run
baseline or resolve its continuous-link failure.

The variant is not accepted for production. SCPI command send remains the time
reference, with output latency and POR included; no physical power or link edge
was measured. POST remains undefined and unverified.
