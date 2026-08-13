import { create } from "zustand";

interface WorkflowEditorState {
  nodes: any[];
  edges: any[];
  workflowName: string;
  workflowDesc: string;
  currentWfId: string | undefined;
  taskMode: boolean;
  taskModeId: string | undefined;
  activeTaskId: string | undefined;
  isBatchTask: boolean;
  setNodes: (nodes: any[]) => void;
  setEdges: (edges: any[]) => void;
  setWorkflowName: (name: string) => void;
  setWorkflowDesc: (desc: string) => void;
  setCurrentWfId: (id: string | undefined) => void;
  setTaskMode: (mode: boolean, taskId?: string) => void;
  setActiveTaskId: (id: string | undefined) => void;
  setBatchTask: (v: boolean) => void;
  reset: () => void;
}

const initialState = {
  nodes: [] as any[],
  edges: [] as any[],
  workflowName: "",
  workflowDesc: "",
  currentWfId: undefined as string | undefined,
  taskMode: false,
  taskModeId: undefined as string | undefined,
  activeTaskId: undefined as string | undefined,
  isBatchTask: false,
};

export const useWorkflowStore = create<WorkflowEditorState>((set) => ({
  ...initialState,
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  setWorkflowName: (workflowName) => set({ workflowName }),
  setWorkflowDesc: (workflowDesc) => set({ workflowDesc }),
  setCurrentWfId: (currentWfId) => set({ currentWfId }),
  setTaskMode: (taskMode, taskModeId) => set({ taskMode, taskModeId: taskModeId }),
  setActiveTaskId: (activeTaskId) => set({ activeTaskId }),
  setBatchTask: (isBatchTask) => set({ isBatchTask }),
  reset: () => set(initialState),
}));
