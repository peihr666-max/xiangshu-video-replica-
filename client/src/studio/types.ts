import type { CurrentUser, Project } from "../api";

export type StudioPage =
  | "workbench"
  | "viral"
  | "viral-detail"
  | "copy"
  | "replica"
  | "replacement"
  | "video"
  | "reference"
  | "oral"
  | "oral-audio"
  | "tasks"
  | "task-detail"
  | "people"
  | "person-ip"
  | "person-photos"
  | "person-avatars"
  | "person-voices"
  | "materials"
  | "publishing"
  | "analytics"
  | "profile";
export type AssetKind = "image" | "video" | "audio";
export type StudioAsset = {
  id: string;
  name: string;
  kind: AssetKind;
  url?: string;
  poster?: string;
  duration?: string;
  group: string;
  personId?: string;
  composite?: boolean;
  source: string;
  saved: boolean;
};
export type StudioAvatar = {
  id: string;
  name: string;
  imageId: string;
  ready: boolean;
  origin: "视频制作" | "照片制作";
  duration: string;
};
export type StudioVoice = {
  id: string;
  name: string;
  confirmed: boolean;
  isDefault: boolean;
  url?: string;
};
export type StudioPerson = {
  id: string;
  name: string;
  role: string;
  portrait?: string;
  version: number;
  scope: string;
  audience: string;
  expression: string;
  sheetId?: string;
  photoIds: string[];
  avatars: StudioAvatar[];
  voices: StudioVoice[];
};
export type StudioVideo = {
  id: string;
  title: string;
  author: string;
  platform: "抖音" | "视频号";
  category: string;
  poster: string;
  videoUrl?: string;
  duration: string;
  likes: number;
  collections: number;
  shares: number;
  description: string;
};
export type StudioTask = {
  draftSnapshot?: StudioDraft;
  id: string;
  title: string;
  type: "视频复刻" | "人物置换" | "视频生成" | "数字人口播";
  status:
    | "running"
    | "queued"
    | "failed"
    | "completed"
    | "uncertain"
    | "cancelled";
  progress?: number;
  submitted: string;
  poster?: string;
  resultId?: string;
  batchId?: string;
  projectId?: string;
  driverMode?: "text" | "audio";
  ipId?: string;
  avatarId?: string;
  voiceId?: string;
  audioId?: string;
  scriptVersion?: number;
};
export type StudioData = {
  people: StudioPerson[];
  assets: StudioAsset[];
  videos: StudioVideo[];
  tasks: StudioTask[];
  projects: Project[];
  errors: string[];
  loading: boolean;
};
export type StudioScript = {
  id: string;
  title: string;
  original: string;
  text: string;
  version: number;
  confirmed: boolean;
};
export type StudioDraft = {
  id: string;
  ipId?: string;
  sourceId?: string;
  projectId?: string;
  selectedShotId: string;
  originalImageId?: string;
  imageId?: string;
  firstFrameId?: string;
  tailFrameId?: string;
  avatarId?: string;
  voiceId?: string;
  audioId?: string;
  script: StudioScript;
  prompt: string;
  referenceIds: string[];
  resolution: string;
  ratio: string;
  duration: number;
  count: number;
  frameConfirmed: boolean;
  style: "standard" | "template";
  subtitles: boolean;
  quoteRevision: number;
};
export type PickerKind =
  | "person"
  | "image"
  | "original-frame"
  | "first-frame"
  | "tail-frame"
  | "reference"
  | "avatar"
  | "voice"
  | "audio"
  | "avatar-photo";
export type StudioPublishDraft = {
  id: string;
  assetId: string;
  coverId?: string;
  platform: "抖音" | "视频号";
  account: string;
  title: string;
  description: string;
  tags: string[];
};
export type StudioState = {
  page: StudioPage;
  draft: StudioDraft;
  selectedVideoId?: string;
  selectedTaskId?: string;
  selectedAssetId?: string;
  returnTo?: StudioPage;
  selectedPersonId?: string;
  savedScripts: StudioScript[];
  favorites: string[];
  publishDrafts?: StudioPublishDraft[];
};
export type LivePanel =
  | "projects"
  | "characters"
  | "tasks"
  | "profile"
  | "wallet"
  | "analysis";
export type StudioContextValue = {
  state: StudioState;
  data: StudioData;
  review: boolean;
  user: CurrentUser;
  navigate: (page: StudioPage, patch?: Partial<StudioState>) => void;
  patchDraft: (patch: Partial<StudioDraft>) => void;
  patchState: (patch: Partial<StudioState>) => void;
  updateData: (update: (data: StudioData) => StudioData) => void;
  notify: (message: string) => void;
  openPicker: (kind: PickerKind) => void;
  openLive: (panel: LivePanel) => void;
  requestGeneration: (kind: StudioTask["type"]) => void;
  saveDraft: () => void;
  refresh: () => void;
};
