#include <thread>
int counter = 0;
int main() {
  std::thread t([] { ++counter; });
  ++counter;
  t.join();
  return 0;
}
