import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  customerVisibleErrorMessage,
  type GenerationRatio,
  getLatestProjectAnalysis,
  getLatestProjectFirstFrameSelection,
  getLatestProjectShotCards,
  listUserSavedPrompts,
  readAnalysisPayload,
  readFirstFrameSelectionPayload,
  type SavedPromptItem,
  type ShotCard,
  type ShotCardPayload,
  saveGenerationPrompt,
  startVideoAnalysis,
  waitForAnalysisTask,
} from "../api";
import { CreationNavigation } from "./CreationNavigation";
import { useStudio } from "./context";
import {
  runReplicaGeneration,
  uploadVideoMaterial,
  uploadWorkbenchSourceVideo,
} from "./live";
import { buildReplicaPromptText, SUPPORTED_VIDEO_RATIOS } from "./state";
import type {
  StudioAsset,
  StudioPerson,
  StudioTask,
  StudioVideo,
} from "./types";
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

type ReplicaStage = "source" | "analyzing" | "ready";

export function ReplicaPage() {
  const {
    state,
    data,
    review,
    patchDraft,
    navigate,
    notify,
    saveDraft,
    openLive,
  } = useStudio();
  const project = data.projects.find(
    (item) => item.id === state.draft.projectId,
  );
  const source = findSource(
    data.assets,
    data.videos,
    state.draft.sourceId ?? state.selectedVideoId,
  );
  const [stage, setStage] = useState<ReplicaStage>(() =>
    state.draft.projectId ? "ready" : "source",
  );
  const [shots, setShots] = useState<ShotCard[]>([]);
  const [shotCardVersionId, setShotCardVersionId] = useState<string>();
  const [originalScript, setOriginalScript] = useState("");
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [promptText, setPromptText] = useState(state.draft.prompt);
  const [promptNameOpen, setPromptNameOpen] = useState(false);
  const [promptName, setPromptName] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [generating, setGenerating] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  const handleUpload = async (file: File) => {
    if (review) {
      notify("审核示例不上传视频。");
      return;
    }
    notify("正在上传参考视频…");
    try {
      const uploaded = await uploadWorkbenchSourceVideo(file, (percent) =>
        notify(`参考视频上传中 ${percent}%`),
      );
      patchDraft({
        projectId: uploaded.projectId,
        sourceId: uploaded.assetId,
        sourceAssetId: uploaded.assetId,
      });
      notify("参考视频已上传，点击「启动 AI 拆解」反推分镜与提示词。");
    } catch {
      notify("参考视频上传失败，请稍后重试。");
    }
  };

  const startAnalysis = async () => {
    if (review) {
      notify("审核示例不调用真实接口。");
      return;
    }
    const projectId = state.draft.projectId;
    const assetId =
      state.draft.sourceAssetId ?? project?.reference_asset_id ?? null;
    if (!projectId || !assetId) {
      notify("请先上传或选择来源视频。");
      return;
    }
    setAnalysisBusy(true);
    setStage("analyzing");
    notify("AI 拆解进行中，约需一到数分钟，请保持页面打开…");
    try {
      const task = await startVideoAnalysis(projectId, assetId);
      await waitForAnalysisTask(task.id);
      const [shotVersion, analysisVersion] = await Promise.all([
        getLatestProjectShotCards(projectId),
        getLatestProjectAnalysis(projectId).catch(() => undefined),
      ]);
      const shotPayload = shotVersion
        ? (shotVersion.payload as ShotCardPayload)
        : { shots: [], shot_card_version_id: "" };
      const script = analysisVersion
        ? (readAnalysisPayload(analysisVersion)?.original_script ?? "")
        : "";
      setShots(shotPayload.shots ?? []);
      setShotCardVersionId(shotVersion?.id || undefined);
      setOriginalScript(script);
      const text = buildReplicaPromptText(shotPayload.shots ?? [], script);
      if (!promptText.trim()) {
        setPromptText(text);
        patchDraft({ prompt: text });
      }
      setStage("ready");
      setAnalysisBusy(false);
      notify("拆解完成：分镜与 Prompt 已生成，可编辑后保存或送生成。");
    } catch (cause: unknown) {
      setAnalysisBusy(false);
      setStage("ready");
      notify(customerVisibleErrorMessage(cause, "AI 拆解失败，请稍后重试。"));
    }
  };

  const saveAsCustomPrompt = async () => {
    if (review) {
      notify("审核示例不调用真实接口。");
      return;
    }
    const projectId = state.draft.projectId;
    if (!projectId) {
      notify("请先上传或选择来源视频。");
      return;
    }
    setSavingPrompt(true);
    try {
      await saveGenerationPrompt(projectId, {
        name:
          promptName.trim() ||
          `复刻提示词 ${new Date().toLocaleDateString("zh-CN")}`,
        prompt_text: promptText,
      });
      notify("已保存到我的提示词，视频生成页可直接导入。");
      setPromptNameOpen(false);
    } catch (cause: unknown) {
      notify(
        customerVisibleErrorMessage(
          cause,
          "保存自定义提示词失败，请稍后重试。",
        ),
      );
    } finally {
      setSavingPrompt(false);
    }
  };

  const sendToGeneration = async () => {
    if (review) {
      notify("审核示例不调用真实接口。");
      return;
    }
    const projectId = state.draft.projectId;
    if (!projectId || !shotCardVersionId) {
      notify("请先完成 AI 拆解。");
      return;
    }
    setGenerating(true);
    try {
      const selection = await getLatestProjectFirstFrameSelection(projectId);
      const firstFrameAssetId = selection.version
        ? (readFirstFrameSelectionPayload(selection.version)
            ?.first_frame_asset_id ?? null)
        : null;
      if (!firstFrameAssetId) {
        // eslint-disable-next-line no-console
        console.log("REPLICA_GUIDE", typeof notify, "ff:", firstFrameAssetId);
        notify(
          "还没有确认过的置换首帧：请先到「人物置换」完成首帧确认，再回来送生成。",
        );
        return;
      }
      const batch = await runReplicaGeneration(projectId, {
        promptText,
        originalScriptText: originalScript,
        shotCardVersionId,
        firstFrameAssetId,
        outputDurationSeconds:
          state.draft.duration >= 4 && state.draft.duration <= 15
            ? Math.round(state.draft.duration)
            : 8,
        resolution: state.draft.resolution === "2K" ? "2K" : "768P",
        ratio: (SUPPORTED_VIDEO_RATIOS as readonly string[]).includes(
          state.draft.ratio,
        )
          ? (state.draft.ratio as GenerationRatio)
          : "adaptive",
        quantity:
          state.draft.count === 2 || state.draft.count === 4
            ? state.draft.count
            : 1,
      });
      notify("复刻任务已提交，可在任务中心查看进度。");
      navigate("tasks");
    } catch (cause: unknown) {
      notify(customerVisibleErrorMessage(cause, "送生成失败，请稍后重试。"));
    } finally {
      setGenerating(false);
    }
  };

  // 审核包样例分镜：仅 review 视觉演示，不参与真实拆解流程。
  const reviewShots: ShotCard[] = [
    {
      shot_id: "shot-1",
      start_time: 0,
      end_time: 8,
      shot_type: "中景",
      composition: "",
      camera_motion: "推进",
      subject: "院落",
      action: "镜头缓推庭院",
      scene: "乡墅庭院",
      spoken_text: "",
      transition: "切镜",
    },
    {
      shot_id: "shot-2",
      start_time: 8,
      end_time: 16,
      shot_type: "近景",
      composition: "",
      camera_motion: "固定",
      subject: "讲解人物",
      action: "人物出镜讲解",
      scene: "庭院",
      spoken_text: "这栋房子的采光设计",
      transition: "切镜",
    },
    {
      shot_id: "shot-3",
      start_time: 16,
      end_time: 24,
      shot_type: "特写",
      composition: "",
      camera_motion: "摇移",
      subject: "外立面",
      action: "外立面细节展示",
      scene: "建筑外立面",
      spoken_text: "",
      transition: "切镜",
    },
  ];
  const displayShots =
    shots.length > 0 ? shots : review && stage === "ready" ? reviewShots : [];
  const hasShots = stage === "ready" && displayShots.length > 0;

  return (
    <section className="creation-page creation-replica">
      <header className="creation-heading">
        <h1>视频复刻</h1>
      </header>
      <CreationNavigation />
      {stage === "source" && !project ? (
        <Panel className="creation-empty-workspace">
          <Empty
            title="先导入参考视频"
            description="上传本地视频后由 AI 拆解分镜并反推提示词；也可以选择已有项目直接续作。"
            action={
              <div className="creation-upload-row">
                <Button
                  variant="primary"
                  onClick={() => uploadInputRef.current?.click()}
                >
                  上传参考视频
                </Button>
                {data.projects.length > 0 && (
                  <select
                    aria-label="选择已有项目"
                    className="creation-project-select"
                    defaultValue=""
                    onChange={(event) => {
                      const selected = data.projects.find(
                        (item) => item.id === event.target.value,
                      );
                      if (selected) {
                        patchDraft({
                          projectId: selected.id,
                          sourceId: selected.reference_asset_id ?? undefined,
                          sourceAssetId:
                            selected.reference_asset_id ?? undefined,
                        });
                        setStage("ready");
                        notify(
                          `已切换到项目「${selected.name}」，可启动 AI 拆解。`,
                        );
                      }
                    }}
                  >
                    <option value="" disabled>
                      选择已有项目
                    </option>
                    {data.projects.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            }
          />
        </Panel>
      ) : (
        <>
          <SourceStrip source={source} />
          <Panel className="creation-replica-analyze">
            <div className="creation-panel-title-row">
              <span>
                来源视频 ·{" "}
                {project?.name ?? state.draft.projectId ?? "未命名项目"}
              </span>
              {shots.length > 0 && <small>已拆解 {shots.length} 个镜头</small>}
            </div>
            <div className="creation-upload-row">
              <Button
                variant="primary"
                disabled={analysisBusy}
                onClick={() => void startAnalysis()}
              >
                {analysisBusy
                  ? "AI 拆解进行中…"
                  : shots.length > 0
                    ? "重新拆解"
                    : "启动 AI 拆解"}
              </Button>
              <Button
                variant="outline"
                onClick={() => uploadInputRef.current?.click()}
              >
                更换来源视频
              </Button>
            </div>
            <Hint>
              拆解会反推分镜与提示词；上传新视频会创建新项目，历史任务不受影响。
            </Hint>
          </Panel>
          {hasShots && (
            <Panel className="creation-shot-list">
              <div className="creation-panel-title">
                分镜（共 {displayShots.length} 个）
              </div>
              {displayShots.map((shot, index) => (
                <div className="creation-shot-row" key={shot.shot_id}>
                  <span className="creation-shot-index">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="creation-shot-body">
                    <strong>
                      {shot.start_time.toFixed(1)}s–{shot.end_time.toFixed(1)}s
                      · {shot.shot_type || "未标注景别"}
                    </strong>
                    <small>
                      {[
                        shot.subject && `主体：${shot.subject}`,
                        shot.action && `动作：${shot.action}`,
                        shot.spoken_text && `台词：${shot.spoken_text}`,
                      ]
                        .filter(Boolean)
                        .join(" ｜ ")}
                    </small>
                  </span>
                </div>
              ))}
            </Panel>
          )}
          <Panel className="creation-prompt-output">
            <div className="creation-panel-title-row">
              <span>拆解 Prompt（可编辑）</span>
              {shots.length === 0 && <small>完成拆解后自动生成</small>}
            </div>
            <textarea
              aria-label="拆解 Prompt"
              className="creation-textarea"
              onChange={(event) => {
                setPromptText(event.target.value);
                patchDraft({ prompt: event.target.value });
              }}
              placeholder="完成 AI 拆解后，这里会生成逐镜头的反推提示词；也可手动撰写。"
              rows={10}
              value={promptText}
            />
            <div className="creation-upload-row">
              {promptNameOpen ? (
                <>
                  <input
                    aria-label="自定义提示词名称"
                    className="creation-project-select"
                    onChange={(event) => setPromptName(event.target.value)}
                    placeholder="提示词名称"
                    value={promptName}
                  />
                  <Button
                    disabled={savingPrompt}
                    onClick={() => void saveAsCustomPrompt()}
                    variant="primary"
                  >
                    {savingPrompt ? "保存中…" : "确认保存"}
                  </Button>
                  <Button
                    onClick={() => setPromptNameOpen(false)}
                    variant="quiet"
                  >
                    取消
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    onClick={() => setPromptNameOpen(true)}
                    variant="outline"
                  >
                    保存为自定义提示词
                  </Button>
                  <Button
                    disabled={generating || shots.length === 0}
                    onClick={() => void sendToGeneration()}
                    variant="primary"
                  >
                    {generating ? "提交中…" : "送生成"}
                  </Button>
                </>
              )}
            </div>
            <Hint>
              编辑后的 Prompt
              可保存为自定义提示词（视频生成页可导入）；「送生成」需要项目已有确认首帧，未确认时请先到人物置换页完成。
            </Hint>
          </Panel>
        </>
      )}
      <footer className="creation-action-bar">
        <div>
          <strong>分镜、Prompt 与生成批次能力已在本页打通</strong>
          <Hint>需要逐镜头精修可进入成熟分镜工作区。</Hint>
        </div>
        <Button variant="outline" onClick={saveDraft}>
          保存草稿
        </Button>
        <Button variant="outline" onClick={() => openLive("analysis")}>
          进入分镜工作区
        </Button>
      </footer>
      <div data-testid="replica-debug">
        {JSON.stringify({
          stage,
          scv: shotCardVersionId,
          busy: analysisBusy,
          shots: shots.length,
        })}
      </div>
      <input
        accept="video/mp4,video/quicktime"
        aria-label="上传参考视频"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleUpload(file);
          event.target.value = "";
        }}
        ref={uploadInputRef}
        type="file"
      />
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

// 生成等待期的安抚文案：按阶段轮换，降低等待焦虑（不伪造进度）。
const REASSURANCE_COPY = [
  "AI 正在理解你的提示词与画面结构…",
  "视频生成通常需要 1–3 分钟，可以先去处理其他创作。",
  "任务已进入公平队列，关掉页面也不会丢失进度。",
  "生成完成后可以直接在下方预览成片。",
];

const VIDEO_STAGE_LABELS = ["已提交", "排队中", "生成中", "完成"] as const;

function videoStageIndex(status: StudioTask["status"]): number {
  if (status === "queued") return 1;
  if (status === "running") return 2;
  if (status === "completed") return 3;
  return 0;
}

function formatElapsed(from: string): string {
  // 服务端 CURRENT_TIMESTAMP 是 UTC 文本；补 Z 防止按本地时区解析出巨幅偏差。
  const started = new Date(`${from.replace(" ", "T")}Z`).getTime();
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}

/** 生成等待视图：阶段时间线 + 进度百分比 + 轮换安抚文案。 */
function VideoProgressView({ task }: { task: StudioTask }) {
  const [copyIndex, setCopyIndex] = useState(0);
  const [, setTick] = useState(0);
  const failed = task.status === "failed" || task.status === "uncertain";

  useEffect(() => {
    if (failed) return;
    const timer = window.setInterval(() => {
      setCopyIndex((value) => (value + 1) % REASSURANCE_COPY.length);
      setTick((value) => value + 1);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [failed]);

  if (failed) {
    return (
      <div className="creation-progress failed" role="alert">
        <div className="creation-progress-headline">
          生成未完成{task.status === "uncertain" ? "（状态待确认）" : ""}
        </div>
        <p className="creation-progress-copy">
          积分未结算的失败不会扣费；可在任务中心重试或对账。
        </p>
        <Empty
          title="这条视频没有生成成功"
          description="可回到上方调整提示词或素材后重新生成。"
        />
      </div>
    );
  }

  const stageIndex = videoStageIndex(task.status);
  const progress = task.progress ?? 0;

  return (
    <div className="creation-progress" aria-live="polite">
      <ol className="creation-progress-stages">
        {VIDEO_STAGE_LABELS.map((label, index) => (
          <li
            key={label}
            className={
              index === stageIndex
                ? "is-active"
                : index < stageIndex
                  ? "is-done"
                  : ""
            }
          >
            {label}
          </li>
        ))}
      </ol>
      <progress
        aria-label="生成进度"
        className="creation-progress-bar"
        max={100}
        value={task.status === "completed" ? 100 : progress}
      />
      <div className="creation-progress-meta">
        <span>{task.status === "completed" ? "生成完成" : `${progress}%`}</span>
        <span>已等待 {formatElapsed(task.submitted)}</span>
      </div>
      <p className="creation-progress-copy">{REASSURANCE_COPY[copyIndex]}</p>
    </div>
  );
}

function SavedPromptImporter({
  onImport,
}: {
  onImport: (promptText: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [prompts, setPrompts] = useState<SavedPromptItem[]>();
  const [error, setError] = useState<string>();
  const { review, notify } = useStudio();

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && prompts === undefined && !error && !review) {
      void listUserSavedPrompts()
        .then(setPrompts)
        .catch(() => setError("我的提示词暂时读取失败，请稍后重试。"));
    }
  };

  return (
    <div className="creation-prompt-import">
      <Button variant="quiet" onClick={toggle}>
        <Icon name="arrow" size={16} /> 导入提示词
      </Button>
      {open && (
        <div
          className="creation-prompt-list"
          role="listbox"
          aria-label="我的提示词"
        >
          {review ? (
            <p>审核示例不提供提示词库。</p>
          ) : error ? (
            <p>{error}</p>
          ) : prompts === undefined ? (
            <p>正在读取我的提示词…</p>
          ) : prompts.length === 0 ? (
            <p>
              还没有保存过提示词。在项目拆解中修订反推提示词并保存后会出现在这里。
            </p>
          ) : (
            prompts.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  onImport(item.prompt_text);
                  notify(`已导入「${item.name}」，可继续修改。`);
                  setOpen(false);
                }}
              >
                <strong>{item.name}</strong>
                <small>{item.prompt_text.slice(0, 60)}</small>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function VideoMaterialUpload({
  group,
  label,
  onUploaded,
}: {
  group: string;
  label: string;
  onUploaded: (asset: StudioAsset) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number>();
  const { review, notify } = useStudio();

  const upload = async (file: File) => {
    if (review) {
      notify("审核示例不上传素材。");
      return;
    }
    setProgress(0);
    try {
      const asset = await uploadVideoMaterial(file, group, setProgress);
      onUploaded(asset);
      notify(`${label}「${file.name}」已上传到素材库。`);
    } catch {
      notify("素材上传失败，请稍后重试。");
    } finally {
      setProgress(undefined);
    }
  };

  return (
    <>
      <button
        className="creation-upload-mini"
        disabled={progress !== undefined}
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        {progress !== undefined ? `上传中 ${progress}%` : "本机上传"}
      </button>
      <input
        accept="image/png,image/jpeg"
        aria-label={`上传${label}`}
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void upload(file);
          event.target.value = "";
        }}
        ref={inputRef}
        type="file"
      />
    </>
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
    updateData,
  } = useStudio();
  const referenceMode = state.page === "reference";
  const firstFrame =
    findAsset(data.assets, state.draft.firstFrameId) ??
    findAsset(data.materials, state.draft.firstFrameId);
  const tailFrame =
    findAsset(data.assets, state.draft.tailFrameId) ??
    findAsset(data.materials, state.draft.tailFrameId);
  const references = state.draft.referenceIds
    .map((id) => findAsset(data.assets, id) ?? findAsset(data.materials, id))
    .filter((asset): asset is StudioAsset => Boolean(asset));
  const ready =
    Boolean(state.draft.prompt.trim()) &&
    (referenceMode ? references.length > 0 : true);
  const videoTask = state.draft.videoBatchId
    ? data.tasks.find((task) => task.id === state.draft.videoBatchId)
    : undefined;

  const appendMaterial = (asset: StudioAsset) => {
    updateData((previous) => ({
      ...previous,
      materials: [
        asset,
        ...previous.materials.filter((item) => item.id !== asset.id),
      ],
    }));
  };

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
            <SavedPromptImporter
              onImport={(promptText) => patchDraft({ prompt: promptText })}
            />
          </Field>
          {referenceMode ? (
            <ControlGroup label="参考素材">
              <div className="creation-upload-row">
                <button
                  className="creation-upload"
                  onClick={() => openPicker("reference")}
                  type="button"
                >
                  <Icon name="upload" />
                  <span>从素材库选择</span>
                  <small>本批生成最多 4 张参考图</small>
                </button>
                <VideoMaterialUpload
                  group="参考素材"
                  label="参考图"
                  onUploaded={(asset) => {
                    appendMaterial(asset);
                    patchDraft({
                      referenceIds: [...state.draft.referenceIds, asset.id],
                    });
                  }}
                />
              </div>
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
                <div className="creation-frame-slot">
                  <button
                    onClick={() => openPicker("first-frame")}
                    type="button"
                  >
                    <Media asset={firstFrame} alt="首帧" />
                    <span>首帧（选填）</span>
                  </button>
                  <VideoMaterialUpload
                    group="首帧素材"
                    label="首帧"
                    onUploaded={(asset) => {
                      appendMaterial(asset);
                      patchDraft({ firstFrameId: asset.id });
                    }}
                  />
                </div>
                <Icon name="arrow" />
                <div className="creation-frame-slot">
                  <button
                    onClick={() => openPicker("tail-frame")}
                    type="button"
                  >
                    <Media asset={tailFrame} alt="尾帧" />
                    <span>尾帧（可选）</span>
                  </button>
                  <VideoMaterialUpload
                    group="尾帧素材"
                    label="尾帧"
                    onUploaded={(asset) => {
                      appendMaterial(asset);
                      patchDraft({ tailFrameId: asset.id });
                    }}
                  />
                </div>
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
          {videoTask ? (
            <VideoProgressView task={videoTask} />
          ) : referenceMode ? (
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
          {videoTask && (
            <Hint>成片与历史进度可在任务中心查看，任务记录不会丢失。</Hint>
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
    navigate,
    openPicker,
    saveDraft,
    requestGeneration,
    notify,
  } = useStudio();
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
                  <Button
                    variant="outline"
                    onClick={() =>
                      notify("音频上传服务尚未接通，请先从素材库选择")
                    }
                  >
                    上传音频
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
