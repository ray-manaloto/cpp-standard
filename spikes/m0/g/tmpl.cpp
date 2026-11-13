#include <meta>
struct widget {
  template <int N> int scaled() const { return v * N; }
  int v;
};
consteval auto scaled_member() {
  return std::meta::members_of(^^widget, std::meta::access_context::unchecked())[0];
}
int main() {
  widget w{2};
  constexpr auto m = scaled_member();
  return w.template [: m :]<3>() == 6 ? 0 : 1;
}
