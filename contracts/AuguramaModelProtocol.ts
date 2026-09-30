/**
 * Augurama Model Protocol & Scene Interface Definitions
 * Defines the contract for modular video generation adapters.
 */

export interface AuguramaShot {
  start: number;
  end: number;
  action: string;
  camera?: string;
  sound?: string;
}

export interface AuguramaAudio {
  enabled: boolean;
  dialogue?: string[];
  ambience?: string;
  music?: string;
}

export interface AuguramaReference {
  assetId: string;
  role: "identity" | "environment" | "style" | "object" | "motion" | "camera" | "audio" | "first_frame" | "last_frame";
  direction?: string;
  url?: string;
}

export interface AuguramaScene {
  title: string;
  direction: string;
  durationSeconds: number;
  aspectRatio: "9:16" | "16:9" | "1:1" | "4:3" | "3:4" | "21:9";
  resolution: "480p" | "720p" | "768p" | "1080p" | "4k";
  shots?: AuguramaShot[];
  references?: AuguramaReference[];
  audio?: AuguramaAudio;
  seed?: number | null;
  watermark?: boolean;
  promptExpansion?: "balanced" | "quality" | "none";
  thinkingMode?: boolean;
}

export interface AuguramaCostEstimate {
  currency: "USD";
  approximateUsd: number;
  ratePerSecond?: number;
  ratePerMillionTokens?: number;
  pricingSnapshot: string;
  notice: string;
}

export interface AuguramaGenerationResult {
  providerTaskId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  model: string;
  videoUrl?: string;
  lastFrameUrl?: string;
  error?: string;
  usage?: Record<string, any>;
}

export interface AuguramaModelProtocol {
  modelId: string;
  displayName: string;
  supportsNativeAudio: boolean;
  maxDurationSeconds: number;
  supportedResolutions: string[];
  compilePayload(scene: AuguramaScene): Record<string, any>;
  estimateCost(durationSec: number, resolution: string): number;
  execute(payload: Record<string, any>): Promise<AuguramaGenerationResult>;
}
