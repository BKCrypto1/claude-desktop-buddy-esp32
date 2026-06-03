// LittleFS shim sandboxed to ~/.cache/buddy-sim/fs/.
// Maps virtual paths like "/characters/bufo/manifest.json" onto host
// paths inside the sandbox. Defense-in-depth: reject paths containing
// ".." so malformed BLE traffic can't escape the sandbox.

#include <LittleFS.h>
#include <sys/stat.h>
#include <dirent.h>
#include <unistd.h>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <string>

_LittleFS LittleFS;

static std::string s_root;

static const std::string& root() {
  if (s_root.empty()) {
    const char* h = std::getenv("HOME");
    s_root = std::string(h ? h : "/tmp") + "/.cache/buddy-sim/fs";
  }
  return s_root;
}

static bool ensureDir(const std::string& p) {
  struct stat st;
  if (::stat(p.c_str(), &st) == 0) return S_ISDIR(st.st_mode);
  // Recursively create.
  size_t pos = 1;
  while (pos < p.size()) {
    size_t slash = p.find('/', pos);
    std::string seg = p.substr(0, slash == std::string::npos ? p.size() : slash);
    if (::stat(seg.c_str(), &st) != 0) {
      if (::mkdir(seg.c_str(), 0755) != 0 && errno != EEXIST) return false;
    }
    if (slash == std::string::npos) break;
    pos = slash + 1;
  }
  return true;
}

// Reject ".." anywhere in path; firmware never uses it, so this is purely
// defense-in-depth against malformed BLE payloads.
static bool safePath(const char* p) {
  if (!p) return false;
  if (std::strstr(p, "..")) return false;
  return true;
}

static std::string hostPath(const char* vpath) {
  if (!vpath || !*vpath) return root();
  std::string r = root();
  if (vpath[0] != '/') r += "/";
  r += vpath;
  // Strip trailing slash for stat reliability.
  while (r.size() > 1 && r.back() == '/') r.pop_back();
  return r;
}

// ─────────── File ───────────

File::File() = default;

File::File(File&& o) noexcept
  : _kind(o._kind), _fp(o._fp), _path(std::move(o._path)),
    _name(std::move(o._name)), _dirh(o._dirh), _vfsPath(std::move(o._vfsPath)) {
  o._kind = Closed; o._fp = nullptr; o._dirh = nullptr;
}
File& File::operator=(File&& o) noexcept {
  if (this != &o) {
    close();
    _kind = o._kind; _fp = o._fp; _path = std::move(o._path);
    _name = std::move(o._name); _dirh = o._dirh; _vfsPath = std::move(o._vfsPath);
    o._kind = Closed; o._fp = nullptr; o._dirh = nullptr;
  }
  return *this;
}

File::~File() { close(); }

void File::close() {
  if (_fp)   { std::fclose(_fp); _fp = nullptr; }
  if (_dirh) { ::closedir((DIR*)_dirh); _dirh = nullptr; }
  _kind = Closed;
}

size_t File::size() const {
  if (_kind != Reg || !_fp) return 0;
  long here = std::ftell(_fp);
  std::fseek(_fp, 0, SEEK_END);
  long n = std::ftell(_fp);
  std::fseek(_fp, here, SEEK_SET);
  return n < 0 ? 0 : (size_t)n;
}

size_t File::read(uint8_t* buf, size_t n) {
  if (_kind != Reg || !_fp || !buf) return 0;
  return std::fread(buf, 1, n, _fp);
}

int File::read() {
  if (_kind != Reg || !_fp) return -1;
  int c = std::fgetc(_fp);
  return c == EOF ? -1 : c;
}

size_t File::write(const uint8_t* buf, size_t n) {
  if (_kind != Reg || !_fp || !buf) return 0;
  return std::fwrite(buf, 1, n, _fp);
}

bool File::seek(size_t pos) {
  if (_kind != Reg || !_fp) return false;
  return std::fseek(_fp, (long)pos, SEEK_SET) == 0;
}

size_t File::position() {
  if (_kind != Reg || !_fp) return 0;
  long p = std::ftell(_fp);
  return p < 0 ? 0 : (size_t)p;
}

File File::openNextFile() {
  File f;
  if (_kind != Dir || !_dirh) return f;
  while (true) {
    struct dirent* ent = ::readdir((DIR*)_dirh);
    if (!ent) return f;
    if (std::strcmp(ent->d_name, ".") == 0 || std::strcmp(ent->d_name, "..") == 0) continue;
    std::string child = _path + "/" + ent->d_name;
    struct stat st;
    if (::stat(child.c_str(), &st) != 0) continue;
    f._path = child;
    f._name = std::string(_vfsPath.empty() ? "/" : _vfsPath) +
              (_vfsPath.empty() || _vfsPath.back() == '/' ? "" : "/") + ent->d_name;
    if (S_ISDIR(st.st_mode)) {
      f._kind = Dir;
      f._dirh = ::opendir(child.c_str());
      f._vfsPath = f._name;
    } else {
      f._kind = Reg;
      f._fp = std::fopen(child.c_str(), "rb");
    }
    return f;
  }
}

File File::open(const char* path, const char* mode) {
  return LittleFS.open(path, mode);
}

// ─────────── _LittleFS ───────────

bool _LittleFS::begin(bool format) {
  if (!ensureDir(root())) return false;
  if (format) this->format();
  return true;
}

bool _LittleFS::format() {
  // Wipe everything under root().
  std::string cmd = "rm -rf " + root() + "/*";
  std::system(cmd.c_str());
  return ensureDir(root());
}

File _LittleFS::open(const char* path, const char* mode) {
  File f;
  if (!safePath(path)) return f;
  std::string h = hostPath(path);
  struct stat st;
  // Mode "r" with a directory → return a Dir handle (xfer.h relies on this).
  if ((mode == nullptr || mode[0] == 'r') && ::stat(h.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) {
    f._kind = File::Dir;
    f._path = h;
    f._name = path;
    f._vfsPath = path;
    f._dirh = ::opendir(h.c_str());
    if (!f._dirh) f._kind = File::Closed;
    return f;
  }
  // Regular file. For write modes, ensure parent dir exists.
  if (mode && (mode[0] == 'w' || mode[0] == 'a')) {
    std::string parent = h;
    size_t slash = parent.find_last_of('/');
    if (slash != std::string::npos) ensureDir(parent.substr(0, slash));
  }
  const char* fmode = mode ? mode : "r";
  // Translate Arduino's "r"/"w" (text) → "rb"/"wb" (binary) for binary safety.
  char mbuf[4] = {0};
  size_t mi = 0;
  for (const char* m = fmode; *m && mi < 3; ++m) mbuf[mi++] = *m;
  bool hasB = false;
  for (size_t i = 0; i < mi; i++) if (mbuf[i] == 'b') hasB = true;
  if (!hasB && mi < 3) mbuf[mi++] = 'b';
  std::FILE* fp = std::fopen(h.c_str(), mbuf);
  if (!fp) return f;
  f._kind = File::Reg;
  f._fp = fp;
  f._path = h;
  f._name = path;
  return f;
}

bool _LittleFS::exists(const char* path) {
  if (!safePath(path)) return false;
  struct stat st;
  return ::stat(hostPath(path).c_str(), &st) == 0;
}

bool _LittleFS::remove(const char* path) {
  if (!safePath(path)) return false;
  return ::unlink(hostPath(path).c_str()) == 0;
}

bool _LittleFS::mkdir(const char* path) {
  if (!safePath(path)) return false;
  return ensureDir(hostPath(path));
}

bool _LittleFS::rmdir(const char* path) {
  if (!safePath(path)) return false;
  // Recursive — character.cpp/xfer.h expect this.
  std::string cmd = "rm -rf " + hostPath(path);
  return std::system(cmd.c_str()) == 0;
}

size_t _LittleFS::totalBytes() { return 8 * 1024 * 1024; }     // pretend 8 MB
size_t _LittleFS::usedBytes()  {
  // crude du; good enough for the FREE/SIZE info page
  std::string cmd = "du -sk " + root() + " 2>/dev/null | awk '{print $1}'";
  std::FILE* p = ::popen(cmd.c_str(), "r");
  if (!p) return 0;
  char buf[64] = {0};
  std::fgets(buf, sizeof(buf), p);
  ::pclose(p);
  return (size_t)std::atol(buf) * 1024;
}
