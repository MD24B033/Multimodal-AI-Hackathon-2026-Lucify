"use client";

import { API_BASE, readAccessKey } from "@/lib/api";

export type VoiceEvent =
  | { type: "connected" }
  | { type: "error"; message: string }
  | { type: "closed" }
  | { type: "speech-start" }
  | { type: "speech-end" }
  | { type: "partial"; text: string }
  | { type: "final"; text: string }
  | { type: "level"; rms: number };

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunk, bytes.length)));
  }
  return btoa(binary);
}

/** Streams microphone audio to Sarvam's realtime transcriber through our backend and
 *  reports speech boundaries, so the conversation can run hands-free. */
export class VoiceSession {
  private socket: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
  private listeners = new Set<(event: VoiceEvent) => void>();
  private open = false;

  on(listener: (event: VoiceEvent) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: VoiceEvent) {
    this.listeners.forEach((listener) => listener(event));
  }

  get connected(): boolean {
    return this.open;
  }

  async start(languageCode = "auto"): Promise<void> {
    await this.stop();

    const key = readAccessKey();
    const url = new URL(`${API_BASE.replace(/^http/, "ws")}/api/voice/stream`);
    if (key) url.searchParams.set("access_key", key);
    url.searchParams.set("language_code", languageCode);

    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url.toString());
      this.socket = socket;
      let settled = false;

      socket.onmessage = (event) => {
        let message: { type?: string; message?: string; data?: Record<string, unknown> };
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }

        if (message.type === "connected") {
          this.open = true;
          this.emit({ type: "connected" });
          if (!settled) {
            settled = true;
            resolve();
          }
          return;
        }

        if (message.type === "error") {
          this.emit({ type: "error", message: message.message ?? "Voice error" });
          if (!settled) {
            settled = true;
            reject(new Error(message.message ?? "Voice error"));
          }
          return;
        }

        if (message.type !== "event" || !message.data) return;

        const data = message.data as { event?: string; text?: string };
        switch (data.event) {
          case "vad.speech_start":
            this.emit({ type: "speech-start" });
            break;
          case "vad.speech_end":
            this.emit({ type: "speech-end" });
            break;
          case "transcript.partial":
            this.emit({ type: "partial", text: data.text ?? "" });
            break;
          case "transcript.final":
            this.emit({ type: "final", text: data.text ?? "" });
            break;
          case "error":
            this.emit({ type: "error", message: String(data.text ?? "Sarvam error") });
            break;
          default:
            break;
        }
      };

      socket.onerror = () => {
        if (!settled) {
          settled = true;
          reject(new Error("Could not reach the voice service."));
        }
      };

      socket.onclose = () => {
        this.open = false;
        this.emit({ type: "closed" });
        if (!settled) {
          settled = true;
          reject(new Error("The voice service closed the connection."));
        }
      };
    });

    await this.startMicrophone();
  }

  private async startMicrophone(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });

    const AudioContextClass =
      window.AudioContext ??
      (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) throw new Error("Web Audio is not supported in this browser.");

    this.context = new AudioContextClass({ latencyHint: "interactive" });
    if (this.context.state === "suspended") await this.context.resume();

    await this.context.audioWorklet.addModule("/audio-processor.js");

    this.source = this.context.createMediaStreamSource(this.stream);
    this.worklet = new AudioWorkletNode(this.context, "vox-audio-processor", {
      processorOptions: { targetSampleRate: 16000 },
    });

    // Keep the graph alive without echoing the microphone back to the speakers.
    this.sink = this.context.createGain();
    this.sink.gain.value = 0;

    this.source.connect(this.worklet);
    this.worklet.connect(this.sink);
    this.sink.connect(this.context.destination);

    this.worklet.port.onmessage = (event: MessageEvent) => {
      const data = event.data;
      if (!data) return;
      if (data.type === "audio" && data.buffer) {
        this.sendAudio(data.buffer as ArrayBuffer);
      } else if (data.type === "rms") {
        this.emit({ type: "level", rms: data.rms as number });
      }
    };
  }

  private sendAudio(buffer: ArrayBuffer) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || !this.open) return;
    this.socket.send(JSON.stringify({ type: "audio", audio: toBase64(buffer) }));
  }

  finishTurn() {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "finish" }));
    }
  }

  async stop(): Promise<void> {
    this.open = false;

    if (this.worklet) {
      this.worklet.port.onmessage = null;
      try {
        this.worklet.disconnect();
      } catch {
        /* already detached */
      }
      this.worklet = null;
    }

    for (const node of [this.source, this.sink]) {
      try {
        node?.disconnect();
      } catch {
        /* already detached */
      }
    }
    this.source = null;
    this.sink = null;

    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;

    if (this.context) {
      try {
        await this.context.close();
      } catch {
        /* already closed */
      }
      this.context = null;
    }

    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        /* already closed */
      }
      this.socket = null;
    }
  }
}
