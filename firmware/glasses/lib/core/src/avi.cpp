#include "avi.h"

namespace hvr {

namespace {
constexpr uint32_t make_fcc(char a, char b, char c, char d) {
  return static_cast<uint32_t>(a) | (static_cast<uint32_t>(b) << 8) | (static_cast<uint32_t>(c) << 16) |
         (static_cast<uint32_t>(d) << 24);
}
constexpr uint32_t kVideoChunk = make_fcc('0', '0', 'd', 'c');
constexpr uint32_t kAudioChunk = make_fcc('0', '1', 'w', 'b');
constexpr uint32_t kKeyframe = 0x10;     // AVIIF_KEYFRAME
constexpr uint32_t kHasIndex = 0x10;     // AVIF_HASINDEX
constexpr uint32_t kStrhSize = 56;
}  // namespace

bool AviWriter::u32(uint32_t v) {
  uint8_t b[4] = {uint8_t(v), uint8_t(v >> 8), uint8_t(v >> 16), uint8_t(v >> 24)};
  return sink_.write(b, 4);
}

bool AviWriter::u16(uint16_t v) {
  uint8_t b[2] = {uint8_t(v), uint8_t(v >> 8)};
  return sink_.write(b, 2);
}

bool AviWriter::fcc(const char* s) { return sink_.write(reinterpret_cast<const uint8_t*>(s), 4); }

bool AviWriter::patch(uint32_t pos, uint32_t v) { return sink_.seek(pos) && u32(v); }

bool AviWriter::begin(uint16_t width, uint16_t height, uint32_t audioRate) {
  width_ = width;
  height_ = height;
  audioRate_ = audioRate;
  frames_ = audioBytes_ = videoBytes_ = maxVideo_ = maxAudio_ = 0;
  entries_ = 0;
  const uint32_t streams = audioRate ? 2 : 1;
  const uint32_t videoStrl = 4 + (8 + kStrhSize) + (8 + 40);
  const uint32_t audioStrl = 4 + (8 + kStrhSize) + (8 + 18);
  const uint32_t hdrl = 4 + (8 + 56) + (8 + videoStrl) + (audioRate ? 8 + audioStrl : 0);

  bool ok = fcc("RIFF");
  posRiffSize_ = sink_.position();
  ok = ok && u32(0) && fcc("AVI ") && fcc("LIST") && u32(hdrl) && fcc("hdrl");

  // MainAVIHeader
  ok = ok && fcc("avih") && u32(56);
  posAvih_ = sink_.position();
  ok = ok && u32(0) && u32(0) && u32(0) && u32(kHasIndex) && u32(0) && u32(0) && u32(streams) && u32(0) &&
       u32(width) && u32(height) && u32(0) && u32(0) && u32(0) && u32(0);

  // Video stream: MJPEG
  ok = ok && fcc("LIST") && u32(videoStrl) && fcc("strl") && fcc("strh") && u32(kStrhSize);
  posVideoStrh_ = sink_.position();
  ok = ok && fcc("vids") && fcc("MJPG") && u32(0) && u16(0) && u16(0) && u32(0) &&
       u32(1000) && u32(0) && u32(0) && u32(0) && u32(0) && u32(0xFFFFFFFF) && u32(0) &&
       u16(0) && u16(0) && u16(width) && u16(height);
  ok = ok && fcc("strf") && u32(40) && u32(40) && u32(width) && u32(height) && u16(1) && u16(24) &&
       fcc("MJPG") && u32(uint32_t(width) * height * 3) && u32(0) && u32(0) && u32(0) && u32(0);

  if (audioRate) {  // Audio stream: PCM, mono, 16-bit
    ok = ok && fcc("LIST") && u32(audioStrl) && fcc("strl") && fcc("strh") && u32(kStrhSize);
    posAudioStrh_ = sink_.position();
    ok = ok && fcc("auds") && u32(0) && u32(0) && u16(0) && u16(0) && u32(0) &&
         u32(2) && u32(audioRate * 2) && u32(0) && u32(0) && u32(0) && u32(0xFFFFFFFF) && u32(2) &&
         u16(0) && u16(0) && u16(0) && u16(0);
    ok = ok && fcc("strf") && u32(18) && u16(1) && u16(1) && u32(audioRate) && u32(audioRate * 2) &&
         u16(2) && u16(16) && u16(0);
  }

  ok = ok && fcc("LIST");
  posMoviSize_ = sink_.position();
  ok = ok && u32(0);
  posMovi_ = sink_.position();
  return ok && fcc("movi");
}

bool AviWriter::chunk(uint32_t fourcc, const uint8_t* data, size_t len) {
  if (entries_ >= capacity_) return false;
  const uint32_t pos = sink_.position();
  bool ok = u32(fourcc) && u32(static_cast<uint32_t>(len)) && sink_.write(data, len);
  if (len & 1) {  // chunks are word aligned
    const uint8_t pad = 0;
    ok = ok && sink_.write(&pad, 1);
  }
  if (!ok) return false;
  index_[entries_++] = {fourcc, kKeyframe, pos - posMovi_, static_cast<uint32_t>(len)};
  return true;
}

bool AviWriter::addVideoFrame(const uint8_t* jpeg, size_t len) {
  if (!chunk(kVideoChunk, jpeg, len)) return false;
  ++frames_;
  videoBytes_ += len;
  if (len > maxVideo_) maxVideo_ = len;
  return true;
}

bool AviWriter::addAudio(const int16_t* samples, size_t count) {
  if (!audioRate_ || count == 0) return true;   // no audio stream: nothing to store
  const size_t len = count * 2;
  if (!chunk(kAudioChunk, reinterpret_cast<const uint8_t*>(samples), len)) return false;
  audioBytes_ += len;
  if (len > maxAudio_) maxAudio_ = len;
  return true;
}

bool AviWriter::finish(uint32_t durationMs) {
  const uint32_t idxPos = sink_.position();
  bool ok = fcc("idx1") && u32(static_cast<uint32_t>(entries_ * 16));
  for (size_t i = 0; ok && i < entries_; ++i) {
    ok = u32(index_[i].fourcc) && u32(index_[i].flags) && u32(index_[i].offset) && u32(index_[i].size);
  }
  const uint32_t end = sink_.position();
  if (!ok) return false;

  if (durationMs == 0) durationMs = 1;
  const uint64_t usPerFrame = frames_ ? uint64_t(durationMs) * 1000 / frames_ : 0;
  const uint32_t fpsMilli = frames_ ? uint32_t(uint64_t(frames_) * 1000000 / durationMs) : 0;  // frames per 1000 s
  const uint32_t bytesPerSec = uint32_t(uint64_t(videoBytes_ + audioBytes_) * 1000 / durationMs);
  const uint32_t maxChunk = maxVideo_ > maxAudio_ ? maxVideo_ : maxAudio_;

  ok = patch(posRiffSize_, end - 8) && patch(posMoviSize_, idxPos - posMoviSize_ - 4) &&
       patch(posAvih_, uint32_t(usPerFrame)) && patch(posAvih_ + 4, bytesPerSec) &&
       patch(posAvih_ + 16, frames_) && patch(posAvih_ + 28, maxChunk) &&
       patch(posVideoStrh_ + 24, fpsMilli) &&        // dwRate (dwScale = 1000)
       patch(posVideoStrh_ + 32, frames_) &&         // dwLength
       patch(posVideoStrh_ + 36, maxVideo_);         // dwSuggestedBufferSize
  if (audioRate_) {
    ok = ok && patch(posAudioStrh_ + 32, audioBytes_ / 2) && patch(posAudioStrh_ + 36, maxAudio_);
  }
  return ok && sink_.seek(end);
}

}  // namespace hvr
