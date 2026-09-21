// SPDX-License-Identifier: MIT
// Real GPU integer computation; whole-vector checks before and after warm timing.
#include "bench-common.h"
#include <cuda_runtime.h>
#include <iostream>
#include <vector>

static void check(cudaError_t status, const char *operation) {
    if (status != cudaSuccess)
        throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(status));
}
struct DeviceMemory {
    uint32_t *a = nullptr, *b = nullptr, *c = nullptr;
    ~DeviceMemory() { cudaFree(c); cudaFree(b); cudaFree(a); }
};
struct Events {
    cudaEvent_t start = nullptr, end = nullptr;
    ~Events() { if (end) cudaEventDestroy(end); if (start) cudaEventDestroy(start); }
};
__global__ void add_vectors(const uint32_t *a, const uint32_t *b, uint32_t *c, size_t count) {
    size_t i = size_t(blockIdx.x) * blockDim.x + threadIdx.x;
    if (i < count) c[i] = a[i] + b[i];
}
static void verify(const std::vector<uint32_t> &a, const std::vector<uint32_t> &b,
                   const std::vector<uint32_t> &actual) {
    for (size_t i = 0; i < actual.size(); ++i)
        if (actual[i] != a[i] + b[i])
            throw std::runtime_error("GPU result mismatch at element " + std::to_string(i));
}

int main(int argc, char **argv) {
    auto start = BenchClock::now();
    try {
        bool smoke = argc == 2 && std::string(argv[1]) == "--smoke";
        unsigned count = smoke ? 65536 : 4194304, iterations = 200, repeats = 3;
        if (!smoke) for (int i = 1; i < argc; ++i) {
            std::string option(argv[i]);
            if (option == "--help") {
                std::cout << "ark-cuda-bench --smoke | [--elements 1..16777216] [--iterations 1..10000] [--repeats 1..10]\n";
                return 0;
            }
            if (i + 1 == argc) throw std::invalid_argument("Incomplete option");
            if (option == "--elements") count = bounded_uint(argv[++i], 1, 16777216);
            else if (option == "--iterations") iterations = bounded_uint(argv[++i], 1, 10000);
            else if (option == "--repeats") repeats = bounded_uint(argv[++i], 1, 10);
            else throw std::invalid_argument("Unknown option; --smoke must be used alone");
        }
        std::vector<uint32_t> a(count), b(count), actual(count);
        for (size_t i = 0; i < count; ++i) { a[i] = (i * 13 + 7) % 10007; b[i] = (i * 17 + 11) % 997; }
        auto init_start = BenchClock::now();
        int devices = 0, runtime = 0, driver = 0;
        check(cudaGetDeviceCount(&devices), "cudaGetDeviceCount");
        if (devices < 1) throw std::runtime_error("No CUDA device available");
        check(cudaSetDevice(0), "cudaSetDevice");
        check(cudaFree(nullptr), "initialize CUDA context");
        cudaDeviceProp properties{};
        check(cudaGetDeviceProperties(&properties, 0), "cudaGetDeviceProperties");
        check(cudaRuntimeGetVersion(&runtime), "cudaRuntimeGetVersion");
        check(cudaDriverGetVersion(&driver), "cudaDriverGetVersion");
        double init_ms = elapsed_ms(init_start);
        DeviceMemory memory;
        const size_t bytes = size_t(count) * sizeof(uint32_t);
        auto allocate_start = BenchClock::now();
        check(cudaMalloc(reinterpret_cast<void **>(&memory.a), bytes), "cudaMalloc a");
        check(cudaMalloc(reinterpret_cast<void **>(&memory.b), bytes), "cudaMalloc b");
        check(cudaMalloc(reinterpret_cast<void **>(&memory.c), bytes), "cudaMalloc output");
        double allocation_ms = elapsed_ms(allocate_start);
        auto upload_start = BenchClock::now();
        check(cudaMemcpy(memory.a, a.data(), bytes, cudaMemcpyHostToDevice), "upload a");
        check(cudaMemcpy(memory.b, b.data(), bytes, cudaMemcpyHostToDevice), "upload b");
        double upload_ms = elapsed_ms(upload_start);
        Events events;
        check(cudaEventCreate(&events.start), "create start event");
        check(cudaEventCreate(&events.end), "create end event");
        unsigned blocks = (count + 255) / 256;
        auto first_start = BenchClock::now();
        check(cudaEventRecord(events.start), "record first start");
        add_vectors<<<blocks, 256>>>(memory.a, memory.b, memory.c, count);
        check(cudaGetLastError(), "first kernel launch");
        check(cudaEventRecord(events.end), "record first end");
        check(cudaEventSynchronize(events.end), "first kernel completion");
        float first_gpu_ms = 0;
        check(cudaEventElapsedTime(&first_gpu_ms, events.start, events.end), "first event time");
        double first_wall_ms = elapsed_ms(first_start);
        auto download_start = BenchClock::now();
        check(cudaMemcpy(actual.data(), memory.c, bytes, cudaMemcpyDeviceToHost), "download first output");
        double download_ms = elapsed_ms(download_start);
        verify(a, b, actual);
        std::vector<float> samples;
        double warmup_ms = 0;
        if (!smoke) {
            auto warm_start = BenchClock::now();
            for (unsigned i = 0; i < 5; ++i) add_vectors<<<blocks, 256>>>(memory.a, memory.b, memory.c, count);
            check(cudaGetLastError(), "warmup launch");
            check(cudaDeviceSynchronize(), "warmup completion");
            warmup_ms = elapsed_ms(warm_start);
            for (unsigned repeat = 0; repeat < repeats; ++repeat) {
                check(cudaEventRecord(events.start), "record steady start");
                for (unsigned i = 0; i < iterations; ++i)
                    add_vectors<<<blocks, 256>>>(memory.a, memory.b, memory.c, count);
                check(cudaGetLastError(), "steady kernel launch");
                check(cudaEventRecord(events.end), "record steady end");
                check(cudaEventSynchronize(events.end), "steady kernel completion");
                float duration = 0;
                check(cudaEventElapsedTime(&duration, events.start, events.end), "steady event time");
                if (duration <= 0) throw std::runtime_error("Invalid CUDA event elapsed time");
                samples.push_back(duration);
            }
            check(cudaMemcpy(actual.data(), memory.c, bytes, cudaMemcpyDeviceToHost), "download steady output");
            verify(a, b, actual);
        }
        std::cout << std::setprecision(10)
                  << "{\"schema_version\":1,\"benchmark\":\"cuda_vector_add_u32_v1\",\"passed\":true,\"smoke\":"
                  << (smoke ? "true" : "false") << ",\"device\":{\"index\":0,\"name\":" << json_string(properties.name)
                  << ",\"compute_major\":" << properties.major << ",\"compute_minor\":" << properties.minor
                  << ",\"total_memory_bytes\":" << properties.totalGlobalMem << "},\"cuda_runtime_version\":" << runtime
                  << ",\"cuda_driver_version\":" << driver << ",\"elements\":" << count
                  << ",\"verified_elements_per_check\":" << count << ",\"initialization_ms\":" << init_ms
                  << ",\"device_allocation_ms\":" << allocation_ms << ",\"input_copy_wall_ms\":" << upload_ms
                  << ",\"first_kernel_event_ms\":" << first_gpu_ms << ",\"first_kernel_wall_ms\":" << first_wall_ms
                  << ",\"first_output_copy_wall_ms\":" << download_ms << ",\"warmup_ms\":" << warmup_ms
                  << ",\"iterations_per_sample\":" << (smoke ? 0 : iterations) << ",\"samples\":[";
        for (size_t i = 0; i < samples.size(); ++i) {
            if (i) std::cout << ',';
            double logical_bytes = double(bytes) * 3 * iterations;
            std::cout << "{\"event_ms\":" << samples[i] << ",\"mean_kernel_ms\":" << samples[i] / iterations
                      << ",\"logical_effective_gb_per_second\":" << logical_bytes / (samples[i] * 1e6) << '}';
        }
        std::cout << "],\"total_wall_ms_before_cleanup\":" << elapsed_ms(start) << "}\n";
        return 0;
    } catch (const std::exception &error) {
        std::cout << "{\"schema_version\":1,\"benchmark\":\"cuda_vector_add_u32_v1\",\"passed\":false,\"error\":"
                  << json_string(error.what()) << "}\n";
        return 1;
    }
}
