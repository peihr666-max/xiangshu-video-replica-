import { useEffect, useMemo, useRef, useState } from "react";
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

function VideoCard({ video }: { video: StudioVideo }) {
  const { state, navigate, patchDraft, patchState } = useStudio();
  const saved = state.favorites.includes(video.id);
  const toggleFavorite = () =>
    patchState({
      favorites: saved
        ? state.favorites.filter((id) => id !== video.id)
        : [...state.favorites, video.id],
    });
  return (
    <article className="content-video-card">
      <button
        type="button"
        className="content-video-preview"
        onClick={() =>
          navigate("viral-detail", {
            selectedVideoId: video.id,
            returnTo: "viral",
          })
        }
        aria-label={`查看详情 ${video.title}`}
      >
        <Media
          asset={{
            id: video.id,
            name: video.title,
            kind: "image",
            url: video.poster,
            source: video.platform,
            group: video.category,
            saved: true,
          }}
          alt={video.title}
        />
        <span>{video.duration}</span>
      </button>
      <h3>{video.title}</h3>
      <p>
        {video.author}
        <em>♡ {formatCount(video.likes)}</em>
      </p>
      <div className="content-card-actions">
        <Button
          variant="quiet"
          onClick={() =>
            navigate("viral-detail", {
              selectedVideoId: video.id,
              returnTo: "viral",
            })
          }
        >
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
    </article>
  );
}

export function ViralPage() {
  const { data, review } = useStudio();
  const [platform, setPlatform] = useState("抖音");
  const [category, setCategory] = useState("全部");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"热门优先" | "最新">("热门优先");
  const [page, setPage] = useState(1);
  const shown = useMemo(
    () =>
      [
        ...data.videos.filter(
          (item) =>
            item.platform === platform &&
            (category === "全部" || item.category === category) &&
            `${item.title}${item.author}`.includes(query),
        ),
      ].sort((left, right) =>
        sort === "热门优先"
          ? right.likes - left.likes || left.id.localeCompare(right.id)
          : right.id.localeCompare(left.id),
      ),
    [category, data.videos, platform, query, sort],
  );
  const current = shown.slice((page - 1) * pageSize, page * pageSize);
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const platformTabs = (["抖音", "视频号"] as const).map((item) => ({
    id: item,
    label: `${item} ${review ? 30 : data.videos.filter((video) => video.platform === item).length}`,
  }));
  return (
    <section className="content-page content-viral">
      <header className="content-title">
        <div>
          <h1>爆款视频</h1>
          <p>乡墅灵感，持续发现</p>
        </div>
        <div className="content-search">
          <Icon name="search" />
          <input
            aria-label="搜索视频标题"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder="搜索视频标题"
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
              onClick={() => {
                setPlatform(item.id);
                setPage(1);
              }}
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
            onChange={(event) => {
              setSort(event.target.value as "热门优先" | "最新");
              setPage(1);
            }}
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
            onClick={() => {
              setCategory(item);
              setPage(1);
            }}
          >
            {item}
          </Button>
        ))}
      </nav>
      {current.length ? (
        <>
          <section className="content-video-grid">
            {current.map((video) => (
              <VideoCard key={video.id} video={video} />
            ))}
          </section>
          <nav className="content-pagination" aria-label="爆款视频分页">
            <span>
              共 {shown.length} 条 · 每页 {pageSize} 条
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
        </>
      ) : (
        <Empty title="没有匹配的视频" description="调整搜索词或分类后再试。" />
      )}
    </section>
  );
}

export function ViralDetailPage() {
  const { data, state, navigate, patchDraft, patchState } = useStudio();
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
        <div className="content-player">
          <Media
            asset={{
              id: video.id,
              name: video.title,
              kind: "image",
              url: video.poster,
              source: video.platform,
              group: video.category,
              saved: true,
            }}
            alt={video.title}
          />
          <span>▶ {video.duration}</span>
        </div>
        <Panel className="content-detail-info">
          <p className="content-detail-kicker">用于创作</p>
          <div className="content-detail-fields">
            <p>
              <span>来源平台</span>
              <strong>{video.platform}</strong>
            </p>
            <p>
              <span>作者</span>
              <strong>{video.author}</strong>
            </p>
          </div>
          <h2>{video.title}</h2>
          <p className="content-detail-meta">
            时长 {video.duration} · 点赞 {formatCount(video.likes)} · 收藏{" "}
            {formatCount(video.collections)} · 转发 {formatCount(video.shares)}
          </p>
          <Field label="视频摘要（来源作品原文）">
            <p className="content-source-copy">{video.description}</p>
          </Field>
          <Hint>来源内容仅供创作参考。</Hint>
          <div className="content-detail-actions">
            <div className="content-detail-action">
              <Button
                variant="outline"
                onClick={() => {
                  patchDraft({ sourceId: video.id });
                  navigate("copy", {
                    selectedVideoId: video.id,
                    returnTo: "viral-detail",
                  });
                }}
              >
                提取文案
              </Button>
              <small>带入文案工坊，编辑成乡墅口播脚本</small>
            </div>
            <div className="content-detail-action">
              <Button
                variant="outline"
                onClick={() => {
                  patchDraft({ sourceId: video.id });
                  navigate("replica", {
                    selectedVideoId: video.id,
                    returnTo: "viral-detail",
                  });
                }}
              >
                视频复刻
              </Button>
              <small>带入视频创作，参考镜头与画面结构</small>
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
