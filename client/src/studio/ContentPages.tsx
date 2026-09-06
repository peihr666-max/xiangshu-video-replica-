import { useEffect, useMemo, useRef, useState } from "react";
import { fetchViralVideoMedia } from "../api";
import { useStudio } from "./context";
import type { StudioAsset, StudioPublishDraft, StudioVideo } from "./types";
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
import "./content.css";

const pageSize = 6;
const categoryTabs = ["全部", "建房预算", "户型设计", "施工避坑", "庭院案例"];

function formatCount(value: number) {
  return value >= 10000
    ? `${(value / 10000).toFixed(1).replace(".0", "")}万`
    : value.toLocaleString("zh-CN");
}

function assetKindLabel(kind: StudioAsset["kind"]) {
  return kind === "image" ? "图片" : kind === "video" ? "视频" : "音频";
}

const viralInitialCount = 12;
const viralRevealStep = 8;

function viralLikesLabel(video: StudioVideo) {
  return video.likeDisplay ?? formatCount(video.likes);
}

function ViralPoster({
  video,
  className,
}: {
  video: StudioVideo;
  className?: string;
}) {
  const [broken, setBroken] = useState(false);
  if (!video.poster || broken) {
    return (
      <span
        className={
          className
            ? `viral-card-cover-empty ${className}`
            : "viral-card-cover-empty"
        }
      >
        <Icon name="video" />
      </span>
    );
  }
  return (
    <img
      alt=""
      className={className}
      loading="lazy"
      onError={() => setBroken(true)}
      src={video.poster}
    />
  );
}

function ViralCard({ video }: { video: StudioVideo }) {
  const { state, navigate, patchDraft, patchState } = useStudio();
  const saved = state.favorites.includes(video.id);
  const toggleFavorite = () =>
    patchState({
      favorites: saved
        ? state.favorites.filter((id) => id !== video.id)
        : [...state.favorites, video.id],
    });
  const openDetail = () =>
    navigate("viral-detail", {
      selectedVideoId: video.id,
      returnTo: "viral",
    });
  return (
    <article className="viral-card">
      <button
        type="button"
        className="viral-card-cover"
        onClick={openDetail}
        aria-label={`查看详情 ${video.title}`}
      >
        <ViralPoster video={video} />
        <span className="viral-card-duration">{video.duration}</span>
        <span className="viral-card-platform">{video.platform}</span>
      </button>
      <div className="viral-card-body">
        <h3>{video.title}</h3>
        <div className="viral-card-author">
          {video.authorAvatar ? (
            <img alt="" loading="lazy" src={video.authorAvatar} />
          ) : (
            <i>{(video.author || "无").slice(0, 1)}</i>
          )}
          <span>{video.author}</span>
          {video.verified && <em title="认证作者">✓</em>}
          <b>♥ {viralLikesLabel(video)}</b>
        </div>
        {video.tags && video.tags.length > 0 && (
          <div className="viral-card-tags">
            {video.tags.slice(0, 6).map((tag) => (
              <span key={tag}>#{tag}</span>
            ))}
          </div>
        )}
        <div className="content-card-actions">
          <Button variant="quiet" onClick={openDetail}>
            查看详情
          </Button>
          <Button
            variant="outline"
            aria-label={`收藏 ${video.title}`}
            onClick={toggleFavorite}
          >
            {saved ? "已收藏" : "收藏"}
          </Button>
          <Button
            variant="outline"
            aria-label={`复刻 ${video.title}`}
            onClick={() => {
              patchDraft({ sourceId: video.id });
              navigate("replica", {
                selectedVideoId: video.id,
                returnTo: "viral",
              });
            }}
          >
            复刻
          </Button>
        </div>
      </div>
    </article>
  );
}

export function ViralPage() {
  const { data, review } = useStudio();
  const [platform, setPlatform] = useState<"抖音" | "视频号">("抖音");
  const [category, setCategory] = useState("全部");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"热门优先" | "最新">("热门优先");
  const [visibleCount, setVisibleCount] = useState(viralInitialCount);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const shown = useMemo(
    () =>
      data.videos
        .filter(
          (item) =>
            item.platform === platform &&
            (category === "全部" || item.category === category) &&
            `${item.title}${item.author}`.includes(query),
        )
        .sort((left, right) => {
          if (sort === "热门优先") {
            return (
              right.likes - left.likes ||
              left.id.localeCompare(right.id, undefined, { numeric: true })
            );
          }
          return (right.publishedAt ?? 0) - (left.publishedAt ?? 0);
        }),
    [category, data.videos, platform, query, sort],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: 平台/分类/搜索词/排序变化时重置滚动加载计数。
  useEffect(() => {
    setVisibleCount(viralInitialCount);
  }, [platform, category, query, sort]);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisibleCount((count) =>
            Math.min(count + viralRevealStep, shown.length),
          );
        }
      },
      { rootMargin: "240px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [shown.length]);

  const current = shown.slice(0, visibleCount);
  const platformTabs = (["抖音", "视频号"] as const).map((item) => ({
    id: item,
    label: `${item} ${
      review
        ? item === "抖音"
          ? 20
          : 30
        : data.videos.filter((video) => video.platform === item).length
    }`,
  }));

  return (
    <section className="content-page content-viral">
      <header className="content-title">
        <div>
          <h1>爆款视频</h1>
          <p>乡墅灵感，持续发现 · 最近 7 天爆款</p>
        </div>
        <div className="content-search">
          <Icon name="search" />
          <input
            aria-label="搜索视频标题"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            placeholder="在已加载的爆款中搜索"
          />
        </div>
      </header>
      <div className="content-viral-toolbar">
        <div
          className="content-platform-tabs"
          role="tablist"
          aria-label="视频平台"
        >
          {platformTabs.map((item) => (
            <button
              aria-selected={item.id === platform}
              className={item.id === platform ? "is-active" : ""}
              key={item.id}
              onClick={() => setPlatform(item.id)}
              role="tab"
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="content-sort">
          <span>排序</span>
          <select
            aria-label="排序方式"
            value={sort}
            onChange={(event) =>
              setSort(event.target.value as "热门优先" | "最新")
            }
          >
            <option value="热门优先">热门优先</option>
            <option value="最新">最新</option>
          </select>
        </label>
      </div>
      <nav className="content-filters" aria-label="视频分类">
        {categoryTabs.map((item) => (
          <Button
            key={item}
            variant={item === category ? "primary" : "outline"}
            onClick={() => setCategory(item)}
          >
            {item}
          </Button>
        ))}
      </nav>
      {current.length ? (
        <>
          <section className="content-video-grid content-video-grid-viral">
            {current.map((video) => (
              <ViralCard key={video.id} video={video} />
            ))}
          </section>
          {visibleCount < shown.length && (
            <div className="viral-reveal-sentinel" aria-hidden="true">
              <span>上拉加载更多…</span>
            </div>
          )}
        </>
      ) : (
        <Empty
          title="暂无爆款视频"
          description="数据源尚未配置或最近 7 天暂无内容，配置后自动展示。"
        />
      )}
    </section>
  );
}

type ViralMediaState = {
  status: "idle" | "loading" | "ready" | "error";
  message?: string;
};

function useViralMedia() {
  const [media, setMedia] = useState<ViralMediaState>({ status: "idle" });
  return {
    media,
    prepare: async (
      video: StudioVideo,
      onReady: (kind: "audio" | "video") => void,
    ) => {
      if (!video.platformKey || !video.nativeId) {
        onReady("video");
        return;
      }
      setMedia({ status: "loading" });
      try {
        const result = await fetchViralVideoMedia(
          video.platformKey,
          video.nativeId,
        );
        setMedia({
          status: "ready",
          message:
            result.kind === "audio" ? "原声音频已就绪" : "低清视频已就绪",
        });
        onReady(result.kind);
      } catch (error) {
        setMedia({
          status: "error",
          message: error instanceof Error ? error.message : "素材准备失败",
        });
      }
    },
  };
}

export function ViralDetailPage() {
  const { data, state, navigate, patchDraft, patchState } = useStudio();
  const { media, prepare } = useViralMedia();
  const video = state.selectedVideoId
    ? data.videos.find((item) => item.id === state.selectedVideoId)
    : undefined;
  if (!video)
    return (
      <section className="content-page">
        <Empty
          title="暂未选择参考视频"
          description="请返回爆款视频列表选择一条内容。"
          action={
            <Button variant="primary" onClick={() => navigate("viral")}>
              返回爆款视频
            </Button>
          }
        />
      </section>
    );
  const saved = state.favorites.includes(video.id);
  const isWechat = video.platform === "视频号";
  const published =
    video.publishedDisplay ??
    (video.publishedAt
      ? new Date(video.publishedAt * 1000).toLocaleDateString("zh-CN")
      : "—");
  const stats: Array<[string, string]> = [
    ["点赞", viralLikesLabel(video)],
    ...(isWechat
      ? []
      : ([
          ["评论", formatCount(video.comments ?? 0)],
          ["收藏", formatCount(video.collections)],
          ["转发", formatCount(video.shares)],
        ] as Array<[string, string]>)),
    ["发布", published],
    ["时长", video.duration],
  ];
  const goExtract = () => {
    patchDraft({ sourceId: video.id });
    navigate("copy", {
      selectedVideoId: video.id,
      returnTo: "viral-detail",
    });
  };
  const goReplica = () => {
    patchDraft({ sourceId: video.id });
    navigate("replica", {
      selectedVideoId: video.id,
      returnTo: "viral-detail",
    });
  };
  return (
    <section className="content-page content-detail">
      <header className="content-detail-heading">
        <h1>爆款视频 / 视频详情</h1>
        <Button
          variant="quiet"
          onClick={() => navigate(state.returnTo ?? "viral")}
        >
          ‹ 返回列表
        </Button>
      </header>
      <section className="content-detail-grid">
        <div className="content-player content-player-viral">
          <ViralPoster video={video} className="content-player-viral-poster" />
          <span>▶ {video.duration}</span>
        </div>
        <Panel className="content-detail-info">
          <div className="content-detail-author">
            {video.authorAvatar ? (
              <img alt="" src={video.authorAvatar} />
            ) : (
              <i>{(video.author || "无").slice(0, 1)}</i>
            )}
            <div>
              <strong>
                {video.author}
                {video.verified && <em title="认证作者">✓</em>}
              </strong>
              <span>
                {video.platform} · {video.category || "推荐"}
                {video.hasPlayableAudio ? " · 有原声" : ""}
              </span>
            </div>
          </div>
          <h2>{video.title}</h2>
          {video.tags && video.tags.length > 0 && (
            <div className="viral-card-tags viral-detail-tags">
              {video.tags.slice(0, 6).map((tag) => (
                <span key={tag}>#{tag}</span>
              ))}
            </div>
          )}
          <dl className="content-detail-stats">
            {stats.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <Field label="视频摘要（来源作品原文）">
            <p className="content-source-copy">{video.description}</p>
          </Field>
          <Hint>
            来源内容仅供创作参考；素材按需获取（音频优先，其次低清视频）。
          </Hint>
          {media.status !== "idle" && (
            <p
              className={`viral-media-status is-${media.status}`}
              role="status"
            >
              {media.status === "loading" && "素材准备中，可能需要几十秒…"}
              {media.status === "ready" && media.message}
              {media.status === "error" &&
                `素材准备失败：${media.message ?? ""}`}
            </p>
          )}
          <div className="content-detail-actions">
            <div className="content-detail-action">
              <Button
                disabled={media.status === "loading"}
                variant="outline"
                onClick={() => prepare(video, goExtract)}
              >
                提取文案
              </Button>
              <small>
                {video.hasPlayableAudio
                  ? "优先取原声音频，带入文案工坊"
                  : "取低清视频后抽音频，带入文案工坊"}
              </small>
            </div>
            <div className="content-detail-action">
              <Button
                disabled={media.status === "loading"}
                variant="outline"
                onClick={() => prepare(video, goReplica)}
              >
                视频复刻
              </Button>
              <small>取低清视频作参考，带入视频创作</small>
            </div>
            <div className="content-detail-action">
              <Button
                variant="outline"
                onClick={() =>
                  patchState({
                    favorites: saved
                      ? state.favorites.filter((id) => id !== video.id)
                      : [...state.favorites, video.id],
                  })
                }
              >
                {saved ? "已收藏" : "收藏"}
              </Button>
              <small>加入我的收藏，后续继续参考</small>
            </div>
          </div>
        </Panel>
      </section>
    </section>
  );
}

function AssetCard({
  asset,
  selected,
  onSelect,
}: {
  asset: StudioAsset;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`content-asset ${selected ? "is-selected" : ""} ${asset.composite ? "content-asset--composite" : ""}`}
      onClick={onSelect}
      aria-label={`选择素材 ${asset.name}`}
    >
      <Media asset={asset} alt={asset.name} />
      <strong>{asset.name}</strong>
      <span>
        {asset.group} · {assetKindLabel(asset.kind)}
      </span>
      <i>{asset.saved ? "已保存" : "处理中"}</i>
    </button>
  );
}

export function MaterialsPage() {
  const { data, state, patchState, patchDraft, navigate, notify } = useStudio();
  const [kind, setKind] = useState<"全部" | StudioAsset["kind"]>("全部");
  const assets = data.assets.filter(
    (asset) => kind === "全部" || asset.kind === kind,
  );
  const selected = data.assets.find(
    (asset) => asset.id === state.selectedAssetId,
  );
  const selectedIndex = assets.findIndex(
    (asset) => asset.id === state.selectedAssetId,
  );
  const pages = Math.max(1, Math.ceil(assets.length / pageSize));
  const [page, setPage] = useState(() =>
    selectedIndex >= 0 ? Math.floor(selectedIndex / pageSize) + 1 : 1,
  );
  const selectedAssetIdRef = useRef(state.selectedAssetId);
  useEffect(() => {
    if (selectedAssetIdRef.current === state.selectedAssetId) return;
    selectedAssetIdRef.current = state.selectedAssetId;
    if (selectedIndex >= 0) {
      setPage(Math.floor(selectedIndex / pageSize) + 1);
    }
  }, [selectedIndex, state.selectedAssetId]);
  const currentAssets = assets.slice((page - 1) * pageSize, page * pageSize);
  return (
    <section className="content-page content-materials">
      <header className="content-title">
        <div>
          <h1>素材库</h1>
          <p>统一管理和复用乡墅创作素材</p>
        </div>
        <Button
          className="content-title-action"
          variant="primary"
          onClick={() => notify("上传能力将在素材服务接通后启用")}
        >
          上传素材
        </Button>
      </header>
      <Tabs
        items={[
          { id: "全部", label: "全部" },
          { id: "video", label: "视频" },
          { id: "image", label: "图片" },
          { id: "audio", label: "音频" },
        ]}
        value={kind}
        onChange={(value) => {
          setKind(value as typeof kind);
          setPage(1);
        }}
      />
      <section className="content-material-layout">
        <div className="content-material-list">
          <div className="content-asset-grid">
            {currentAssets.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                selected={selected?.id === asset.id}
                onSelect={() => patchState({ selectedAssetId: asset.id })}
              />
            ))}
          </div>
          {assets.length > pageSize ? (
            <nav className="content-pagination" aria-label="素材分页">
              <span>
                共 {assets.length} 条 · 每页 {pageSize} 条
              </span>
              <Button
                aria-label="上一页"
                disabled={page === 1}
                variant="outline"
                onClick={() => setPage((currentPage) => currentPage - 1)}
              >
                ‹
              </Button>
              {Array.from({ length: pages }, (_, index) => index + 1).map(
                (pageNumber) => (
                  <Button
                    key={pageNumber}
                    variant={page === pageNumber ? "primary" : "quiet"}
                    onClick={() => setPage(pageNumber)}
                  >
                    {pageNumber}
                  </Button>
                ),
              )}
              <Button
                aria-label="下一页"
                disabled={page === pages}
                variant="outline"
                onClick={() => setPage((currentPage) => currentPage + 1)}
              >
                ›
              </Button>
            </nav>
          ) : null}
        </div>
        <Panel className="content-inspector">
          {selected ? (
            <>
              <h2>{selected.name}</h2>
              {selected.kind === "audio" && <Waveform />}
              <dl>
                <dt>类型</dt>
                <dd>{assetKindLabel(selected.kind)}</dd>
                <dt>来源</dt>
                <dd>{selected.source}</dd>
                <dt>归属</dt>
                <dd>{selected.personId ? "人物库" : selected.group}</dd>
                <dt>状态</dt>
                <dd>{selected.saved ? "已保存" : "处理中"}</dd>
              </dl>
              {selected.kind === "audio" ? (
                <Button
                  variant="primary"
                  onClick={() => {
                    patchDraft({
                      audioId: selected.id,
                      ipId: selected.personId,
                      voiceId: undefined,
                    });
                    navigate("oral-audio", { returnTo: "materials" });
                  }}
                >
                  用于音频口播
                </Button>
              ) : (
                <Hint>选择后可在当前创作草稿中引用此素材。</Hint>
              )}
            </>
          ) : (
            <Empty
              title="选择一个素材"
              description="统一选择后再进入相应创作流程。"
            />
          )}
        </Panel>
      </section>
    </section>
  );
}

function newPublishDraft(
  asset: StudioAsset | undefined,
  review: boolean,
): StudioPublishDraft {
  return {
    id: `publish-${asset?.id ?? "unsaved"}`,
    assetId: asset?.id ?? "",
    coverId: asset?.id,
    platform: "抖音",
    account: review ? "张工说乡墅" : "",
    title: asset?.name ?? "",
    description: review
      ? "主体之外，门窗、水电、防水和庭院，也要提前规划。"
      : "",
    tags: review ? ["农村自建房", "建房预算"] : [],
  };
}

export function PublishPage() {
  const { data, navigate, patchState, review, state } = useStudio();
  const completedResultIds = new Set(
    data.tasks
      .filter((task) => task.status === "completed" && task.resultId)
      .map((task) => task.resultId),
  );
  const selectedAsset = data.assets.find(
    (asset) =>
      asset.id === state.selectedAssetId &&
      asset.kind === "video" &&
      (completedResultIds.size === 0 || completedResultIds.has(asset.id)),
  );
  const coverCandidates = [
    ...(selectedAsset ? [selectedAsset] : []),
    ...data.assets.filter(
      (asset) =>
        asset.id !== selectedAsset?.id &&
        asset.kind === "image" &&
        (Boolean(asset.personId) || asset.group.includes("场景")),
    ),
  ].slice(0, 3);
  const savedDraftForAsset = state.publishDrafts?.find(
    (draft) => draft.assetId === selectedAsset?.id,
  );
  const visibleDrafts =
    state.publishDrafts ??
    (review && selectedAsset ? [newPublishDraft(selectedAsset, review)] : []);
  const [form, setForm] = useState<StudioPublishDraft>(
    () => savedDraftForAsset ?? newPublishDraft(selectedAsset, review),
  );
  const [tagInput, setTagInput] = useState("");
  const [saveNotice, setSaveNotice] = useState(false);
  const draftCount = visibleDrafts.length;
  const selectedCover =
    coverCandidates.find((asset) => asset.id === form.coverId) ??
    coverCandidates[0];

  useEffect(() => {
    setForm(savedDraftForAsset ?? newPublishDraft(selectedAsset, review));
    setSaveNotice(false);
  }, [review, savedDraftForAsset, selectedAsset]);

  const updateForm = (patch: Partial<StudioPublishDraft>) => {
    setSaveNotice(false);
    setForm((current) => ({ ...current, ...patch }));
  };

  const addTag = () => {
    const tag = tagInput.trim();
    if (!tag || form.tags.includes(tag)) {
      setTagInput("");
      return;
    }
    updateForm({ tags: [...form.tags, tag] });
    setTagInput("");
  };

  const savePublishDraft = () => {
    if (!selectedAsset) return;
    const savedDraft = {
      ...form,
      id: savedDraftForAsset?.id ?? `publish-${selectedAsset.id}`,
      assetId: selectedAsset.id,
      coverId: selectedCover?.id,
    };
    const currentDrafts = state.publishDrafts ?? [];
    patchState({
      publishDrafts: savedDraftForAsset
        ? currentDrafts.map((draft) =>
            draft.id === savedDraftForAsset.id ? savedDraft : draft,
          )
        : [...currentDrafts, savedDraft],
    });
    setForm(savedDraft);
    setSaveNotice(true);
  };

  return (
    <section className="content-page content-publish">
      <header className="content-title">
        <div>
          <h1>发布管理</h1>
          <p>编辑发布草稿，确认后再提交至平台发布</p>
        </div>
      </header>
      <section className="content-publish-layout">
        <Panel className="content-publish-drafts">
          <div className="content-publish-draft-tabs">
            <strong>
              发布草稿 <b>{draftCount}</b>
            </strong>
            <span>
              待发布 <b>0</b>
            </span>
            <span>
              已发布 <b>0</b>
            </span>
          </div>
          {visibleDrafts.length ? (
            visibleDrafts.map((draft) => {
              const draftAsset = data.assets.find(
                (asset) => asset.id === draft.assetId,
              );
              const isReviewSample = !state.publishDrafts;
              return (
                <button
                  className="content-publish-draft-card"
                  key={draft.id}
                  onClick={() => {
                    setForm(draft);
                    setSaveNotice(false);
                    patchState({ selectedAssetId: draft.assetId });
                  }}
                  type="button"
                >
                  {draftAsset ? (
                    <Media asset={draftAsset} alt={`${draft.title} 草稿封面`} />
                  ) : (
                    <div className="content-publish-draft-card-empty">
                      <Icon name="video" />
                    </div>
                  )}
                  <span>
                    <strong>{draft.title || "未命名发布草稿"}</strong>
                    <small>来源：任务中心</small>
                    <i>已保存 · 待发布</i>
                    <small>
                      {isReviewSample ? "审核示例" : "当前会话草稿"}
                    </small>
                  </span>
                </button>
              );
            })
          ) : (
            <Empty
              title="暂无发布草稿"
              description={
                selectedAsset
                  ? "填写右侧信息后保存到当前会话。"
                  : "从任务中心选择一条已完成的视频后创建草稿。"
              }
            />
          )}
        </Panel>
        <Panel className="content-publish-editor">
          <header className="content-publish-editor-heading">
            <h2>编辑发布草稿</h2>
            <Hint>发布文案独立于口播终稿；确认后才提交发布。</Hint>
          </header>
          <div className="content-publish-media-grid">
            <section className="content-publish-preview">
              <h3>视频预览</h3>
              {selectedAsset ? (
                <Media
                  asset={selectedAsset}
                  alt={`${selectedAsset.name} 视频预览`}
                />
              ) : (
                <Empty
                  title="暂无可发布成片"
                  description="请从任务中心选择一条已完成的视频。"
                />
              )}
            </section>
            <section className="content-publish-cover">
              <h3>封面选择</h3>
              {coverCandidates.length ? (
                <div className="content-cover-options">
                  {coverCandidates.map((asset, index) => (
                    <button
                      aria-label={`选择封面 ${asset.name}`}
                      className={
                        selectedCover?.id === asset.id ? "is-selected" : ""
                      }
                      key={asset.id}
                      onClick={() => updateForm({ coverId: asset.id })}
                      type="button"
                    >
                      <Media asset={asset} alt={`封面 ${index + 1}`} />
                    </button>
                  ))}
                </div>
              ) : (
                <div className="content-cover-empty">
                  <Icon name="image" />
                  <span>暂无可选封面</span>
                </div>
              )}
              <Button disabled variant="outline">
                上传自定义封面（接口待接通）
              </Button>
            </section>
          </div>
          <div className="content-publish-fields">
            <Field label="发布平台">
              <div className="content-platform-options">
                {(["抖音", "视频号"] as const).map((platform) => (
                  <Button
                    aria-pressed={form.platform === platform}
                    key={platform}
                    onClick={() => updateForm({ platform })}
                    variant={form.platform === platform ? "primary" : "outline"}
                  >
                    {platform}
                  </Button>
                ))}
              </div>
            </Field>
            <Field label="发布账号">
              {review ? (
                <div className="content-publish-account">
                  <Button
                    aria-pressed={form.account === "张工说乡墅"}
                    onClick={() => updateForm({ account: "张工说乡墅" })}
                    variant="outline"
                  >
                    张工说乡墅
                  </Button>
                  <span>审核示例账号</span>
                </div>
              ) : (
                <div className="content-publish-account-empty">
                  <span>尚未连接发布账号</span>
                  <Button onClick={() => navigate("profile")} variant="quiet">
                    前往用户档案管理账号
                  </Button>
                </div>
              )}
            </Field>
            <Field label="发布标题">
              <input
                onChange={(event) => updateForm({ title: event.target.value })}
                placeholder="填写发布标题"
                value={form.title}
              />
            </Field>
            <Field label="发布描述">
              <textarea
                onChange={(event) =>
                  updateForm({ description: event.target.value })
                }
                placeholder="填写发布说明"
                value={form.description}
              />
            </Field>
            <Field label="标签">
              <div className="content-publish-tags">
                {form.tags.map((tag) => (
                  <span key={tag}># {tag}</span>
                ))}
                <input
                  aria-label="添加标签"
                  onChange={(event) => setTagInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter") return;
                    event.preventDefault();
                    addTag();
                  }}
                  placeholder="输入标签后按 Enter"
                  value={tagInput}
                />
              </div>
            </Field>
          </div>
          {saveNotice && (
            <p className="content-publish-save-notice">
              已保存到当前会话，未同步到云端。
            </p>
          )}
          <div className="content-publish-actions">
            <Button
              disabled={!selectedAsset}
              onClick={savePublishDraft}
              variant="outline"
            >
              保存草稿
            </Button>
            <Button
              aria-label="正式发布（接口未接通）"
              disabled
              variant="primary"
            >
              正式发布（接口未接通）
            </Button>
          </div>
        </Panel>
      </section>
    </section>
  );
}
