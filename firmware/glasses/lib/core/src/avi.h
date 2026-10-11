// Minimal AVI (RIFF) writer: MJPEG video + optional mono 16-bit PCM audio.
//
// The ESP32-S3 has no H.264 encoder, but the camera hands out JPEG frames for
// free, and an AVI of JPEG frames plays in VLC, mpv, ffmpeg and most editors.
// Headers are written with placeholders and patched in finish(); the index
// lives in caller-provided memory (PSRAM on the glasses).
#pragma once
#include <cstddef>
#include <cstdint>

namespace hvr {

class ByteSink {
 public:
  virtual ~ByteSink() = default;
  virtual bool write(const uint8_t* data, size_t len) = 0;
  virtual bool seek(uint32_t pos) = 0;
  virtual uint32_t position() = 0;
};

struct AviIndexEntry {
  uint32_t fourcc;
  uint32_t flags;
  uint32_t offset;   // from the 'movi' fourcc
  uint32_t size;
};

class AviWriter {
 public:
  AviWriter(ByteSink& sink, AviIndexEntry* index, size_t capacity)
      : sink_(sink), index_(index), capacity_(capacity) {}

  // audioRate = 0 records video only.
  bool begin(uint16_t width, uint16_t height, uint32_t audioRate);
  bool addVideoFrame(const uint8_t* jpeg, size_t len);
  bool addAudio(const int16_t* samples, size_t count);
  // Patch the headers for the real duration and write the index.
  bool finish(uint32_t durationMs);

  uint32_t frames() const { return frames_; }
  uint32_t audioSamples() const { return audioBytes_ / 2; }
  uint32_t bytesWritten() { return sink_.position(); }
  // True when the index is nearly full: start a new segment.
  bool full() const { return entries_ + 2 >= capacity_; }

 private:
  bool chunk(uint32_t fourcc, const uint8_t* data, size_t len);
  bool u32(uint32_t v);
  bool u16(uint16_t v);
  bool fcc(const char* s);
  bool patch(uint32_t pos, uint32_t v);

  ByteSink& sink_;
  AviIndexEntry* index_;
  size_t capacity_;
  size_t entries_ = 0;
  uint16_t width_ = 0, height_ = 0;
  uint32_t audioRate_ = 0;
  uint32_t frames_ = 0, audioBytes_ = 0, videoBytes_ = 0;
  uint32_t maxVideo_ = 0, maxAudio_ = 0;
  // positions of the fields patched in finish()
  uint32_t posRiffSize_ = 0, posAvih_ = 0, posVideoStrh_ = 0, posAudioStrh_ = 0;
  uint32_t posMoviSize_ = 0, posMovi_ = 0;
};

}  // namespace hvr
