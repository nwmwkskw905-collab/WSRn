export interface VoiceSettings {
  enabled: boolean;
  rate: number;
  pitch: number;
  volume: number;
  voiceName: string;
  lang: string;
  wakeWord: boolean;
}

export const DEFAULT_VOICE: VoiceSettings = {
  enabled: false,
  rate: 1.02,
  pitch: 1,
  volume: 1,
  voiceName: "",
  lang: "pt-BR",
  wakeWord: false,
};

export function listVoices(): SpeechSynthesisVoice[] {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return [];
  return window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("pt"));
}

export function speak(text: string, settings: VoiceSettings): Promise<void> {
  return new Promise((resolve) => {
    if (!settings.enabled || typeof window === "undefined" || !("speechSynthesis" in window)) {
      resolve();
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 4000));
    utterance.lang = settings.lang || "pt-BR";
    utterance.rate = settings.rate;
    utterance.pitch = settings.pitch;
    utterance.volume = settings.volume;
    const voice = listVoices().find((v) => v.name === settings.voiceName);
    if (voice) utterance.voice = voice;
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
  });
}

export function stopSpeaking(): void {
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

type RecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
};

export class SpeechListener {
  private recognition: RecognitionLike | null = null;
  private active = false;

  static supported(): boolean {
    if (typeof window === "undefined") return false;
    const w = window as any;
    return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
  }

  constructor(
    private onTranscript: (text: string, final: boolean) => void,
    private onState: (listening: boolean) => void,
    private onError: (message: string) => void,
  ) {}

  start(wakeWord = false): boolean {
    if (!SpeechListener.supported()) {
      this.onError(
        "Reconhecimento de voz nativo indisponivel neste ambiente. Use o campo de texto ou configure STT local (faster-whisper) na versao empacotada.",
      );
      return false;
    }
    const w = window as any;
    const Recognition = w.SpeechRecognition || w.webkitSpeechRecognition;
    const recognition: RecognitionLike = new Recognition();
    recognition.lang = "pt-BR";
    recognition.continuous = wakeWord;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
      this.active = true;
      this.onState(true);
    };
    recognition.onresult = (event: any) => {
      let text = "";
      let final = false;
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        text += event.results[i][0].transcript;
        if (event.results[i].isFinal) final = true;
      }
      const trimmed = text.trim();
      if (trimmed) this.onTranscript(trimmed, final);
    };
    recognition.onerror = (event: any) => {
      this.onError(
        event.error === "not-allowed"
          ? "Permissao de microfone negada. Libere o microfone nas Configuracoes do Windows."
          : `Erro de voz: ${event.error}. Em Electron sem chave do Google, o reconhecimento web pode ficar indisponivel; use texto ou STT local.`,
      );
    };
    recognition.onend = () => {
      this.active = false;
      this.onState(false);
      if (wakeWord && recognition === this.recognition) {
        // Continuous mode: restart if the user has not stopped it.
        if ((this as any).wanted) {
          try {
            recognition.start();
          } catch {
            /* ignore */
          }
        }
      }
    };
    this.recognition = recognition;
    (this as any).wanted = true;
    try {
      recognition.start();
      return true;
    } catch (error) {
      this.onError(String(error));
      return false;
    }
  }

  stop(): void {
    (this as any).wanted = false;
    this.active = false;
    this.onState(false);
    try {
      this.recognition?.stop();
    } catch {
      /* ignore */
    }
    this.recognition = null;
  }

  get listening(): boolean {
    return this.active;
  }
}

export function extractCommand(transcript: string, wakeWord: boolean): string | null {
  const text = transcript.trim();
  if (!text) return null;
  const match = text.match(/\bjarvis\b[,\s]*(.*)$/i);
  if (match) return (match[1] || "").trim();
  if (!wakeWord) return text;
  return null;
}
