#include <string_view>
import encoder;

int main() {
  int failures = 0;
  failures += encoder::checksum("A") != 65;
  failures += encoder::tag_name(8) != "BeginString";
  failures += encoder::tag_name(35) != "MsgType";
  failures += encoder::tag_name(1) != "Unknown";
  failures += encoder::field_sum({2, 3}) != 5;
  return failures;
}
