// The core module's tests: bext-ut for the run-time checks (the include comes before the imports),
// static_assert in the module for the compile-time ones.
#include <boost/ut.hpp>

import std;
import cppstd.core;

int main() {
  using namespace boost::ut;
  using cppstd::core::join;
  using cppstd::core::parse_u32;

  "parse_u32 reads decimal numbers"_test = [] {
    expect(parse_u32("0") == std::optional<std::uint32_t>{0});
    expect(parse_u32("4294967295") == std::optional<std::uint32_t>{4294967295u});
  };

  "parse_u32 refuses what is no number"_test = [] {
    expect(!parse_u32(""));
    expect(!parse_u32("12a"));
    expect(!parse_u32("-1"));
  };

  "parse_u32 refuses a value past 32 bits"_test = [] { expect(!parse_u32("4294967296")); };

  "join puts the separator between the parts"_test = [] {
    const std::array<std::string_view, 3> parts{"a", "b", "c"};
    expect(join(parts, ", ") == "a, b, c");
    expect(join({}, ",").empty());
  };
}
