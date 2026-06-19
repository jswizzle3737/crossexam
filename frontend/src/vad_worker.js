// VAD Web Worker — runs energy-threshold detection off the main thread
// Receives Float32Array audio chunks, returns VAD state changes

let vadState = false; // false = silence, true = speech

self.onmessage = async (event) => {
  const { audioBuffer, sampleRate } = event.data;

  // Energy-threshold VAD (Silero-lite WASM would replace this in production)
  const energy = audioBuffer.reduce((sum, s) => sum + Math.abs(s), 0) / audioBuffer.length;
  const threshold = 0.02; // tunable
  const isSpeech = energy > threshold;

  if (isSpeech !== vadState) {
    vadState = isSpeech;
    self.postMessage({ type: 'vad_change', speaking: isSpeech, energy });
  }
};
