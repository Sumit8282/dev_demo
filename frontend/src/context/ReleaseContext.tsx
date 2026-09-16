import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { createReleaseApi, getReleaseApi, listReleasesApi, rejectL3ReleaseApi, approveL3ReleaseApi, approveRmReleaseApi, rejectRmReleaseApi, completeDeploymentApi } from '../api/releases';
import type { BackendReleaseState } from '../api/releases';
import { FALLBACK_USER } from '../config/user';
import type { ApprovalType, NewReleaseForm, Release, WorkflowActivity } from '../types/release';
import { mergeBackendState, mapBackendToRelease, createLocalWorkflowEvent } from '../utils/releaseMapper';
import {
  formatTime,
  generateBuildId,
} from '../utils/helpers';

interface ReleaseContextValue {
  releases: Release[];
  loading: boolean;
  error: string | null;
  createRelease: (form: NewReleaseForm, createdBy?: string) => Promise<Release>;
  syncReleaseFromBackend: (releaseId: string) => Promise<void>;
  updateReleaseFromBackend: (state: BackendReleaseState) => void;
  refreshReleases: () => Promise<void>;
  approveRelease: (id: string, type: ApprovalType, approverName?: string, soeId?: string) => void;
  rejectRelease: (
    id: string,
    type: ApprovalType,
    approverName?: string,
    soeId?: string,
    remarks?: string
  ) => void;
  advanceWorkflow: (id: string) => void;
  getRelease: (id: string) => Release | undefined;
}

const ReleaseContext = createContext<ReleaseContextValue | null>(null);

let activityCounter = 1000;

function createActivity(
  partial: Omit<WorkflowActivity, 'id' | 'srNo'>,
  srNo: number
): WorkflowActivity {
  activityCounter += 1;
  return {
    id: `act-${activityCounter}`,
    srNo,
    ...partial,
  };
}

function getCurrentWorkflowStep(release: Release): Release['currentStage'] {
  switch (release.backendWorkflowStatus) {
    case 'VALIDATING':
      return 'Scope Agent';
    case 'L3_APPROVAL_PENDING':
      return 'L3 Approval Pending';
    case 'L3_APPROVED':
    case 'MERGE_PENDING':
      return 'Waiting for Merge';
    case 'MERGED':
    case 'BUILD_PENDING':
    case 'BUILD_COMPLETED':
    case 'BUILD_FAILED':
      return 'Generating Build';
    case 'RM_APPROVAL_PENDING':
      return 'RM Approval Pending';
    case 'RM_APPROVED':
      return 'Deployment';
    case 'DEPLOYMENT_COMPLETED':
      return 'Completed';
    case 'RM_REJECTED':
      return 'RM Approval';
    case 'L3_REJECTED':
    case 'HALTED':
      return 'L3 Approval';
    case 'MERGE_FAILED':
      return 'Waiting for Merge';
    default:
      break;
  }

  if (release.status === 'Rejected') return release.currentStage;
  if (release.deploymentStatus === 'Deployment Successful') return 'Completed';
  if (release.deploymentStatus === 'Running') return 'Deployment';
  if (
    release.workflowActivities.some(
      (a) => a.activity === 'Deployment of Build' && a.status === 'Pending'
    )
  ) {
    return 'Deployment';
  }
  if (
    release.workflowActivities.some(
      (a) => a.activity === 'Waiting for RM Approval' && a.status === 'Pending'
    )
  ) {
    return 'RM Approval Pending';
  }
  if (
    release.workflowActivities.some(
      (a) => a.activity === 'Generating Build' && a.status === 'Running'
    )
  ) {
    return 'Generating Build';
  }
  if (
    release.workflowActivities.some(
      (a) => a.activity === 'Waiting for Merge' && a.status === 'Pending'
    )
  ) {
    return 'Waiting for Merge';
  }
  if (
    release.workflowActivities.some(
      (a) => a.activity === 'Waiting for Approval' && a.status === 'Pending'
    )
  ) {
    return 'L3 Approval Pending';
  }
  if (release.status === 'PR Request Raised') return 'L3 Approval Pending';
  if (release.status === 'Validating') return 'Scope Agent';
  return release.currentStage;
}

export function ReleaseProvider({ children }: { children: ReactNode }) {
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshReleases = useCallback(async () => {
    try {
      setError(null);
      const states = await listReleasesApi();
      setReleases(states.map((state) => mapBackendToRelease(state)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load releases');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshReleases();
  }, [refreshReleases]);

  const syncReleaseFromBackend = useCallback(async (releaseId: string) => {
    const state = await getReleaseApi(releaseId);
    setReleases((prev) =>
      prev.map((release) =>
        release.id === releaseId ? mergeBackendState(release, state) : release
      )
    );
  }, []);

  const updateReleaseFromBackend = useCallback((state: BackendReleaseState) => {
    setReleases((prev) =>
      prev.map((release) =>
        release.id === state.release_id ? mergeBackendState(release, state) : release
      )
    );
  }, []);

  const createRelease = useCallback(
    async (form: NewReleaseForm, createdBy: string = FALLBACK_USER.name): Promise<Release> => {
      setError(null);
      const response = await createReleaseApi(form, createdBy);
      const state = await getReleaseApi(response.release_id);
      const newRelease = mapBackendToRelease(state, createdBy);

      setReleases((prev) => {
        const exists = prev.some((r) => r.id === newRelease.id);
        if (exists) {
          return prev.map((r) => (r.id === newRelease.id ? newRelease : r));
        }
        return [newRelease, ...prev];
      });

      return newRelease;
    },
    []
  );

  const approveRelease = useCallback(
    (id: string, type: ApprovalType, approverName?: string, soeId?: string) => {
      const name = approverName ?? FALLBACK_USER.name;
      const soe = soeId ?? FALLBACK_USER.soeId;
      if (type === 'L3') {
        void approveL3ReleaseApi(id, name, soe)
          .then((state) => {
            updateReleaseFromBackend(state);
          })
          .catch((err) => {
            setError(err instanceof Error ? err.message : 'Failed to approve release');
          });
        return;
      }

      void approveRmReleaseApi(id, name, soe)
        .then((state) => {
          updateReleaseFromBackend(state);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : 'Failed to approve release');
        });
    },
    [updateReleaseFromBackend]
  );

  const rejectRelease = useCallback(
    (
      id: string,
      type: ApprovalType,
      approverName?: string,
      soeId?: string,
      remarks = 'Rejected by approver'
    ) => {
      const name = approverName ?? FALLBACK_USER.name;
      const soe = soeId ?? FALLBACK_USER.soeId;
      if (type === 'L3') {
        void rejectL3ReleaseApi(id, name, soe, remarks)
          .then((state) => {
            updateReleaseFromBackend(state);
          })
          .catch((err) => {
            setError(err instanceof Error ? err.message : 'Failed to reject release');
          });
        return;
      }

      void rejectRmReleaseApi(id, name, soe, remarks)
        .then((state) => {
          updateReleaseFromBackend(state);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : 'Failed to reject release');
        });
    },
    [updateReleaseFromBackend]
  );

  const advanceWorkflow = useCallback((id: string) => {
    setReleases((prev) =>
      prev.map((release) => {
        if (release.id !== id || release.status === 'Rejected') return release;

        const backendStatus = release.backendWorkflowStatus;
        if (
          backendStatus &&
          ['MERGED', 'BUILD_PENDING', 'BUILD_COMPLETED', 'BUILD_FAILED', 'RM_APPROVAL_PENDING', 'RM_REJECTED', 'DEPLOYMENT_COMPLETED'].includes(
            backendStatus
          )
        ) {
          return release;
        }

        const activities = [...release.workflowActivities];
        let updatedRelease = { ...release };

        const mergePendingIdx = activities.findIndex(
          (a) => a.activity === 'Waiting for Merge' && a.status === 'Pending'
        );
        const hasBackendMergeEvents = release.workflowEvents.some(
          (event) => event.agent === 'merge' && !event.simulated
        );
        if (mergePendingIdx >= 0 && !hasBackendMergeEvents) {
          activities[mergePendingIdx] = {
            ...activities[mergePendingIdx],
            name: 'CI/CD',
            soeId: '',
            status: 'Completed',
            time: formatTime(),
            remarks: 'Merge completed',
          };
          activities.push(
            createActivity(
              {
                name: 'CI/CD',
                soeId: '',
                team: 'CI/CD',
                activity: 'Generating Build',
                status: 'Running',
                time: formatTime(),
                remarks: '-',
              },
              activities.length + 1
            )
          );
          updatedRelease = {
            ...updatedRelease,
            currentStage: 'Generating Build',
            workflowActivities: activities,
            workflowEvents: [
              ...release.workflowEvents,
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'merge',
                phase: 'started',
                message: 'Merge agent started — merging PR into target branch',
              }),
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'merge',
                phase: 'completed',
                message: 'Merge completed successfully',
              }),
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'build',
                phase: 'started',
                message: 'Build agent started — generating release build',
              }),
            ],
          };
          return updatedRelease;
        }

        const buildRunningIdx = activities.findIndex(
          (a) => a.activity === 'Generating Build' && a.status === 'Running'
        );
        if (buildRunningIdx >= 0) {
          const buildId = generateBuildId();
          activities[buildRunningIdx] = {
            ...activities[buildRunningIdx],
            status: 'Completed',
            time: formatTime(),
            remarks: buildId,
          };
          activities.push(
            createActivity(
              {
                name: '',
                soeId: '',
                team: 'RM',
                activity: 'Waiting for RM Approval',
                status: 'Pending',
                time: '-',
                remarks: '-',
              },
              activities.length + 1
            )
          );
          updatedRelease = {
            ...updatedRelease,
            buildId,
            currentStage: 'RM Approval Pending',
            workflowActivities: activities,
            workflowEvents: [
              ...release.workflowEvents,
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'build',
                phase: 'completed',
                message: `Build generated successfully — ${buildId}`,
              }),
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'rm',
                phase: 'started',
                message: 'RM approval requested',
              }),
            ],
          };
          return updatedRelease;
        }

        const rmApproverName =
          activities.find((a) => a.activity === 'RM Approved Release')?.name?.trim() ?? '';

        const deployPendingIdx = activities.findIndex(
          (a) => a.activity === 'Deployment of Build' && a.status === 'Pending'
        );
        if (deployPendingIdx >= 0) {
          activities[deployPendingIdx] = {
            ...activities[deployPendingIdx],
            name: rmApproverName,
            status: 'Running',
            time: formatTime(),
            remarks: 'Deployment in progress',
          };
          updatedRelease = {
            ...updatedRelease,
            deploymentStatus: 'Running',
            workflowActivities: activities,
            workflowEvents: [
              ...release.workflowEvents,
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'deploy',
                phase: 'started',
                message: `Deployment started to ${release.environment}`,
              }),
            ],
          };
          return updatedRelease;
        }

        const deployRunningIdx = activities.findIndex(
          (a) => a.activity === 'Deployment of Build' && a.status === 'Running'
        );
        if (deployRunningIdx >= 0) {
          activities[deployRunningIdx] = {
            ...activities[deployRunningIdx],
            name: rmApproverName || activities[deployRunningIdx].name,
            status: 'Completed',
            time: formatTime(),
            remarks: 'Deployment completed',
          };
          activities.push(
            createActivity(
              {
                name: 'Agent',
                soeId: '',
                team: 'AI',
                activity: `Deployment Completed on ${release.environment}`,
                status: 'Completed',
                time: formatTime(),
                remarks: 'Deployment Successful',
              },
              activities.length + 1
            )
          );
          updatedRelease = {
            ...updatedRelease,
            status: 'Completed',
            currentStage: 'Completed',
            deploymentStatus: 'Deployment Successful',
            workflowActivities: activities,
            workflowEvents: [
              ...release.workflowEvents,
              createLocalWorkflowEvent({
                timestamp: new Date().toISOString(),
                agent: 'deploy',
                phase: 'completed',
                message: `Deployment completed successfully on ${release.environment}`,
              }),
            ],
          };
          if (release.backendWorkflowStatus === 'RM_APPROVED') {
            void completeDeploymentApi(release.id)
              .then((state) => {
                updateReleaseFromBackend(state);
              })
              .catch((err) => {
                setError(err instanceof Error ? err.message : 'Failed to record deployment completion');
              });
          }
          return updatedRelease;
        }

        return release;
      })
    );
  }, [updateReleaseFromBackend]);

  const getRelease = useCallback(
    (id: string) => releases.find((r) => r.id === id),
    [releases]
  );

  const value = useMemo(
    () => ({
      releases: releases.map((r) => ({
        ...r,
        currentStage: getCurrentWorkflowStep(r),
      })),
      loading,
      error,
      createRelease,
      syncReleaseFromBackend,
      updateReleaseFromBackend,
      refreshReleases,
      approveRelease,
      rejectRelease,
      advanceWorkflow,
      getRelease,
    }),
    [
      releases,
      loading,
      error,
      createRelease,
      syncReleaseFromBackend,
      updateReleaseFromBackend,
      refreshReleases,
      approveRelease,
      rejectRelease,
      advanceWorkflow,
      getRelease,
    ]
  );

  return (
    <ReleaseContext.Provider value={value}>{children}</ReleaseContext.Provider>
  );
}

export function useReleases() {
  const context = useContext(ReleaseContext);
  if (!context) {
    throw new Error('useReleases must be used within ReleaseProvider');
  }
  return context;
}
