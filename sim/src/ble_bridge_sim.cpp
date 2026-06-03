// TCP-backed BLE bridge for the simulator.
//
// On real hardware, ble_bridge.cpp speaks Nordic UART Service over GATT.
// In the sim we expose the same line-delimited JSON protocol over a TCP
// socket on 127.0.0.1:31415 so the Tk driver (or any netcat) can drive
// the firmware. One client at a time; if the client disconnects, the
// firmware sees bleConnected()=false until the next connection.
//
// A background thread accepts connections + drains incoming bytes into
// the same RX ring buffer the real bridge uses. bleWrite() pushes to a
// TX queue that gets flushed to the socket from the same thread (so we
// don't have to deal with cross-thread send blocking).

#include "ble_bridge.h"
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <unistd.h>

static constexpr int  PORT    = 31415;
static constexpr size_t RX_CAP = 2048;

static uint8_t            s_rx[RX_CAP];
static size_t             s_rxHead = 0, s_rxTail = 0;
static std::mutex         s_rxMu;

static std::vector<uint8_t> s_tx;
static std::mutex           s_txMu;

static std::atomic<bool>  s_connected{false};
static std::atomic<bool>  s_running{false};
static std::thread        s_thread;
static int                s_listenFd = -1;
static int                s_clientFd = -1;

static void rxPush(const uint8_t* p, size_t n) {
  std::lock_guard<std::mutex> lk(s_rxMu);
  for (size_t i = 0; i < n; i++) {
    size_t next = (s_rxHead + 1) % RX_CAP;
    if (next == s_rxTail) return;   // full — drop
    s_rx[s_rxHead] = p[i];
    s_rxHead = next;
  }
}

static void closeClient() {
  if (s_clientFd >= 0) { ::close(s_clientFd); s_clientFd = -1; }
  s_connected.store(false);
  // Flush any buffered TX so leftover bytes don't appear on the next client.
  std::lock_guard<std::mutex> lk(s_txMu);
  s_tx.clear();
}

static void serverThread() {
  while (s_running.load()) {
    if (s_clientFd < 0) {
      // Non-blocking accept poll.
      sockaddr_in cli{}; socklen_t cl = sizeof(cli);
      int fd = ::accept(s_listenFd, (sockaddr*)&cli, &cl);
      if (fd < 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        continue;
      }
      // Make client non-blocking so recv doesn't pin the thread.
      int fl = fcntl(fd, F_GETFL, 0);
      fcntl(fd, F_SETFL, fl | O_NONBLOCK);
      s_clientFd = fd;
      s_connected.store(true);
      std::fprintf(stderr, "[ble-sim] client connected\n");
    }

    // Drain RX.
    uint8_t buf[512];
    ssize_t n = ::recv(s_clientFd, buf, sizeof(buf), 0);
    if (n > 0) {
      rxPush(buf, (size_t)n);
    } else if (n == 0) {
      std::fprintf(stderr, "[ble-sim] client disconnected\n");
      closeClient();
      continue;
    } else {
      if (errno != EAGAIN && errno != EWOULDBLOCK) {
        std::fprintf(stderr, "[ble-sim] recv err: %s\n", std::strerror(errno));
        closeClient();
        continue;
      }
    }

    // Flush TX.
    std::vector<uint8_t> pending;
    {
      std::lock_guard<std::mutex> lk(s_txMu);
      pending.swap(s_tx);
    }
    if (!pending.empty() && s_clientFd >= 0) {
      ssize_t sent = ::send(s_clientFd, pending.data(), pending.size(), 0);
      if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        std::fprintf(stderr, "[ble-sim] send err: %s\n", std::strerror(errno));
        closeClient();
        continue;
      }
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  closeClient();
  if (s_listenFd >= 0) { ::close(s_listenFd); s_listenFd = -1; }
}

void bleInit(const char* deviceName) {
  if (s_running.load()) return;
  s_listenFd = ::socket(AF_INET, SOCK_STREAM, 0);
  if (s_listenFd < 0) { std::perror("[ble-sim] socket"); return; }
  int yes = 1;
  ::setsockopt(s_listenFd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  a.sin_port = htons(PORT);
  if (::bind(s_listenFd, (sockaddr*)&a, sizeof(a)) < 0) {
    std::perror("[ble-sim] bind");
    ::close(s_listenFd); s_listenFd = -1;
    return;
  }
  if (::listen(s_listenFd, 1) < 0) {
    std::perror("[ble-sim] listen");
    ::close(s_listenFd); s_listenFd = -1;
    return;
  }
  int fl = fcntl(s_listenFd, F_GETFL, 0);
  fcntl(s_listenFd, F_SETFL, fl | O_NONBLOCK);
  s_running.store(true);
  s_thread = std::thread(serverThread);
  s_thread.detach();   // process exits without us joining; detach to avoid std::terminate
  std::fprintf(stderr, "[ble-sim] %s listening on 127.0.0.1:%d\n",
               deviceName ? deviceName : "(unnamed)", PORT);
}

bool bleConnected()   { return s_connected.load(); }
bool bleSecure()      { return s_connected.load(); }   // sim treats connected==secure
uint32_t blePasskey() { return 0; }
void bleClearBonds()  { /* no-op in sim */ }

size_t bleAvailable() {
  std::lock_guard<std::mutex> lk(s_rxMu);
  return (s_rxHead + RX_CAP - s_rxTail) % RX_CAP;
}

int bleRead() {
  std::lock_guard<std::mutex> lk(s_rxMu);
  if (s_rxHead == s_rxTail) return -1;
  uint8_t b = s_rx[s_rxTail];
  s_rxTail = (s_rxTail + 1) % RX_CAP;
  return b;
}

size_t bleWrite(const uint8_t* data, size_t len) {
  if (!s_connected.load() || !data || !len) return 0;
  std::lock_guard<std::mutex> lk(s_txMu);
  s_tx.insert(s_tx.end(), data, data + len);
  return len;
}
