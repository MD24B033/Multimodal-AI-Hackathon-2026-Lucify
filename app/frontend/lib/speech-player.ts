"use client";

export type PlayerEvent =
  | { type: "started" }
  | { type: "ended" }
  | { type: "stopped" }
  | { type: "error"; message: string };

/** Plays the tutor's synthesised reply and exposes a live amplitude so the
 *  interface can react to the voice instead of animating on a timer. */
export class SpeechPlayer {
  private context: AudioContext | null = null;
  private source: AudioBufferSourceNode | null = null;
  private analyser: AnalyserNode | null = null;
  private samples: Uint8Array<ArrayBuffer> | null = null;
  private listeners = new Set<(event: PlayerEvent) => void>();
  private active = false;
  private settle: (() => void) | null = null;

  on(listener: (event: PlayerEvent) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: PlayerEvent) {
    this.listeners.forEach((listener) => listener(event));
  }

  get playing(): boolean {
    return this.active;
  }

  level(): number {
    if (!this.analyser || !this.samples || !this.active) return 0;
    this.analyser.getByteTimeDomainData(this.samples);
    let sum = 0;
    for (let i = 0; i < this.samples.length; i += 1) {
      const deviation = (this.samples[i] - 128) / 128;
      sum += deviation * deviation;
    }
    return Math.sqrt(sum / this.samples.length);
  }

  async play(audio: ArrayBuffer): Promise<void> {
    this.stop();

    const AudioContextClass =
      window.AudioContext ??
      (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) {
      this.emit({ type: "error", message: "Web Audio is not supported in this browser." });
      return;
    }

    this.context ??= new AudioContextClass();
    if (this.context.state === "suspended") await this.context.resume();

    let buffer: AudioBuffer;
    try {
      buffer = await this.context.decodeAudioData(audio.slice(0));
    } catch {
      this.emit({ type: "error", message: "That audio could not be decoded." });
      return;
    }

    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    this.samples = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser);
    this.analyser.connect(this.context.destination);

    this.source = source;
    this.active = true;
    this.emit({ type: "started" });

    await new Promise<void>((resolve) => {
      this.settle = resolve;
      source.onended = () => {
        if (this.source === source) {
          this.active = false;
          this.source = null;
          this.emit({ type: "ended" });
        }
        this.settle = null;
        resolve();
      };
      source.start();
    });
  }

  stop(): void {
    const source = this.source;
    const settle = this.settle;
    this.source = null;
    this.settle = null;
    this.active = false;

    if (source) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        /* already finished */
      }
      try {
        source.disconnect();
      } catch {
        /* already detached */
      }
      this.emit({ type: "stopped" });
    }

    settle?.();
  }

  async dispose(): Promise<void> {
    this.stop();
    this.analyser = null;
    this.samples = null;
    if (this.context) {
      try {
        await this.context.close();
      } catch {
        /* already closed */
      }
      this.context = null;
    }
  }
}
