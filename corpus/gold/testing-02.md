---
id: testing-02
dimension: testing
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Write tests for `crc16_modbus()` used in DFU framing.

# Context

CRC-16/MODBUS: reflected polynomial `0xA001` (`0x8005` bit-reversed), init
`0xFFFF`, no final XOR. Two entry points exist and are believed correct:
`uint16_t crc16_modbus(const uint8_t* data, size_t len)` (one-shot) and
`uint16_t crc16_modbus_update(uint16_t crc, uint8_t byte)` (incremental,
seeded with `0xFFFF`). The empty payload yields the init value `0xFFFF`; the
standard check string "123456789" yields `0x4B37`.

## A (focused)

```cpp
TEST(Crc16Modbus, KnownVectors) {
    const uint8_t check[] = {'1','2','3','4','5','6','7','8','9'};
    EXPECT_EQ(crc16_modbus(check, 0), 0xFFFF);   // empty: the init value
    EXPECT_EQ(crc16_modbus(check, 9), 0x4B37);   // standard check value
    const uint8_t frame[] = {0xA1, 0x03};        // a real packet header
    EXPECT_EQ(crc16_modbus(frame, 2), 0x2138);
}
```

Three known-answer vectors: the empty payload, the spec's check string, and
one real frame prefix.

## B (exhaustive)

```cpp
TEST(Crc16Modbus, KnownVectors) {
    const uint8_t check[] = {'1','2','3','4','5','6','7','8','9'};
    EXPECT_EQ(crc16_modbus(check, 0), 0xFFFF);   // empty: the init value
    EXPECT_EQ(crc16_modbus(check, 9), 0x4B37);   // standard check value
    const uint8_t frame[] = {0xA1, 0x03};
    EXPECT_EQ(crc16_modbus(frame, 2), 0x2138);
    const std::vector<uint8_t> ff(16, 0xFF);     // all-ones frame body
    EXPECT_EQ(crc16_modbus(ff.data(), ff.size()), 0x80FE);
}
TEST(Crc16Modbus, SingleByteSweepIsInjective) {
    std::set<uint16_t> seen;
    for (int b = 0; b < 256; ++b) {
        const uint8_t byte = static_cast<uint8_t>(b);
        seen.insert(crc16_modbus(&byte, 1));
    }
    EXPECT_EQ(seen.size(), 256u);  // any single-byte corruption is detected
}
TEST(Crc16Modbus, IncrementalMatchesOneShot) {
    const uint8_t check[] = {'1','2','3','4','5','6','7','8','9'};
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < 9; ++i) crc = crc16_modbus_update(crc, check[i]);
    EXPECT_EQ(crc, crc16_modbus(check, 9));
}
TEST(Crc16Modbus, BitFlipChangesCrc) {
    uint8_t buf[] = {'1','2','3','4','5','6','7','8','9'};
    buf[4] ^= 0x01;
    EXPECT_NE(crc16_modbus(buf, 9), 0x4B37);  // CRCs catch single-bit errors
}
```

The known vectors plus the all-`0xFF` frame, a full single-byte sweep
asserting 256 distinct CRCs, the incremental-equals-one-shot property, and a
mutation check.

# Notes

Every expected value verified against the stated parameters (poly `0xA001`
reflected, init `0xFFFF`, no final XOR): empty -> `0xFFFF`, "123456789" ->
`0x4B37`, `{0xA1, 0x03}` -> `0x2138`, sixteen `0xFF` bytes -> `0x80FE`; the
256 single-byte CRCs are in fact distinct, and a single-bit flip always
changes a CRC-16, so the `EXPECT_NE` cannot be flaky. A's three vectors
already pin the algorithm parameters; B adds property and mutation coverage
over the same correct function. The axis is coverage appetite only.
