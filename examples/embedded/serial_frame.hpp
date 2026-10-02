#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

// Example project fixture, not production firmware.
// Wire format: two-byte big-endian payload length followed by payload.
class SerialFrameDecoder {
public:
    static constexpr std::size_t Capacity = 512;

    bool append(const std::uint8_t* bytes, std::size_t count) {
        if (count > Capacity - size_ || (count != 0 && bytes == nullptr)) {
            return false;
        }
        for (std::size_t i = 0; i < count; ++i) {
            buffer_[size_++] = bytes[i];
        }
        return true;
    }

    bool hasCompleteFrame() const {
        if (size_ < 2) {
            return false;
        }
        const auto length = static_cast<std::size_t>(buffer_[0]) * 256 + buffer_[1];
        return length <= Capacity - 2 && size_ >= length + 2;
    }

    void reset() { size_ = 0; }

private:
    std::array<std::uint8_t, Capacity> buffer_{};
    std::size_t size_ = 0;
};
