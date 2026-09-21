// SPDX-License-Identifier: MIT
#pragma once
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>

using BenchClock = std::chrono::steady_clock;
inline double elapsed_ms(BenchClock::time_point since) {
    return std::chrono::duration<double, std::milli>(BenchClock::now() - since).count();
}
inline std::string json_string(const std::string &value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        switch (c) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c) << std::dec;
            else out << c;
        }
    }
    return out.str() + '"';
}
inline unsigned bounded_uint(const std::string &text, unsigned low, unsigned high) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("Expected an unsigned decimal integer");
    auto value = std::stoull(text);
    if (value < low || value > high) throw std::invalid_argument("Argument outside supported bounds");
    return static_cast<unsigned>(value);
}
