#include <meta>
#include <print>
struct point { int x; int y; };
template <typename T> struct box { T v; };
namespace ns { int x = 7; }
consteval auto first_member(std::meta::info t) {
  return std::meta::nonstatic_data_members_of(t, std::meta::access_context::unchecked())[0];
}
template <typename T> int get_first(T& obj) {
  constexpr auto m = first_member(^^T);
  return obj.[: m :];
}
int main() {
  constexpr auto r = ^^point;
  typename [: r :] p{3, 4};
  constexpr auto mx = first_member(^^point);
  int a = p.[: mx :];
  int b = [: ^^ns::x :];
  int c = [: ::std::meta::reflect_constant(5) :];
  typename [: ^^box :]<int> bx{9};
  int d = get_first(bx);
  std::println("{} {} {} {}", a, b, c, d);
  return (a == 3 && b == 7 && c == 5 && d == 9) ? 0 : 1;
}
