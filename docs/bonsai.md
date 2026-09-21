# Optional Bonsai 2 runtime

The `prism-llama` recipe packages the same PrismML source revision used for the
2026-09-18 Ubuntu benchmark on Just a Jetson / Orin NX 16GB. Yocto compilation,
GPU inference and comparative measurements are pending. The package is optional;
the base image does not start a model server or download model weights.

## Build and provision

Keep the SSH public-key setting in your ignored `local.yml`, then build the
optional benchmark variant:

```bash
./scripts/build.sh build kas/jaj.yml:kas/bonsai.yml:local.yml
```

The variant installs Prism and selects NVIDIA's complete MAXN_SUPER power mode
(mode 0) before the first CUDA context. It assumes the board's Super firmware,
adequate power delivery and active cooling. The base configuration remains
available through `./scripts/build.sh`.

The package installs `llama-bench`, `llama-server`, `llama-cli`, and their shared
libraries. The server provides its
HTTP API; this build disables the embedded browser UI to avoid an unpinned UI
download during compilation. It does not need libcurl: this source revision
deprecates and ignores `LLAMA_CURL`, using bundled cpp-httplib with system OpenSSL.

The runtime is [PrismML-Eng/llama.cpp](https://github.com/PrismML-Eng/llama.cpp/tree/d8f26eec76da6d09bb708bcba51ef64b8cd868a3),
tag `prism-b10683-d8f26ee`, commit
`d8f26eec76da6d09bb708bcba51ef64b8cd868a3`. It builds in Release mode for CUDA
SM87 with CUDA graphs enabled. The pinned upstream CUDA code already uses
`-use_fast_math`, which was also present in the Ubuntu build; the recipe adds no
extra fast-math flags. Cross-compilation uses an explicit
`armv8.2-a+dotprod+fp16` CPU target instead of detecting the build host's CPU.
Compiler and CPU-optimization differences must be recorded when comparing results.

Provision model files separately into a private directory such as
`/data/bonsai2/models`, using a verified device backup or your own download from
the [official model repository](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/tree/6ed5e12bf84b7a63069882c91dd9e9218647d17b).
Keep its Apache-2.0 license and notices with the files. Neither the recipe nor the
public repository includes weights. Use the same model revision as the Ubuntu
comparison: `6ed5e12bf84b7a63069882c91dd9e9218647d17b`.

| File | SHA-256 |
| --- | --- |
| `Ternary-Bonsai-2-27B-PQ2_0.gguf` | `3907dc1658db1f78a9826bf8d5bcb8dc65db0d466388937af57f2294fae62ec1` |
| `Ternary-Bonsai-2-27B-PTQ1_0.gguf` | `53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3` |
| `Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf` | `6807ede61d570bb86ba34b756a0fa109edc33668604de867c6ea6d8f1d631903` |

PQ2_0 is the comparison default. PTQ1_0 packs the same ternary weights more
tightly; benchmark it separately. The Q8_0 projector is required for vision.

## Native benchmark

Record `uname -a`, `/etc/os-release`, `llama-cli --version`,
`llama-cli --list-devices`, `nvpmodel -q --verbose`, and
`jetson_clocks --show` before each run. Verify the CUDA backend is present and
the model load reports 65/65 language-model layers offloaded. Match the recorded
power mode, context and test arguments. Keep dynamic clocks and normal fan control;
the Ubuntu measurements did not lock clocks with `jetson_clocks`.

Stop every model server before running this command so two copies of the model
are not resident in the NX's shared 16 GB RAM:

```bash
BONSAI_MODEL_DIR=/data/bonsai2/models
llama-bench \
  -m "$BONSAI_MODEL_DIR/Ternary-Bonsai-2-27B-PQ2_0.gguf" \
  -ngl 99 -fa on -t 6 -b 512 -ub 128 -p 512 -n 128 -r 3 -o json \
  > bonsai-native.json 2> bonsai-native.log
```

Use a fresh private results directory for each run. Capture `tegrastats` at
one-second intervals over the complete run, including before/after memory and
swap snapshots. These native rates measure separate 512-token prompt-processing
and 128-token generation cases, without HTTP, the vision projector or model load.

## HTTP and vision checks

Start one foreground server:

```bash
BONSAI_MODEL_DIR=/data/bonsai2/models
llama-server \
  --model "$BONSAI_MODEL_DIR/Ternary-Bonsai-2-27B-PQ2_0.gguf" \
  --mmproj "$BONSAI_MODEL_DIR/Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf" \
  --alias bonsai2-27b \
  --n-gpu-layers 99 --flash-attn on --ctx-size 4096 --parallel 1 \
  --batch-size 512 --ubatch-size 128 --threads 6 --threads-batch 6 \
  --jinja --reasoning off --image-max-tokens 1024 \
  --host 127.0.0.1 --port 8081
```

Wait for `/health` to return HTTP 200. From another terminal on the Jetson:

```bash
curl --fail --max-time 10 http://127.0.0.1:8081/health
curl --fail-with-body --max-time 300 \
  http://127.0.0.1:8081/v1/chat/completions \
  -H 'Content-Type: application/json' \
  --data '{"model":"bonsai2-27b","messages":[{"role":"user","content":"What is 17 multiplied by 23? Reply with only the integer."}],"temperature":0,"seed":27,"max_tokens":128,"chat_template_kwargs":{"enable_thinking":false},"stream":false}'
```

The expected answer is `391`. The original comparison workload is now included
as the [repository client and synthetic assets](../benchmarks/bonsai/README.md).
Run it from a repository checkout on the Jetson, or copy `benchmarks/bonsai/`
there with its adjacent PNG and JSON manifest:

```bash
python3 benchmarks/bonsai/bonsai_bench.py \
  --base-url http://127.0.0.1:8081 --model bonsai2-27b \
  --suite all --repeats 3 --max-tokens 128 \
  --output-dir /data/bonsai2/results/http-vision-001
```

Choose a new private results directory for each run. The seven checks are
arithmetic, exact instruction, exact JSON, three completed repeated text
requests, and one synthetic-image request. The client preserves temperature 0,
seed 27, thinking disabled, 128 output tokens, and disabled prompt-prefix reuse.
The vision answer must identify code `JAJ27`, three circles and color `red`.
Keep responses, server properties and model files private. The public client
adds an SPDX header and updates its description, so its file hash differs from
the historical copy; executable workload logic and image bytes are unchanged.

Report client first-visible-output latency separately from server prompt/decode
timings. Model-loading time, Linux boot readiness and complete application
readiness are separate measurements.

## Existing Ubuntu comparison

These are historical observations from the private 2026-09-18 JAJ record:
Ubuntu 24.04, R39.2.1, custom Linux 6.8.12, native CUDA 13.2 and the pinned
runtime/model above. They are **not Yocto results**. Native values are means
over three repetitions; HTTP values are medians over three text requests.

| PQ2_0 measurement | Ubuntu 40 W | Ubuntu MAXN_SUPER | Yocto |
| --- | ---: | ---: | --- |
| Native prompt, 512 tokens (tokens/s) | 117.294748 | 117.611236 | Pending |
| Native generation, 128 tokens (tokens/s) | 7.296625 | 7.288507 | Pending |
| HTTP first visible output (s) | 1.527969 | 1.503 | Pending |
| Server text decode (tokens/s) | 7.215732 | 7.216243 | Pending |
| Functional checks | 7/7 | 7/7 | Pending |

The final Ubuntu MAXN_SUPER run observed 1.173 GHz GPU and 3.199 GHz EMC with
dynamic scaling. These short runs do not establish a difference between power
modes, sustained thermal behavior or application coexistence under load. Record
actual Yocto build/runtime versions and raw evidence before filling the pending
column or claiming an operating-system performance difference.
