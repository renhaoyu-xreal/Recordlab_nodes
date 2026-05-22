#include "recordlab_nodes/watchdog_node.h"

#include <chrono>
#include <iostream>
#include <thread>

int main() {
  recordlab::nodes::WatchdogNode node;
  if (!node.start()) return 1;
  std::cout << "watchdog_node running\n";
  while (true) std::this_thread::sleep_for(std::chrono::seconds(1));
}
