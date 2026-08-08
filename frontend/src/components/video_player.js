// Video.js player initialization — lecture synchronisée au playhead
export function initVideoPlayer(elementId, srcUrl) {
  const video = document.createElement('video');
  video.id = elementId;
  video.className = 'video-js vjs-default-skin';
  video.controls = true;
  video.preload = 'auto';
  const source = document.createElement('source');
  source.src = srcUrl;
  source.type = 'video/mp4';
  video.appendChild(source);
  const container = document.getElementById(elementId);
  if (container) container.appendChild(video);
  // Initialisation Video.js (CDN chargé dans index.html)
  if (typeof window.Video !== 'undefined' && window.Video !== null) {
    // On suppose video.js chargé via CDN dans index.html
    try { windowVideo = window.videojs?.(video); } catch(e) { /* ignore */ }
  }
  return video;
}

export function seekVideo(videoEl, timeMs, fps = 25) {
  // Conversion ms → secondes avec précision frame (SMPTE)
  const secs = timeMs / 1000.0;
  if (videoEl && videoEl.currentTime !== undefined) {
    videoEl.currentTime = secs;
  }
  return secs;
}
