// The stand-in module, copied from the M0 (b) and (j) spike
// (spikes/m0/bj/src/encoder.cppm, D106) so that the gate keeps a source file
// when M1a PR 3 deletes the spikes. It is removed when the encoder and core
// modules reach 100% coverage. Run-time code with branches,
// compile-time-only helpers (a consteval function, a static consteval
// member, a constexpr function used only in static_assert) that gcov mode
// must not count, and, on a compiler with reflection, a run-time function
// built from splices.
module;
#include <cstdint>
#include <string_view>
// GCC 16 defines __cpp_impl_reflection; clang-p2996 does not, and reports
// reflection through __has_feature(reflection) instead (D105).
#if defined(__cpp_impl_reflection)
#define STANDIN_HAS_REFLECTION 1
#elif defined(__has_feature)
#if __has_feature(reflection)
#define STANDIN_HAS_REFLECTION 1
#endif
#endif
#if STANDIN_HAS_REFLECTION
#include <meta>
#endif
export module standin;

export namespace standin {

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

// Run-time code from reflection where the compiler has it; plain code
// elsewhere, so every compiler runs the same test.
int field_sum(const heartbeat& h) {
#if STANDIN_HAS_REFLECTION
  constexpr auto ctx = std::meta::access_context::unchecked();
  return h.[:std::meta::nonstatic_data_members_of(^^heartbeat, ctx)[0]:] +
         h.[:std::meta::nonstatic_data_members_of(^^heartbeat, ctx)[1]:];
#else
  return h.seq + h.len;
#endif
}

}  // namespace standin

static_assert(standin::soh() == 0x01);
static_assert(standin::limits::max_tag() == 9999);
static_assert(standin::checksum("") == 0);
static_assert(standin::is_tag_char('8') && !standin::is_tag_char('='));
