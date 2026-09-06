import { type ReactNode, useRef, useState } from "react";
import {
  completeMaterialUpload,
  createMaterialUploadIntent,
  uploadMaterial,
} from "../api";
import { CreationNavigation } from "./CreationNavigation";
import { useStudio } from "./context";
import { studioAssetFromMaterial } from "./live";
import type { StudioAsset, StudioPerson, StudioVideo } from "./types";
import {
  Button,
  Empty,
  Field,
  Hint,
  Icon,
  Media,
  Panel,
  Tabs,
  Waveform,
} from "./ui";
import "./creation.css";

function findAsset(assets: StudioAsset[], id?: string) {
  return id ? assets.find((asset) => asset.id === id) : undefined;
}

function findSource(
  assets: StudioAsset[],
  videos: StudioVideo[],
  id?: string,
): StudioAsset | undefined {
  const asset = findAsset(assets, id);
  if (asset) return asset;
  const video = id ? videos.find((item) => item.id === id) : undefined;
  return video
    ? {
        id: video.id,
        name: video.title,
        kind: "video",
        poster: video.poster,
        duration: video.duration,
        group: video.category,
        source: video.platform,
        saved: true,
      }
    : undefined;
}

function activePerson(
  people: StudioPerson[],
  selectedId?: string,
): StudioPerson | undefined {
  return selectedId
    ? people.find((person) => person.id === selectedId)
    : undefined;
}

function SourceStrip({ source }: { source?: StudioAsset }) {
  return (
    <div className="creation-source-strip">
      <span className="creation-status-dot" />
      <span>
        来源：
        {source ? `${source.name} · ${source.source}` : "尚未选择来源视频"}
      </span>
    </div>
  );
}

function ControlGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="studio-field">
      <span>{label}</span>
      {children}
    </div>
  );
}

export function CopyPage() {
  const {
    state,
    data,
    patchDraft,
    navigate,
    saveDraft,
    confirmFinalDraft,
    openLive,
    openPicker,
  } = useStudio();
  const [tab, setTab] = useState<"rewrite" | "saved">("rewrite");
  const source = findSource(
    data.assets,
    data.videos,
    state.draft.sourceId ?? state.selectedVideoId,
  );
  const person = activePerson(data.people, state.draft.ipId);
  const saved = state.savedScripts;

  return (
    <section className="creation-page creation-copy">
      <header className="creation-heading">
        <h1>文案工坊</h1>
        <p>提取与二创文案，优化表达，匹配乡墅场景</p>
      </header>
      <Tabs
        items={[
          { id: "rewrite", label: "文案改写" },
          { id: "saved", label: "我的文案" },
        ]}
        value={tab}
        onChange={(value) => setTab(value as "rewrite" | "saved")}
      />

      {tab === "saved" ? (
        <Panel className="creation-saved-list">
          {saved.length ? (
            saved.map((script) => (
              <button
                className="creation-script-row"
                key={script.id}
                onClick={() => patchDraft({ script })}
                type="button"
              >
                <span>{script.title}</span>
                <small>
                  {script.confirmed ? "已确认" : "草稿"} · V{script.version}
                </small>
              </button>
            ))
          ) : (
            <Empty
              title="还没有保存的文案"
              description="完成二创后保存版本，文案会集中显示在这里。"
            />
          )}
        </Panel>
      ) : (
        <>
          <SourceStrip source={source} />
          <div className="creation-copy-grid">
            <Panel className="creation-copy-source">
              <div className="creation-panel-title">原文（提取自来源）</div>
              {state.draft.script.original ? (
                <div className="creation-script-copy">
                  {state.draft.script.original}
                </div>
              ) : (
                <Empty
                  title="尚未提取文案"
                  description="可先从爆款视频或视频来源进入文案工坊。"
                  action={
                    <Button
                      variant="outline"
                      onClick={() => openLive("analysis")}
                    >
                      打开来源分析
                    </Button>
                  }
                />
              )}
            </Panel>
            <Panel className="creation-copy-editor">
              <div className="creation-panel-title-row">
                <span>二创文案（可编辑）</span>
                <small>
                  {state.draft.script.confirmed ? "终稿" : "草稿"} V
                  {state.draft.script.version}
                </small>
              </div>
              <input
                aria-label="作品名称"
                className="creation-input"
                onChange={(event) =>
                  patchDraft({
                    script: {
                      ...state.draft.script,
                      title: event.target.value,
                      confirmed: false,
                    },
                  })
                }
                placeholder="作品名称"
                value={state.draft.script.title}
              />
              <textarea
                aria-label="二创文案"
                className="creation-textarea creation-copy-textarea"
                onChange={(event) =>
                  patchDraft({
                    script: {
                      ...state.draft.script,
                      text: event.target.value,
                      confirmed: false,
                    },
                  })
                }
                placeholder="在这里编辑乡墅口播文案"
                value={state.draft.script.text}
              />
              <div className="creation-saved-state">
                内容变动后需重新确认终稿
              </div>
            </Panel>
            <Panel className="creation-copy-person">
              <div className="creation-panel-title">IP 选择</div>
              {person ? (
                <div className="creation-person-card">
                  <Media
                    asset={
                      person.portrait
                        ? {
                            id: person.id,
                            name: person.name,
                            kind: "image",
                            url: person.portrait,
                            group: "人物",
                            source: "人物库",
                            saved: true,
                          }
                        : undefined
                    }
                    alt={person.name}
                    className="creation-avatar"
                  />
                  <div>
                    <strong>
                      {person.name} · {person.role}
                    </strong>
                    <p>{person.scope}</p>
                    <small>{person.expression}</small>
                  </div>
                </div>
              ) : (
                <Empty
                  title="未选择人物 IP"
                  description="二创时可带入人物定位与表达方式。"
                />
              )}
              <Button variant="outline" onClick={() => openLive("analysis")}>
                按 IP 二创
              </Button>
              <Button variant="outline" onClick={() => openPicker("person")}>
                更换人物
              </Button>
              <Button
                variant="quiet"
                onClick={confirmFinalDraft}
                disabled={!state.draft.script.text.trim()}
              >
                确认终稿
              </Button>
            </Panel>
          </div>
          <footer className="creation-action-bar">
            <Button variant="outline" onClick={saveDraft}>
              保存版本
            </Button>
            <Button
              variant="primary"
              disabled={!state.draft.script.confirmed || !state.draft.ipId}
              onClick={() => navigate("oral", { returnTo: "copy" })}
            >
              用于数字人口播
            </Button>
          </footer>
        </>
      )}
    </section>
  );
}

export function ReplicaPage() {
  const { state, data, review, patchDraft, openLive, openPicker, saveDraft } =
    useStudio();
  const source = findSource(
    data.assets,
    data.videos,
    state.draft.sourceId ?? state.selectedVideoId,
  );
  const original = findAsset(data.assets, state.draft.originalImageId);
  const selectedTarget = findAsset(data.assets, state.draft.firstFrameId);
  const target =
    review && selectedTarget?.personId !== state.draft.ipId
      ? (data.assets.find(
          (asset) =>
            asset.kind === "image" &&
            asset.personId === state.draft.ipId &&
            !asset.composite,
        ) ?? selectedTarget)
      : selectedTarget;
  const person = activePerson(data.people, state.draft.ipId);
  const reviewShots = [
    {
      id: "shot-1",
      title: "院落推进",
      time: "00:00–00:08",
      asset:
        data.assets.find(
          (asset) => asset.kind === "image" && !asset.personId,
        ) ?? source,
    },
    {
      id: "shot-2",
      title: "人物讲解",
      time: "00:08–00:16",
      asset: original ?? source,
    },
    {
      id: "shot-3",
      title: "外立面特写",
      time: "00:16–00:24",
      asset:
        data.assets.find(
          (asset) =>
            asset.kind === "video" &&
            !asset.personId &&
            asset.id !== source?.id,
        ) ?? source,
    },
  ];
  const shots = review
    ? reviewShots
    : [
        {
          id: state.draft.selectedShotId || "待选择镜头",
          title: "当前镜头",
          time: "",
          asset: original ?? source,
        },
      ];

  return (
    <section className="creation-page creation-replica">
      <header className="creation-heading">
        <h1>视频复刻</h1>
      </header>
      <CreationNavigation />
      <SourceStrip source={source} />
      {!source ? (
        <Panel className="creation-empty-workspace">
          <Empty
            title="先导入参考视频"
            description="当前链接解析尚未接通，可上传本地视频后进入成熟分镜工作区。"
            action={
              <Button variant="primary" onClick={() => openPicker("reference")}>
                上传参考视频
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="creation-replica-grid">
          <Panel className="creation-shot-list">
            <div className="creation-panel-title">
              分镜（共 {shots.length} 个）
            </div>
            {shots.map((shot, index) => (
              <button
                className={`creation-shot ${state.draft.selectedShotId === shot.id ? "active" : ""}`}
                key={shot.id}
                onClick={() => patchDraft({ selectedShotId: shot.id })}
                type="button"
              >
                <Media asset={shot.asset} alt={`镜头 ${index + 1}`} />
                <span>
                  <strong>
                    {String(index + 1).padStart(2, "0")} · {shot.title}
                  </strong>
                  <small>{shot.time || "已从成熟分镜工作区带入"}</small>
                </span>
              </button>
            ))}
          </Panel>
          <Panel className="creation-frame-compare">
            <div className="creation-panel-title-row">
              <span>镜头 {state.draft.selectedShotId} · 首帧确认</span>
              <small>已确认</small>
            </div>
            <div className="creation-frame-stack">
              <div>
                <span>原视频首帧</span>
                <Media
                  asset={original ?? source}
                  alt="原视频首帧"
                  className="creation-frame-source"
                />
              </div>
              <Icon name="down" />
              <div className="creation-frame-target">
                <span>目标首帧</span>
                <Media asset={target} alt="目标首帧" />
              </div>
            </div>
          </Panel>
          <Panel className="creation-shot-notes">
            <div className="creation-panel-title-row">
              <span>镜头描述</span>
              <Button variant="outline" onClick={() => openLive("analysis")}>
                调整人物首帧
              </Button>
            </div>
            <p>
              {state.draft.prompt || "进入分镜工作区后查看和调整镜头提示。"}
            </p>
            {person && (
              <div className="creation-shot-person">
                <Media
                  asset={target}
                  alt={person.name}
                  className="creation-avatar"
                />
                <span>
                  <strong>{person.name}</strong>
                  <small>{person.role}</small>
                </span>
              </div>
            )}
          </Panel>
        </div>
      )}
      <footer className="creation-action-bar">
        <div>
          <strong>复刻任务使用现有分镜、首帧与生成批次能力</strong>
          <Hint>进入成熟工作区后再确认费用并提交。</Hint>
        </div>
        <Button variant="outline" onClick={saveDraft}>
          保存草稿
        </Button>
        <Button variant="primary" onClick={() => openLive("analysis")}>
          进入分镜工作区
        </Button>
      </footer>
    </section>
  );
}

export function ReplacementPage() {
  const { state, data, openPicker, navigate, saveDraft, requestGeneration } =
    useStudio();
  const original = findAsset(data.assets, state.draft.originalImageId);
  const target = findAsset(data.assets, state.draft.imageId);
  const preview = state.draft.frameConfirmed
    ? (findAsset(data.assets, state.draft.firstFrameId) ?? target)
    : undefined;

  return (
    <section className="creation-page">
      <header className="creation-heading creation-heading-back">
        <Button
          variant="quiet"
          onClick={() => navigate(state.returnTo ?? "replica")}
        >
          ← 返回
        </Button>
        <div>
          <h1>人物置换</h1>
          <p>先确认人物首帧，再继续生成视频</p>
        </div>
      </header>
      <CreationNavigation />
      <SourceStrip source={original} />
      <div className="creation-replacement-grid">
        <Panel>
          <div className="creation-panel-title">原始画面</div>
          <Media
            asset={original}
            alt="原始画面"
            className="creation-large-media"
          />
          <Button
            variant="outline"
            onClick={() => openPicker("original-frame")}
          >
            更换原始画面
          </Button>
        </Panel>
        <Panel>
          <div className="creation-panel-title">目标人物参考</div>
          <Media
            asset={target}
            alt="目标人物参考"
            className="creation-large-media"
          />
          <Button variant="outline" onClick={() => openPicker("image")}>
            从人物库选择
          </Button>
          <Hint>人物照片只填目标参考，不会覆盖原始画面。</Hint>
        </Panel>
        <Panel className="creation-replacement-preview">
          <div className="creation-panel-title">置换首帧预览</div>
          <Media
            asset={preview}
            alt="置换首帧预览"
            className="creation-large-media"
          />
          <div className="creation-preview-state">
            <span className="creation-status-dot" />
            {state.draft.frameConfirmed ? "静态首帧 · 已确认" : "待生成并确认"}
          </div>
        </Panel>
      </div>
      <footer className="creation-action-bar creation-action-center">
        <Button variant="outline" onClick={() => requestGeneration("人物置换")}>
          重新生成首帧
        </Button>
        <Button
          variant="primary"
          disabled={!preview}
          onClick={() => {
            saveDraft();
            navigate(state.returnTo ?? "replica");
          }}
        >
          确认并返回镜头
        </Button>
        <Button
          variant="outline"
          disabled={!preview}
          onClick={() => navigate("video", { returnTo: "replacement" })}
        >
          用于文/图生视频
        </Button>
      </footer>
    </section>
  );
}

const ratios = ["自动", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"];
const assetKindNames: Record<StudioAsset["kind"], string> = {
  image: "图片",
  video: "视频",
  audio: "音频",
};

function ParameterControls() {
  const { state, patchDraft } = useStudio();
  const draft = state.draft;
  return (
    <div className="creation-parameters">
      <ControlGroup label="分辨率">
        <div className="creation-segmented">
          {["768P", "2K"].map((resolution) => (
            <button
              className={draft.resolution === resolution ? "active" : ""}
              key={resolution}
              onClick={() => patchDraft({ resolution })}
              type="button"
            >
              {resolution}
            </button>
          ))}
        </div>
      </ControlGroup>
      <ControlGroup label={`时长 ${draft.duration} 秒`}>
        <input
          aria-label="时长"
          max={15}
          min={4}
          onChange={(event) =>
            patchDraft({ duration: Number(event.target.value) })
          }
          type="range"
          value={draft.duration}
        />
      </ControlGroup>
      <ControlGroup label="画面比例">
        <div className="creation-ratios">
          {ratios.map((ratio) => (
            <button
              className={draft.ratio === ratio ? "active" : ""}
              key={ratio}
              onClick={() => patchDraft({ ratio })}
              type="button"
            >
              {ratio}
            </button>
          ))}
        </div>
      </ControlGroup>
      <ControlGroup label="生成数量">
        <div className="creation-segmented">
          {[1, 2, 4].map((count) => (
            <button
              className={draft.count === count ? "active" : ""}
              key={count}
              onClick={() => patchDraft({ count })}
              type="button"
            >
              {count}个
            </button>
          ))}
        </div>
      </ControlGroup>
    </div>
  );
}

export function VideoPage() {
  const {
    state,
    data,
    patchDraft,
    navigate,
    openPicker,
    saveDraft,
    requestGeneration,
  } = useStudio();
  const referenceMode = state.page === "reference";
  const firstFrame = findAsset(data.assets, state.draft.firstFrameId);
  const tailFrame = findAsset(data.assets, state.draft.tailFrameId);
  const references = state.draft.referenceIds
    .map((id) => findAsset(data.assets, id))
    .filter((asset): asset is StudioAsset => Boolean(asset));
  const ready =
    Boolean(state.draft.prompt.trim()) &&
    (referenceMode ? references.length > 0 : true);

  return (
    <section className="creation-page">
      <header className="creation-heading">
        <h1>{referenceMode ? "视频生成-参考生视频" : "视频生成-文图生视频"}</h1>
      </header>
      <CreationNavigation />
      <Tabs
        items={[
          { id: "video", label: "文/图生视频" },
          { id: "reference", label: "参考生视频" },
        ]}
        value={referenceMode ? "reference" : "video"}
        onChange={(value) =>
          navigate(value === "reference" ? "reference" : "video")
        }
      />
      <div
        className={`creation-video-grid ${referenceMode ? "reference" : ""}`}
      >
        <Panel className="creation-video-form">
          <Field label="提示词">
            <textarea
              aria-label="提示词"
              className="creation-textarea"
              onChange={(event) => patchDraft({ prompt: event.target.value })}
              placeholder="描述镜头、场景、运动与光线"
              value={state.draft.prompt}
            />
          </Field>
          {referenceMode ? (
            <ControlGroup label="参考素材">
              <button
                className="creation-upload"
                onClick={() => openPicker("reference")}
                type="button"
              >
                <Icon name="upload" />
                <span>点击上传，或从素材库选择</span>
                <small>支持图片、视频、音频</small>
              </button>
              <div className="creation-reference-list">
                {references.map((asset, index) => (
                  <div className="creation-reference-row" key={asset.id}>
                    <Media asset={asset} alt={asset.name} />
                    <span className="creation-reference-copy">
                      <strong>
                        @{index + 1} {asset.name}
                      </strong>
                      <small>
                        {assetKindNames[asset.kind]} · {asset.source}
                      </small>
                    </span>
                    <Button
                      aria-label={`移除 ${asset.name}`}
                      className="creation-reference-remove"
                      onClick={() =>
                        patchDraft({
                          referenceIds: state.draft.referenceIds.filter(
                            (id) => id !== asset.id,
                          ),
                        })
                      }
                      variant="quiet"
                    >
                      <Icon name="close" size={18} />
                    </Button>
                  </div>
                ))}
              </div>
            </ControlGroup>
          ) : (
            <ControlGroup label="首尾帧">
              <Hint>无首帧时文生视频；添加首帧后图生视频。</Hint>
              <div className="creation-frame-row">
                <button onClick={() => openPicker("first-frame")} type="button">
                  <Media asset={firstFrame} alt="首帧" />
                  <span>首帧（选填）</span>
                </button>
                <Icon name="arrow" />
                <button onClick={() => openPicker("tail-frame")} type="button">
                  <Media asset={tailFrame} alt="尾帧" />
                  <span>尾帧（可选）</span>
                </button>
              </div>
            </ControlGroup>
          )}
        </Panel>
        <Panel className="creation-video-controls">
          <div className="creation-panel-title">参数设置</div>
          <ParameterControls />
          <div className="creation-form-actions">
            <Button variant="outline" onClick={saveDraft}>
              保存草稿
            </Button>
            <Button
              variant="primary"
              disabled={!ready}
              onClick={() => requestGeneration("视频生成")}
            >
              生成视频
            </Button>
          </div>
          <Hint>提交前确认费用；生成结果进入任务中心。</Hint>
        </Panel>
        <Panel className="creation-video-preview">
          <div className="creation-panel-title">
            预览（{referenceMode ? "参考画布" : "首帧预览"}）
          </div>
          {referenceMode ? (
            references.length ? (
              <Media
                asset={references[0]}
                alt="参考画布"
                className="creation-preview-media"
              />
            ) : (
              <Empty
                title="还没有参考素材"
                description="设置参考素材与参数后再生成视频。"
              />
            )
          ) : firstFrame ? (
            <Media
              asset={firstFrame}
              alt="首帧预览"
              className="creation-preview-media"
            />
          ) : (
            <Empty
              title="当前为文生视频"
              description="添加首帧后会在这里显示图生预览。"
            />
          )}
        </Panel>
      </div>
    </section>
  );
}

function PersonIdentity({ person }: { person?: StudioPerson }) {
  const { openPicker } = useStudio();
  return (
    <div className="creation-identity-row">
      <span>人物 IP</span>
      <strong>{person ? `${person.name} · ${person.role}` : "未选择"}</strong>
      <Button variant="outline" onClick={() => openPicker("person")}>
        更换 IP
      </Button>
    </div>
  );
}

function avatarDisplayName(person: StudioPerson | undefined, name: string) {
  if (!person || name.startsWith(person.name)) return name;
  return `${person.name} · ${name}`;
}

export function OralPage() {
  const {
    state,
    data,
    patchDraft,
    updateData,
    navigate,
    openPicker,
    saveDraft,
    requestGeneration,
    notify,
    review,
  } = useStudio();
  const audioUploadInputRef = useRef<HTMLInputElement>(null);
  const [audioUploadProgress, setAudioUploadProgress] = useState<number>();
  const audioMode = state.page === "oral-audio";
  const person = activePerson(data.people, state.draft.ipId);
  const avatar = person?.avatars.find(
    (item) => item.id === state.draft.avatarId && item.ready,
  );
  const voice = person?.voices.find(
    (item) => item.id === state.draft.voiceId && item.confirmed,
  );
  const audio = findAsset(data.assets, state.draft.audioId);
  const speechAudio = audio?.kind === "audio" ? audio : undefined;
  const avatarImage = findAsset(data.assets, avatar?.imageId);
  const ready = audioMode
    ? Boolean(person && avatar && speechAudio)
    : Boolean(
        person &&
          avatar &&
          voice &&
          state.draft.script.confirmed &&
          state.draft.script.text.trim(),
      );

  const uploadSpeechAudio = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".mp3")) {
      notify("仅支持 MP3 口播音频");
      return;
    }
    setAudioUploadProgress(0);
    try {
      const intent = await createMaterialUploadIntent(file, {
        title: file.name,
        group: "完整口播音频",
      });
      await uploadMaterial(intent, file, setAudioUploadProgress);
      const completed = await completeMaterialUpload(intent.asset_id);
      const uploaded = studioAssetFromMaterial(completed);
      updateData((current) => ({
        ...current,
        assets: [
          uploaded,
          ...current.assets.filter((item) => item.id !== uploaded.id),
        ],
      }));
      patchDraft({ audioId: uploaded.id, voiceId: undefined });
      notify(`音频“${uploaded.name}”已上传并永久保存`);
    } catch (error) {
      notify(error instanceof Error ? error.message : "上传口播音频失败");
    } finally {
      setAudioUploadProgress(undefined);
      if (audioUploadInputRef.current) audioUploadInputRef.current.value = "";
    }
  };

  return (
    <section className="creation-page creation-oral">
      <header className="creation-heading creation-heading-back">
        <Button
          variant="quiet"
          onClick={() => navigate(state.returnTo ?? "workbench")}
        >
          ← 返回
        </Button>
        <div>
          <h1>{audioMode ? "数字人口播 - 用已有音频生成" : "数字人口播"}</h1>
        </div>
      </header>
      <CreationNavigation />
      <div className="creation-oral-grid">
        <div className="creation-oral-left">
          <Tabs
            items={[
              { id: "oral", label: "用文案生成" },
              { id: "oral-audio", label: "用已有音频生成" },
            ]}
            value={audioMode ? "oral-audio" : "oral"}
            onChange={(value) =>
              navigate(value === "oral-audio" ? "oral-audio" : "oral")
            }
          />
          <Panel className="creation-oral-inputs">
            {audioMode ? (
              <ControlGroup label="口播音频">
                {speechAudio ? (
                  <div className="creation-audio-card">
                    <div className="creation-audio-title">
                      <Icon name="audio" />
                      <span>
                        <strong>{speechAudio.name}</strong>
                        <small>
                          {speechAudio.source} ·{" "}
                          {speechAudio.duration ?? "时长未知"}
                        </small>
                      </span>
                    </div>
                    <Waveform />
                  </div>
                ) : (
                  <Empty
                    title="未选择完整口播音频"
                    description="使用录音原声直接驱动口型。"
                  />
                )}
                <div className="creation-inline-actions">
                  <Button variant="outline" onClick={() => openPicker("audio")}>
                    从素材库选择
                  </Button>
                  <input
                    accept=".mp3,audio/mpeg"
                    aria-label="选择口播音频"
                    hidden
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void uploadSpeechAudio(file);
                    }}
                    ref={audioUploadInputRef}
                    type="file"
                  />
                  <Button
                    disabled={audioUploadProgress !== undefined}
                    variant="outline"
                    onClick={() => {
                      if (review) {
                        notify("审核模式不执行真实上传");
                        return;
                      }
                      audioUploadInputRef.current?.click();
                    }}
                  >
                    {audioUploadProgress === undefined
                      ? "上传音频"
                      : `上传中 ${audioUploadProgress}%`}
                  </Button>
                </div>
                <Hint>使用音频中的原声直接驱动口型，无需另选克隆声音。</Hint>
              </ControlGroup>
            ) : (
              <>
                <ControlGroup label="口播文案">
                  <div className="creation-readonly-script">
                    <div>
                      <span>来源：文案工坊</span>
                      <strong>
                        {state.draft.script.confirmed ? "终稿" : "待确认"} V
                        {state.draft.script.version}
                      </strong>
                    </div>
                    <h3>{state.draft.script.title || "未命名作品"}</h3>
                    <p>{state.draft.script.text || "尚未带入已确认终稿。"}</p>
                    <button
                      onClick={() => navigate("copy", { returnTo: "oral" })}
                      type="button"
                    >
                      去文案工坊修改
                    </button>
                  </div>
                </ControlGroup>
                <ControlGroup label="声音">
                  <div className="creation-voice-row">
                    <span>{voice?.name ?? "未选择已确认声音"}</span>
                    <small>{voice ? "已就绪" : "需在人物库试听确认"}</small>
                    <Button
                      variant="outline"
                      onClick={() => openPicker("voice")}
                    >
                      更换
                    </Button>
                  </div>
                  <button
                    className="creation-text-link"
                    onClick={() =>
                      navigate("person-voices", {
                        returnTo: state.page,
                        selectedPersonId: state.draft.ipId,
                      })
                    }
                    type="button"
                  >
                    管理声音
                  </button>
                </ControlGroup>
              </>
            )}
          </Panel>
        </div>
        <Panel className="creation-oral-avatar">
          <PersonIdentity person={person} />
          <div className="creation-panel-title-row">
            <span>口播分身{audioMode ? "预览" : ""}</span>
            <Button variant="outline" onClick={() => openPicker("avatar")}>
              更换分身
            </Button>
          </div>
          {avatar ? (
            <>
              <Media
                asset={avatarImage}
                alt={avatar.name}
                className="creation-avatar-preview"
              />
              <div className="creation-avatar-meta">
                <strong>{avatarDisplayName(person, avatar.name)}</strong>
                <small>已就绪 · 来源：人物库</small>
              </div>
              <button
                className="creation-text-link"
                onClick={() =>
                  navigate("person-avatars", {
                    returnTo: state.page,
                    selectedPersonId: state.draft.ipId,
                  })
                }
                type="button"
              >
                去人物库管理口播分身
              </button>
            </>
          ) : (
            <Empty
              title="还没有可用口播分身"
              description="请先在当前人物下制作并完成分身。"
              action={
                <Button
                  variant="outline"
                  onClick={() =>
                    navigate("person-avatars", {
                      returnTo: state.page,
                      selectedPersonId: state.draft.ipId,
                    })
                  }
                >
                  去人物库制作口播分身
                </Button>
              }
            />
          )}
        </Panel>
      </div>
      <footer className="creation-action-bar">
        {!audioMode && (
          <div className="creation-style-controls">
            <span>成片样式</span>
            <Button
              variant={state.draft.style === "standard" ? "outline" : "quiet"}
              onClick={() => patchDraft({ style: "standard" })}
            >
              标准口播
            </Button>
            <Button
              variant={state.draft.style === "template" ? "outline" : "quiet"}
              onClick={() => patchDraft({ style: "template" })}
            >
              网感模板
            </Button>
            {state.draft.style === "standard" && (
              <>
                <span>字幕</span>
                <Button
                  variant={!state.draft.subtitles ? "outline" : "quiet"}
                  onClick={() => patchDraft({ subtitles: false })}
                >
                  不添加
                </Button>
                <Button
                  variant={state.draft.subtitles ? "outline" : "quiet"}
                  onClick={() => patchDraft({ subtitles: true })}
                >
                  添加
                </Button>
              </>
            )}
          </div>
        )}
        <Button variant="outline" onClick={saveDraft}>
          保存草稿
        </Button>
        <Button
          variant="primary"
          disabled={!ready}
          onClick={() => requestGeneration("数字人口播")}
        >
          生成口播视频
        </Button>
      </footer>
      <Hint>
        确认费用后提交；数字人服务未配置时会明确提示，不会生成伪造成片。
      </Hint>
    </section>
  );
}
