import type { AppInfo } from "../../shared/contracts";
import type { VoiceSettings } from "../lib/voice";

export interface PageProps {
  status: any;
  refreshStatus: () => void;
  voice: VoiceSettings;
  setVoice: (value: VoiceSettings) => void;
  navigate: (id: string) => void;
  info: AppInfo | null;
}
