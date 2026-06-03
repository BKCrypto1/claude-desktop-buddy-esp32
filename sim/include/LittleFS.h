#pragma once
#include <Arduino.h>
#include <cstdio>
#include <string>

// LittleFS shim backed by a sandboxed directory under
// ~/.cache/buddy-sim/fs/. Same surface as Arduino LittleFS.

class File {
public:
  File();
  File(const File&)            = delete;
  File& operator=(const File&) = delete;
  File(File&& o) noexcept;
  File& operator=(File&& o) noexcept;
  ~File();

  bool isOpen() const { return _kind != Closed; }
  operator bool() const { return _kind != Closed; }

  bool isDirectory() const { return _kind == Dir; }
  const char* name() const { return _name.c_str(); }
  size_t size() const;

  size_t  read(uint8_t* buf, size_t n);
  // ArduinoJson v7's Reader<File> calls f.read() with no args expecting an
  // int (byte read or -1 on EOF). Return that path here so JSON loads work.
  int     read();
  size_t  write(const uint8_t* buf, size_t n);
  bool    seek(size_t pos);
  size_t  position();
  void    close();

  File openNextFile();   // valid only on Dir handles
  File open(const char* path, const char* mode);  // for compat — opens absolute path

private:
  enum Kind { Closed, Reg, Dir };
  Kind         _kind = Closed;
  std::FILE*   _fp   = nullptr;
  std::string  _path;     // absolute host path
  std::string  _name;     // basename used by name()
  void*        _dirh = nullptr;  // DIR*
  std::string  _vfsPath;  // virtual path for openNextFile to compose children
  friend class _LittleFS;
};

class _LittleFS {
public:
  bool   begin(bool format = false);
  bool   format();
  File   open(const char* path, const char* mode = "r");
  bool   exists(const char* path);
  bool   remove(const char* path);
  bool   mkdir(const char* path);
  bool   rmdir(const char* path);
  size_t totalBytes();
  size_t usedBytes();
};
extern _LittleFS LittleFS;
