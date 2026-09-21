# Bonsai HTTP and vision client

This standard-library Python 3 client reproduces the seven synthetic checks
used for the 2026-09-18 Ubuntu comparison: arithmetic, exact text, exact JSON,
three completed text-generation requests, and one image request. It runs on
Linux against an already running Prism `llama-server` on loopback. It does not
start the server, download models, or execute model output.

From the repository root on the Jetson, after starting the pinned server as
shown in [the Bonsai guide](../../docs/bonsai.md):

```sh
python3 benchmarks/bonsai/bonsai_bench.py \
  --base-url http://127.0.0.1:8081 --model bonsai2-27b \
  --suite all --repeats 3 --max-tokens 128 \
  --output-dir /data/bonsai2/results/http-vision-001
```

Use a new private output directory for each run; existing directories are
refused. Requests, responses, streamed events and server properties are written
there. Keep these outputs private. Copy this directory with its adjacent PNG
and JSON manifest if the target does not have a repository checkout.

The client fixes temperature 0, seed 27, thinking off and prompt-prefix caching
off. It validates completion and output format, checks the image hash, and
bounds each request with an absolute deadline. The image is the public synthetic
`JAJ27` card with three red circles. Its manifest preserves the original image
and font provenance; neither Pillow nor the original generator is needed to run
the client.

`ttft_content_s` measures client time to the first visible text. Server prompt
and decode timings are recorded separately. The three repeated text checks
require complete, nonempty output; they do not grade semantic quality. These
checks are distinct from native `llama-bench` rates, model-loading time and
cold-boot measurements. Consult the guide for the pinned server/model versions
and required power settings.

Run the protocol tests on a Linux host without models or a GPU:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s benchmarks/bonsai -p 'test_*.py' -v
```

The tests use a temporary loopback mock server. They cover streamed responses,
usage and timing retention, malformed/truncated streams, absolute deadlines,
strict output validation, image integrity, and the complete seven-request CLI.
Passing them validates the client, not model inference on Yocto.

ARK-authored client, tests and synthetic assets are covered by the repository's
[MIT license](../../LICENSE). The executable workload is unchanged from the
original comparison client; the public copy adds SPDX headers and adjusts its
module description, so its recorded client-file hash differs.
