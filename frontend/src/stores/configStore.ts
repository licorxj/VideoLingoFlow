import { create } from "zustand";

interface ConfigState {
  config: Record<string, any>;
  setConfig: (config: Record<string, any>) => void;
}

export const useConfigStore = create<ConfigState>((set) => ({
  config: {},
  setConfig: (config) => set({ config }),
}));
