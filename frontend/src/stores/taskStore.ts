import { create } from "zustand";

interface TaskState {
  tasks: any[];
  currentTask: any | null;
  setTasks: (tasks: any[]) => void;
  setCurrentTask: (task: any | null) => void;
  updateTaskProgress: (taskId: string, stepId: string, progress: number, message: string) => void;
}

export const useTaskStore = create<TaskState>((set) => ({
  tasks: [],
  currentTask: null,
  setTasks: (tasks) => set({ tasks }),
  setCurrentTask: (task) => set({ currentTask: task }),
  updateTaskProgress: (taskId, stepId, progress, message) =>
    set((state) => {
      if (state.currentTask?.id === taskId) {
        const steps = { ...state.currentTask.steps };
        if (steps[stepId]) {
          steps[stepId] = { ...steps[stepId], progress, message, status: progress >= 100 ? "completed" : "running" };
        }
        return { currentTask: { ...state.currentTask, steps } };
      }
      return state;
    }),
}));
