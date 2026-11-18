// The stand-in module's test, copied from spikes/m0/bj/tests/encoder_test.cpp.
// It returns the number of failed checks, so ctest fails on any of them.
#include <string_view>
import standin;

int main() {
  int failures = 0;
  failures += standin::checksum("A") != 66;
  failures += standin::tag_name(8) != "BeginString";
  failures += standin::tag_name(35) != "MsgType";
  failures += standin::tag_name(1) != "Unknown";
  failures += standin::field_sum({2, 3}) != 5;
  return failures;
}
