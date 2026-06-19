/**
 * VAD Manager — connects microphone stream to Web Worker, emits events.
 * Sends barge-in interrupt signals over the WebRTC data channel.
 */
export class VADManager {
  constructor(dataChannel) {
    this.dataChannel = dataChannel;
    this.worker = new Worker('./vad_worker.js');
    this.listening = false;

    this.worker.onmessage = (event) => {
      if (event.data.type === 'vad_change' && event.data.speaking) {
        // Barge-in detected — send interrupt signal over data channel
        if (this.dataChannel?.readyState === 'open') {
          this.dataChannel.send(JSON.stringify({ type: 'interrupt' }));
        }
      }
    };
  }

  async start(stream) {
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (event) => {
      if (!this.listening) return;
      const input = event.inputBuffer.getChannelData(0);
      this.worker.postMessage({ audioBuffer: input, sampleRate: audioContext.sampleRate });
    };

    source.connect(processor);
    processor.connect(audioContext.destination);
    this.listening = true;
  }

  stop() {
    this.listening = false;
  }
}
