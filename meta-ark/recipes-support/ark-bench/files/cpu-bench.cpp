// SPDX-License-Identifier: MIT
// Single-thread fixed-data SHA-256 throughput, using the target OpenSSL backend.
#include "bench-common.h"
#include <openssl/evp.h>
#include <openssl/opensslv.h>
#include <iostream>
#include <memory>
#include <vector>

using Context = std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)>;
static std::string digest(const unsigned char *data, size_t bytes, unsigned copies) {
    Context context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1)
        throw std::runtime_error("OpenSSL SHA-256 initialization failed");
    for (unsigned i = 0; i < copies; ++i)
        if (EVP_DigestUpdate(context.get(), data, bytes) != 1)
            throw std::runtime_error("OpenSSL SHA-256 update failed");
    unsigned char output[EVP_MAX_MD_SIZE];
    unsigned length = 0;
    if (EVP_DigestFinal_ex(context.get(), output, &length) != 1 || length != 32)
        throw std::runtime_error("OpenSSL SHA-256 finalization failed");
    std::ostringstream hex;
    for (unsigned i = 0; i < length; ++i)
        hex << std::hex << std::setw(2) << std::setfill('0') << unsigned(output[i]);
    return hex.str();
}

int main(int argc, char **argv) {
    auto start = BenchClock::now();
    try {
        unsigned mib = 256, repeats = 3;
        for (int i = 1; i < argc; ++i) {
            std::string option(argv[i]);
            if (option == "--help") {
                std::cout << "ark-cpu-bench [--mib 64|256|1024] [--repeats 1..10]\n";
                return 0;
            }
            if ((option != "--mib" && option != "--repeats") || i + 1 == argc)
                throw std::invalid_argument("Unknown or incomplete option");
            unsigned value = bounded_uint(argv[++i], 1, option == "--mib" ? 1024 : 10);
            if (option == "--mib") mib = value; else repeats = value;
        }
        std::string expected;
        switch (mib) {
        case 64: expected = "281e519df3077b557c6b03f5da83c4e8d397219259615dd7c3308f89cae8f2a6"; break;
        case 256: expected = "486cc817b95d853d3c357ff283b204c0144bd255e73fe2deb1389493b257e3c0"; break;
        case 1024: expected = "2c06ade942ee3f17a048dd1064b2fab046a4bb95386d8bb41b68dc6711ac2af3"; break;
        default: throw std::invalid_argument("--mib must be 64, 256, or 1024");
        }
        // Independent standard known-answer test before benchmarking.
        auto init_start = BenchClock::now();
        if (digest(reinterpret_cast<const unsigned char *>("abc"), 3, 1) !=
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            throw std::runtime_error("SHA-256 known-answer test failed");
        double init_ms = elapsed_ms(init_start);
        std::vector<unsigned char> block(1024 * 1024);
        for (size_t i = 0; i < block.size(); ++i) block[i] = static_cast<unsigned char>(i);
        auto warm_start = BenchClock::now();
        if (digest(block.data(), block.size(), mib) != expected)
            throw std::runtime_error("Fixed-data warmup checksum mismatch");
        double warm_ms = elapsed_ms(warm_start);
        std::vector<double> samples;
        for (unsigned i = 0; i < repeats; ++i) {
            auto begin = BenchClock::now();
            auto actual = digest(block.data(), block.size(), mib);
            double duration = elapsed_ms(begin);
            if (actual != expected) throw std::runtime_error("Fixed-data checksum mismatch");
            if (duration <= 0) throw std::runtime_error("Invalid elapsed time");
            samples.push_back(duration);
        }
        std::cout << std::setprecision(10)
                  << "{\"schema_version\":1,\"benchmark\":\"openssl_sha256_fixed_data_v1\",\"passed\":true,"
                  << "\"threads\":1,\"backend\":" << json_string(OpenSSL_version(OPENSSL_VERSION))
                  << ",\"mib_per_repeat\":" << mib << ",\"bytes_per_repeat\":" << uint64_t(mib) * 1024 * 1024
                  << ",\"block_bytes\":1048576,\"expected_sha256\":" << json_string(expected)
                  << ",\"initialization_and_known_answer_ms\":" << init_ms
                  << ",\"warmup_ms\":" << warm_ms << ",\"samples\":[";
        for (size_t i = 0; i < samples.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << "{\"wall_ms\":" << samples[i] << ",\"mib_per_second\":" << mib * 1000.0 / samples[i] << '}';
        }
        std::cout << "],\"total_wall_ms\":" << elapsed_ms(start) << "}\n";
        return 0;
    } catch (const std::exception &error) {
        std::cout << "{\"schema_version\":1,\"benchmark\":\"openssl_sha256_fixed_data_v1\",\"passed\":false,\"error\":"
                  << json_string(error.what()) << "}\n";
        return 1;
    }
}
