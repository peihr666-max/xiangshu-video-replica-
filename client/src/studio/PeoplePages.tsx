import { useRef, useState } from "react";
import { confirmOralVoice, customerVisibleErrorMessage } from "../api";
import { useStudio } from "./context";
import type { StudioPage, StudioPerson } from "./types";
import { Button, Empty, Field, Hint, Media, Panel, Tabs } from "./ui";
import "./people.css";

const personTabs: Array<{ id: StudioPage; label: string }> = [
  { id: "person-ip", label: "IP 定位" },
  { id: "person-photos", label: "形象照片" },
  { id: "person-avatars", label: "口播分身" },
  { id: "person-voices", label: "声音档案" },
];

function selectedPerson(people: StudioPerson[], id?: string) {
  return id ? people.find((person) => person.id === id) : people[0];
}

export function PeoplePage() {
  const { data, navigate, openLive } = useStudio();
  const [roleFilter, setRoleFilter] = useState("全部");
  const people = data.people;
  const visiblePeople =
    roleFilter === "全部"
      ? people
      : people.filter((person) => person.role === roleFilter);
  return (
    <section className="people-page" aria-label="人物库">
      <div className="people-toolbar">
        <div>
          <h1>人物库</h1>
          <p>统一管理人物定位、形象照片、口播分身与声音</p>
        </div>
        <Button
          aria-label="新增人物"
          variant="primary"
          onClick={() => openLive("characters")}
        >
          ＋ 新增人物
        </Button>
      </div>
      <div className="people-filters">
        {["全部", "乡墅设计师", "项目负责人", "客户经理"].map((label) => (
          <button
            className={
              label === roleFilter ? "people-filter is-active" : "people-filter"
            }
            key={label}
            type="button"
            onClick={() => setRoleFilter(label)}
          >
            {label}
          </button>
        ))}
      </div>
      {visiblePeople.length === 0 ? (
        <Empty
          title="还没有人物"
          description="从人物库创建第一位乡墅行业 IP。"
          action={
            <Button variant="primary" onClick={() => openLive("characters")}>
              新增人物
            </Button>
          }
        />
      ) : (
        <div className="people-grid">
          {visiblePeople.map((person) => (
            <PersonCard
              key={person.id}
              person={person}
              onOpen={() =>
                navigate("person-ip", { selectedPersonId: person.id })
              }
            />
          ))}
        </div>
      )}
      <Hint>
        普通照片用于画面创作；口播需要可用分身，文案模式还需要已确认声音。
      </Hint>
    </section>
  );
}

function PersonCard({
  person,
  onOpen,
}: {
  person: StudioPerson;
  onOpen(): void;
}) {
  const { navigate } = useStudio();
  const portrait = person.portrait;
  const voices = person.voices.filter((voice) => voice.confirmed).length;
  const avatars = person.avatars.filter((avatar) => avatar.ready).length;
  return (
    <article className="person-card">
      <Media
        asset={
          portrait
            ? {
                id: `${person.id}-portrait`,
                name: person.name,
                kind: "image",
                url: portrait,
                group: "人物",
                source: "人物库",
                saved: true,
              }
            : undefined
        }
        alt={`${person.name}形象`}
        className="person-card__portrait"
      />
      <div className="person-card__body">
        <h2>{person.name}</h2>
        <p>{person.role}</p>
        <div className="person-card__meta">
          <span>✓ 形象照片 {person.photoIds.length} 张</span>
          <span>✓ 口播分身 {avatars} 个</span>
          <span className={voices ? "" : "is-warning"}>
            {voices ? `✓ 可用声音 ${voices} 个` : "！声音待添加"}
          </span>
        </div>
        <div className="person-card__actions">
          <Button variant="primary" onClick={onOpen}>
            查看人物
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              navigate("person-photos", { selectedPersonId: person.id })
            }
          >
            用于创作
          </Button>
        </div>
      </div>
    </article>
  );
}

export function PersonPage() {
  const { state, data, navigate } = useStudio();
  const person = selectedPerson(data.people, state.selectedPersonId);
  const tab = state.page === "people" ? "person-ip" : state.page;
  if (!person)
    return (
      <Empty title="未选择人物" description="请先从人物库选择一位人物。" />
    );
  return (
    <section className="person-page" aria-label="人物详情">
      <button
        className="people-back"
        type="button"
        onClick={() =>
          navigate(state.returnTo ?? "people", { returnTo: undefined })
        }
      >
        ← 返回{state.returnTo ? "创作" : "人物库"}
      </button>
      <PersonHeader person={person} />
      <Tabs
        items={personTabs}
        value={tab}
        onChange={(next) =>
          navigate(next as StudioPage, { selectedPersonId: person.id })
        }
      />
      <div className="person-content">
        {tab === "person-ip" ? <IpPanel person={person} /> : null}
        {tab === "person-photos" ? <PhotosPanel person={person} /> : null}
        {tab === "person-avatars" ? <AvatarPanel person={person} /> : null}
        {tab === "person-voices" ? <VoicePanel person={person} /> : null}
      </div>
    </section>
  );
}

function PersonHeader({ person }: { person: StudioPerson }) {
  const portrait = person.portrait;
  return (
    <header className="person-header">
      <Media
        asset={
          portrait
            ? {
                id: `${person.id}-portrait`,
                name: person.name,
                kind: "image",
                url: portrait,
                group: "人物",
                source: "人物库",
                saved: true,
              }
            : undefined
        }
        alt={`${person.name}头像`}
        className="person-header__portrait"
      />
      <div>
        <h1>{person.name}</h1>
        <p>{person.role}</p>
        {person.version > 0 ? (
          <span>人物版本 V{person.version} · 乡墅行业 IP</span>
        ) : null}
      </div>
    </header>
  );
}

function IpPanel({ person }: { person: StudioPerson }) {
  const { review, updateData, navigate, notify, patchDraft } = useStudio();
  const [draft, setDraft] = useState(() => ({
    name: person.name,
    role: person.role,
    scope: person.scope,
    audience: person.audience,
    expression: person.expression,
  }));
  const update = (key: keyof typeof draft, value: string) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const save = () => {
    if (!review) return;
    updateData((data) => ({
      ...data,
      people: data.people.map((item) =>
        item.id === person.id ? { ...item, ...draft } : item,
      ),
    }));
    notify("定位草稿已更新");
  };
  return (
    <div className="ip-layout">
      <Panel>
        <h2>人物定位</h2>
        <Field label="姓名">
          <input
            value={draft.name}
            onChange={(event) => update("name", event.target.value)}
          />
        </Field>
        <Field label="身份">
          <input
            value={draft.role}
            onChange={(event) => update("role", event.target.value)}
          />
        </Field>
        <Field label="服务范围">
          <input
            value={draft.scope}
            onChange={(event) => update("scope", event.target.value)}
          />
        </Field>
        <Field label="目标人群">
          <input
            value={draft.audience}
            onChange={(event) => update("audience", event.target.value)}
          />
        </Field>
        <Field label="表达特点">
          <input
            value={draft.expression}
            onChange={(event) => update("expression", event.target.value)}
          />
        </Field>
      </Panel>
      <Panel>
        <h2>人物简介预览</h2>
        <p className="ip-preview">
          大家好，我是{draft.name}，一名{draft.role}。我专注于{draft.scope}
          ，服务{draft.audience}，表达风格是{draft.expression}。
        </p>
        <Hint>文案工坊会引用此定位生成更贴合乡墅行业的内容。</Hint>
      </Panel>
      <div className="person-footer">
        <Button variant="primary" disabled={!review} onClick={save}>
          {review ? "保存定位草稿" : "正式保存待接通"}
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            patchDraft({ ipId: person.id });
            navigate("copy", { selectedPersonId: person.id });
          }}
        >
          去文案工坊创作
        </Button>
      </div>
    </div>
  );
}

function PhotosPanel({ person }: { person: StudioPerson }) {
  const { openLive, navigate, patchDraft, data, notify } = useStudio();
  const assets = data.assets.filter(
    (asset) => asset.personId === person.id && asset.kind === "image",
  );
  return (
    <div className="photos-panel">
      <div className="panel-heading">
        <div>
          <h2>形象照片</h2>
          <p>五视图是一张合成图；场景形象照按套单独管理。</p>
        </div>
        <div>
          <Button
            variant="outline"
            onClick={() => {
              notify(
                "当前人物追加形象照接口尚未接通，请在人物管理中上传或创建新人物。",
              );
              openLive("characters");
            }}
          >
            管理形象照
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              notify(`将在人物管理中为${person.name}选择并生成场景形象照。`);
              openLive("characters");
            }}
          >
            AI 生成场景照
          </Button>
        </div>
      </div>
      <Panel>
        <h3>基础五视图 · 1 张合成图</h3>
        {person.sheetId || assets.find((asset) => asset.composite) ? (
          <Media
            asset={
              assets.find((asset) => asset.composite) ?? {
                id: person.sheetId ?? "sheet",
                name: "五视图合成图",
                kind: "image",
                group: "人物",
                source: "人物库",
                saved: true,
                composite: true,
              }
            }
            alt="五视图合成图"
            className="people-sheet"
          />
        ) : (
          <Empty
            title="暂无五视图合成图"
            description="前往人物管理上传照片创建。"
            action={
              <Button variant="outline" onClick={() => openLive("characters")}>
                打开人物管理
              </Button>
            }
          />
        )}
      </Panel>
      <h3>场景形象照</h3>
      <div className="scene-grid">
        {assets
          .filter((asset) => !asset.composite)
          .map((asset) => (
            <Panel key={asset.id}>
              <Media asset={asset} alt={asset.name} className="scene-image" />
              <strong>{asset.name}</strong>
              <div>
                <Button
                  variant="outline"
                  onClick={() => {
                    patchDraft({ ipId: person.id });
                    navigate("person-avatars", {
                      selectedPersonId: person.id,
                      selectedAssetId: asset.id,
                    });
                  }}
                >
                  制作口播分身
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    patchDraft({ ipId: person.id, imageId: asset.id });
                    navigate("replacement", {
                      selectedPersonId: person.id,
                      selectedAssetId: asset.id,
                    });
                  }}
                >
                  用于人物置换
                </Button>
              </div>
            </Panel>
          ))}
      </div>
    </div>
  );
}

function AvatarPanel({ person }: { person: StudioPerson }) {
  const {
    state,
    data,
    review,
    user,
    openPicker,
    navigate,
    patchDraft,
    notify,
    refresh,
    submitOralClone,
  } = useStudio();
  const [title, setTitle] = useState(`${person.name}口播分身`);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const ready = person.avatars.filter((avatar) => avatar.ready);
  const source = data.assets.find(
    (asset) =>
      asset.id === state.draft.imageId &&
      (asset.kind === "image" || asset.kind === "video"),
  );

  async function startClone() {
    if (!source || !submitOralClone || submittingRef.current) return;
    if (review) {
      notify("当前为示例审核，不会提交真实人物分身制作任务。");
      return;
    }
    if (user.role === "auditor") {
      notify("当前账号为只读权限，不能制作人物分身。");
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    try {
      await submitOralClone({
        kind: "avatar",
        identityId: person.id,
        title: title.trim() || `${person.name}口播分身`,
        sourceAssetId: source.id,
        sourceKind: source.kind === "video" ? "VIDEO" : "IMAGE",
      });
      notify("人物分身制作已提交，状态更新后即可使用。");
      refresh();
    } catch (cause: unknown) {
      notify(
        customerVisibleErrorMessage(
          cause,
          "人物分身制作提交失败，请稍后重试。",
        ),
      );
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }
  return (
    <div className="avatar-layout">
      <Panel>
        <h2>可用于数字人口播的分身</h2>
        <div className="avatar-grid">
          {ready.map((avatar) => (
            <article className="avatar-card" key={avatar.id}>
              <Media
                asset={data.assets.find((asset) => asset.id === avatar.imageId)}
                alt={avatar.name}
              />
              <h3>{avatar.name}</h3>
              <p>
                {avatar.origin} · {avatar.duration}
              </p>
              <Button
                variant="outline"
                onClick={() => {
                  patchDraft({ ipId: person.id, avatarId: avatar.id });
                  navigate(state.returnTo ?? "oral", {
                    selectedPersonId: person.id,
                  });
                }}
              >
                用于数字人口播
              </Button>
            </article>
          ))}
        </div>
        {ready.length === 0 ? (
          <Empty
            title="暂无可用分身"
            description="请从当前人物的实拍视频或场景形象照制作。"
          />
        ) : null}
      </Panel>
      <Panel>
        <h2>制作口播分身</h2>
        <p>只使用当前人物的素材，不会新建人物。完成后还需要在此确认可用。</p>
        <Button variant="outline" onClick={() => openPicker("avatar-photo")}>
          用形象照片制作
        </Button>
        <Button
          variant="outline"
          onClick={() =>
            notify(
              "人物视频上传制作接口尚未接通，当前不能把已有分身当作制作原料。",
            )
          }
        >
          上传人物视频制作
        </Button>
        <Field label="分身名称">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="例如：张工庭院讲解分身"
          />
        </Field>
        <Hint>
          {source
            ? `当前原料：${source.name}`
            : "请先选择一张当前人物的形象照片作为制作原料。"}
        </Hint>
        <Button
          variant="primary"
          disabled={!source || !submitOralClone || submitting}
          onClick={() => void startClone()}
        >
          {submitting ? "正在提交" : "开始制作"}
        </Button>
      </Panel>
    </div>
  );
}

function VoicePanel({ person }: { person: StudioPerson }) {
  const {
    state,
    data,
    review,
    user,
    openPicker,
    navigate,
    patchDraft,
    updateData,
    notify,
    refresh,
    submitOralClone,
  } = useStudio();
  const [confirmingVoiceId, setConfirmingVoiceId] = useState<string>();
  const [cloneTitle, setCloneTitle] = useState(`${person.name}克隆声音`);
  const [cloneSubmitting, setCloneSubmitting] = useState(false);
  const cloneSubmittingRef = useRef(false);
  const cloneSource = data.assets.find(
    (asset) => asset.id === state.draft.audioId && asset.kind === "audio",
  );

  function selectVoice(voiceId: string) {
    patchDraft({ ipId: person.id, voiceId });
    navigate(state.returnTo ?? "oral", {
      selectedPersonId: person.id,
      returnTo: undefined,
    });
  }

  async function confirmVoice(voiceId: string) {
    if (review) {
      updateData((data) => ({
        ...data,
        people: data.people.map((item) =>
          item.id !== person.id
            ? item
            : {
                ...item,
                voices: item.voices.map((candidate) =>
                  candidate.id === voiceId
                    ? { ...candidate, confirmed: true }
                    : candidate,
                ),
              },
        ),
      }));
      selectVoice(voiceId);
      return;
    }
    if (confirmingVoiceId) return;
    setConfirmingVoiceId(voiceId);
    try {
      await confirmOralVoice(voiceId);
      notify("声音已确认，可用于文案口播。");
      refresh();
      selectVoice(voiceId);
    } catch (error) {
      refresh();
      notify(
        error instanceof Error && error.message.trim()
          ? error.message
          : "确认声音失败，请稍后重试。",
      );
    } finally {
      setConfirmingVoiceId(undefined);
    }
  }

  async function startVoiceClone() {
    if (!cloneSource || !submitOralClone || cloneSubmittingRef.current) return;
    if (review) {
      notify("当前为示例审核，不会提交真实声音克隆任务。");
      return;
    }
    if (user.role === "auditor") {
      notify("当前账号为只读权限，不能克隆声音。");
      return;
    }
    cloneSubmittingRef.current = true;
    setCloneSubmitting(true);
    try {
      await submitOralClone({
        kind: "voice",
        identityId: person.id,
        title: cloneTitle.trim() || `${person.name}克隆声音`,
        sourceAssetId: cloneSource.id,
      });
      notify("声音克隆已提交，完成后请试听并确认使用。");
      refresh();
    } catch (cause: unknown) {
      notify(
        customerVisibleErrorMessage(cause, "声音克隆提交失败，请稍后重试。"),
      );
    } finally {
      cloneSubmittingRef.current = false;
      setCloneSubmitting(false);
    }
  }
  return (
    <div className="voice-layout">
      <Panel>
        <h2>我的声音</h2>
        {person.voices.map((voice) => (
          <article
            className={
              voice.confirmed ? "voice-card is-confirmed" : "voice-card"
            }
            key={voice.id}
          >
            <div>
              <h3>
                {voice.name} {voice.isDefault ? <small>默认</small> : null}
              </h3>
              <p>
                {voice.confirmed
                  ? "已确认，可用于文案口播"
                  : "待试听确认，暂不可选用"}
              </p>
            </div>
            <div>
              <Button
                variant="outline"
                onClick={() => {
                  if (voice.url) return;
                  notify("该声音暂无可播放样本");
                }}
              >
                试听
              </Button>
              {voice.url ? (
                <audio
                  controls
                  preload="none"
                  src={voice.url}
                  aria-label={`${voice.name}试听`}
                >
                  <track kind="captions" label="声音样本" />
                </audio>
              ) : null}
              {voice.confirmed ? (
                <Button variant="primary" onClick={() => selectVoice(voice.id)}>
                  使用此声音
                </Button>
              ) : null}
              {!voice.confirmed ? (
                <Button
                  variant="primary"
                  disabled={Boolean(confirmingVoiceId)}
                  onClick={() => void confirmVoice(voice.id)}
                >
                  {confirmingVoiceId === voice.id
                    ? "正在确认"
                    : "确认使用此声音"}
                </Button>
              ) : null}
            </div>
          </article>
        ))}
        {person.voices.length === 0 ? (
          <Empty
            title="暂无声音档案"
            description="上传本人或已授权的声音样本创建声音版本。"
          />
        ) : null}
      </Panel>
      <Panel>
        <h2>克隆声音</h2>
        <p>仅使用本人或已获授权的声音样本。</p>
        <Button variant="outline" onClick={() => openPicker("audio")}>
          从素材选择声音样本
        </Button>
        <Field label="声音名称">
          <input
            value={cloneTitle}
            onChange={(event) => setCloneTitle(event.target.value)}
            placeholder="例如：张工本人音色 V2"
          />
        </Field>
        <Button
          variant="primary"
          disabled={!cloneSource || !submitOralClone || cloneSubmitting}
          onClick={() => void startVoiceClone()}
        >
          {cloneSubmitting ? "正在提交" : "开始克隆"}
        </Button>
        <Hint>
          {cloneSource
            ? `当前原料：${cloneSource.name}。克隆完成后仍需试听确认。`
            : "请先选择本人或已获授权的声音样本。"}
        </Hint>
      </Panel>
    </div>
  );
}
