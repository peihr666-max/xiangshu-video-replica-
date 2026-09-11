import { useState } from "react";
// 老组件样式（F-01/P0-1 修复）：这些面板的类规则原在 styles.css（仅管理/内部壳
// 加载），客户制品必须随本挂载点自带样式。
import "../legacy-panels.css";
import { AnalysisWorkspace } from "../AnalysisWorkspace";
import type { CurrentUser, GenerationBatch, Project } from "../api";
import { customerGetWallet } from "../api";
import { CharacterLibrary } from "../CharacterLibrary";
import { CustomerProfilePanel } from "../customer/CustomerProfilePanel";
import { CustomerRechargeDialog } from "../customer/CustomerRechargeDialog";
import { CustomerWalletPanel } from "../customer/CustomerWalletPanel";
import { ProjectDetailFlow } from "../ProjectDetailFlow";
import { ProjectsPage } from "../ProjectsPage";
import { TaskRecordsPanel } from "../TaskRecordsPanel";
import { WalletPanel } from "../WalletPanel";
import type { WorkspaceShellProps } from "../workspace-shell";
import type { LivePanel } from "./types";

type CustomerAccount = WorkspaceShellProps["customerAccount"];
type CustomerWallet = WorkspaceShellProps["customerWallet"];

type ProjectView = "list" | "analysis" | "detail";

export function LiveWorkspacePanel({
  panel,
  currentUser,
  customerAccount,
  customerWallet,
  project,
  characterIdentityId,
  characterInitialTab = "base",
  handoffBatch = null,
  onClose,
  onBusyChange,
  onBatchCreated,
  onHandoffConsumed,
  onProjectSelected,
  onRefresh,
}: {
  panel: LivePanel;
  currentUser: CurrentUser;
  customerAccount?: CustomerAccount;
  customerWallet?: CustomerWallet;
  project?: Project;
  characterIdentityId?: string;
  characterInitialTab?: "base" | "scenes";
  handoffBatch?: GenerationBatch | null;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
  onBatchCreated: (batch: GenerationBatch) => void;
  onHandoffConsumed: () => void;
  onProjectSelected: (project: Project) => void;
  onRefresh: () => void;
}) {
  const [projectView, setProjectView] = useState<ProjectView>(
    project && panel === "analysis" ? "analysis" : "list",
  );
  const [selectedProject, setSelectedProject] = useState<Project | null>(
    project ?? null,
  );
  const [isRechargeOpen, setIsRechargeOpen] = useState(false);
  // The wallet panel suggests an amount for the topping-up context it lives
  // in; a plain "充值条数" click clears it so the dialog starts empty.
  const [suggestedAmountYuan, setSuggestedAmountYuan] = useState<
    number | undefined
  >(undefined);
  const [walletRefreshKey, setWalletRefreshKey] = useState(0);
  const canWrite = currentUser.role !== "auditor";
  const customerSession = customerAccount ?? customerWallet;

  function openRecharge(amountYuan?: number) {
    setSuggestedAmountYuan(amountYuan);
    setIsRechargeOpen(true);
  }

  function selectProject(
    nextProject: Project,
    nextView: Exclude<ProjectView, "list">,
  ) {
    setSelectedProject(nextProject);
    setProjectView(nextView);
    onProjectSelected(nextProject);
  }

  // F-05：建批前软预检的余额读取。仅客户 lane 提供；读取失败返回 null
  // （预检跳过，服务端 402 仍会硬校验）。内部 lane 由任务页/钱包页自身呈现。
  const walletProvider = customerSession
    ? async (): Promise<number | null> => {
        try {
          const token = await customerSession.store.loadSessionToken();
          if (!token) {
            return null;
          }
          const wallet = await customerGetWallet({ kind: "session", token });
          return wallet.available_credits;
        } catch {
          return null;
        }
      }
    : undefined;
  // 余额不足引导：客户 lane 打开充值弹窗；内部 lane 无客户收款概念，
  // 不提供引导按钮（insufficient 提示本身仍会渲染）。
  const rechargeGuidance = customerSession ? () => openRecharge() : undefined;

  function finishRecharge() {
    setWalletRefreshKey((current) => current + 1);
    onRefresh();
  }

  function closeProjectView() {
    onBusyChange(false);
    setProjectView("list");
    setSelectedProject(null);
    onRefresh();
  }

  return (
    <section className="studio-live-panel" aria-label="已有功能工作区">
      <div className="studio-live-panel__bar">
        <button type="button" onClick={onClose}>
          返回新工作台
        </button>
      </div>
      {panel === "projects" || panel === "analysis" ? (
        projectView === "analysis" && selectedProject ? (
          <AnalysisWorkspace
            currentUserId={currentUser.id}
            identityId={characterIdentityId}
            onAnalysisReady={() => onRefresh()}
            onBatchCreated={onBatchCreated}
            onClose={closeProjectView}
            onRecharge={rechargeGuidance}
            onWorkspaceBusyChange={onBusyChange}
            project={selectedProject}
            readOnly={!canWrite}
            walletProvider={walletProvider}
          />
        ) : projectView === "detail" && selectedProject ? (
          <ProjectDetailFlow
            onBack={closeProjectView}
            onBatchCreated={onBatchCreated}
            onBusyChange={onBusyChange}
            onRecharge={rechargeGuidance}
            project={selectedProject}
            readOnly={!canWrite}
            walletProvider={walletProvider}
          />
        ) : (
          <ProjectsPage
            canWrite={canWrite}
            onOpenAnalysis={(nextProject) =>
              selectProject(nextProject, "analysis")
            }
            onOpenDetail={(nextProject) => selectProject(nextProject, "detail")}
          />
        )
      ) : null}
      {panel === "characters" ? (
        <CharacterLibrary
          initialIdentityId={characterIdentityId}
          initialTab={characterInitialTab}
          userId={currentUser.id}
          userRole={currentUser.role}
        />
      ) : null}
      {panel === "tasks" ? (
        <TaskRecordsPanel
          currentUserId={currentUser.id}
          handoffBatch={handoffBatch}
          onHandoffConsumed={onHandoffConsumed}
          userRole={currentUser.role}
        />
      ) : null}
      {panel === "wallet" ? (
        customerSession ? (
          <CustomerWalletPanel
            key={walletRefreshKey}
            store={customerSession.store}
            onSessionExpired={customerSession.onSessionExpired}
            onRechargeRequested={(amountYuan) => openRecharge(amountYuan)}
          />
        ) : (
          <WalletPanel currentUserId={currentUser.id} />
        )
      ) : null}
      {panel === "profile" && customerAccount ? (
        <CustomerProfilePanel
          deviceError={customerAccount.deviceError}
          devices={customerAccount.devices}
          onApprovePairing={customerAccount.onApprovePairing}
          onDismissPairing={customerAccount.onDismissPairing}
          onManualHeartbeat={customerAccount.onManualHeartbeat}
          onProfileUpdated={customerAccount.onProfileUpdated}
          onRefreshProfile={customerAccount.onRefreshProfile}
          onLogout={customerAccount.onLogout}
          onPairDevice={customerAccount.onPairDevice}
          onRecharge={(amountYuan) => openRecharge(amountYuan)}
          onRefreshDevices={customerAccount.onRefreshDevices}
          onResetActivationCode={customerAccount.onResetActivationCode}
          onSessionExpired={customerAccount.onSessionExpired}
          onUnbind={customerAccount.onUnbind}
          onUpdateProfile={customerAccount.onUpdateProfile}
          profile={customerAccount.profile}
          profileLoadError={customerAccount.profileLoadError}
          sessionRuntime={customerAccount.sessionRuntime}
          store={customerAccount.store}
          walletRefreshKey={walletRefreshKey}
        />
      ) : null}
      {panel === "profile" && !customerAccount ? (
        <div className="studio-live-panel__identity">
          <h2>{currentUser.display_name}</h2>
          <p>内部工作区身份：{currentUser.role}</p>
          <WalletPanel currentUserId={currentUser.id} />
        </div>
      ) : null}
      {customerSession ? (
        <CustomerRechargeDialog
          isOpen={isRechargeOpen}
          onClose={() => {
            setIsRechargeOpen(false);
            setSuggestedAmountYuan(undefined);
          }}
          onOrderCreated={finishRecharge}
          onPaid={finishRecharge}
          onSessionExpired={customerSession.onSessionExpired}
          store={customerSession.store}
          suggestedAmountYuan={suggestedAmountYuan}
        />
      ) : null}
    </section>
  );
}
