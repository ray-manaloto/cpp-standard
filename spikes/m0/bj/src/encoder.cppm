// A stand-in for the encoder module: run-time code with branches,
// compile-time-only helpers (a consteval function, a static consteval
// member, a constexpr function used only in static_assert) that gcov mode
// must not count, and, on a compiler with reflection (p2996), a run-time
// function built from splices.
module;
#include <cstdint>
#include <string_view>
#if M0_REQUIRE_REFLECTION && !__cpp_impl_reflection
#error "M0_REQUIRE_REFLECTION is set but the compiler has no reflection"
#endif
#if __cpp_impl_reflection
#include <meta>
#endif
export module encoder;

export namespace encoder {

consteval std::uint8_t soh() { return 0x01; }

struct limits {
  static consteval int max_tag() { return 9999; }
};

// constexpr, used only in static_assert: gcov mode must not count it.
constexpr bool is_tag_char(char c) { return c >= '0' && c <= '9'; }

constexpr std::uint32_t checksum(std::string_view body) {
  std::uint32_t sum = 0;
  for (char c : body) {
    sum += static_cast<unsigned char>(c);
  }
  return sum % 256;
}

std::string_view tag_name(int tag) {
  switch (tag) {
    case 8:
      return "BeginString";
    case 35:
      return "MsgType";
    default:
      return "Unknown";
  }
}

struct heartbeat {
  int seq;
  int len;
};

// Run-time code from reflection on p2996; plain code elsewhere, so every
// compiler runs the same test.
int field_sum(const heartbeat& h) {
#if __cpp_impl_reflection
  constexpr auto ctx = std::meta::access_context::unchecked();
  return h.[:std::meta::nonstatic_data_members_of(^^heartbeat, ctx)[0]:] +
         h.[:std::meta::nonstatic_data_members_of(^^heartbeat, ctx)[1]:];
#else
  return h.seq + h.len;
#endif
}

}  // namespace encoder

static_assert(encoder::soh() == 0x01);
static_assert(encoder::limits::max_tag() == 9999);
static_assert(encoder::checksum("") == 0);
static_assert(encoder::is_tag_char('8') && !encoder::is_tag_char('='));
