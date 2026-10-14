class VoxAudioProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();

    const processorOptions = options.processorOptions || {};

    this.targetSampleRate = processorOptions.targetSampleRate || 16000;
    this.sourceSampleRate = sampleRate;
    this.resampleRatio = this.sourceSampleRate / this.targetSampleRate;

    this.inputBuffer = [];
    this.outputBuffer = [];
    this.sourcePosition = 0;

    this.chunkSize = Math.round(this.targetSampleRate * 0.02);
    this.rmsAccumulator = 0;
    this.rmsSampleCount = 0;
  }

  pushInputSamples(samples) {
    for (let i = 0; i < samples.length; i++) {
      this.inputBuffer.push(samples[i]);

      const value = samples[i];

      this.rmsAccumulator += value * value;
      this.rmsSampleCount += 1;
    }
  }

  resample() {
    while (true) {
      const nextSourceIndex = this.sourcePosition + this.resampleRatio;
      const flooredIndex = Math.floor(this.sourcePosition);
      const nextFlooredIndex = Math.floor(nextSourceIndex);

      if (nextFlooredIndex + 1 >= this.inputBuffer.length) {
        break;
      }

      const fraction = this.sourcePosition - flooredIndex;
      const sampleA = this.inputBuffer[flooredIndex];
      const sampleB = this.inputBuffer[flooredIndex + 1];
      const interpolated = sampleA + (sampleB - sampleA) * fraction;

      this.outputBuffer.push(interpolated);
      this.sourcePosition = nextSourceIndex;
    }

    const consumed = Math.floor(this.sourcePosition);

    if (consumed > 0) {
      this.inputBuffer = this.inputBuffer.slice(consumed);
      this.sourcePosition -= consumed;
    }
  }

  flushChunks() {
    while (this.outputBuffer.length >= this.chunkSize) {
      const chunk = this.outputBuffer.slice(0, this.chunkSize);

      this.outputBuffer = this.outputBuffer.slice(this.chunkSize);

      const pcm16 = new Int16Array(chunk.length);

      for (let i = 0; i < chunk.length; i++) {
        const clamped = Math.max(-1, Math.min(1, chunk[i]));

        pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      }

      this.port.postMessage(
        { type: "audio", buffer: pcm16.buffer },
        [pcm16.buffer]
      );
    }

    if (this.rmsSampleCount > 0) {
      const rms = Math.sqrt(this.rmsAccumulator / this.rmsSampleCount);

      this.port.postMessage({ type: "rms", rms });

      this.rmsAccumulator = 0;
      this.rmsSampleCount = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];

    if (!input || !input[0]) {
      return true;
    }

    this.pushInputSamples(input[0]);
    this.resample();
    this.flushChunks();

    return true;
  }
}

registerProcessor("vox-audio-processor", VoxAudioProcessor);