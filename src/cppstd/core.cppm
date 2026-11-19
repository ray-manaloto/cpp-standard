// The core module (design PR 4): small, pure helpers every later module builds on. It is named and
// imports the standard library as a module (`import std`), so each gate preset proves that its
// compiler, standard library and CMake agree on std modules.
export module cppstd.core;

import std;

export namespace cppstd::core {

// The decimal unsigned integer in `text`: nullopt for an empty text, a character that is no digit
// or a value past 32 bits.
constexpr std::optional<std::uint32_t> parse_u32(std::string_view text) {
  if (text.empty()) {
    return std::nullopt;
  }
  std::uint64_t value = 0;
  for (char c : text) {
    if (c < '0' || c > '9') {
      return std::nullopt;
    }
    value = value * 10 + static_cast<std::uint64_t>(c - '0');
    if (value > std::numeric_limits<std::uint32_t>::max()) {
      return std::nullopt;
    }
  }
  return static_cast<std::uint32_t>(value);
}

// The parts joined with `separator` between them.
inline std::string join(std::span<const std::string_view> parts, std::string_view separator) {
  std::string out;
  for (std::size_t i = 0; i < parts.size(); ++i) {
    if (i != 0) {
      out += separator;
    }
    out += parts[i];
  }
  return out;
}

static_assert(parse_u32("4294967295") == 4294967295u);
static_assert(!parse_u32("4294967296"));

}  // namespace cppstd::core
