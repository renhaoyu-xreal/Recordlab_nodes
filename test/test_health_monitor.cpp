#include "recordlab_nodes/health_monitor.h"
#include "recordlab_master/registries.h"
#include <cassert>

int main() {
  recordlab::nodes::HealthMonitor m("tcp://127.0.0.1:5998");
  auto stale = m.evaluateTopic("/bsp/imu", recordlab::nowMs() - 2000, 1000, 800, 500);
  assert(stale["health"] == "stale");
  auto low = m.evaluateTopic("/bsp/imu", recordlab::nowMs(), 100, 800, 500);
  assert(low["health"] == "low_rate");
  auto ok = m.evaluateTopic("/bsp/imu", recordlab::nowMs(), 1000, 800, 500);
  assert(ok["health"] == "ok");
}
