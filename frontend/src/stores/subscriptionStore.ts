import { create } from "zustand";
import { subscriptionApi, getSubscriptionError, type LoginPayload, type RegisterPayload, type ResetPasswordPayload, type SubscriptionStatus } from "@/api/subscription";

interface SubscriptionState {
  status: SubscriptionStatus | null;
  loading: boolean;
  error: string;
  fetchStatus: () => Promise<SubscriptionStatus | null>;
  refresh: () => Promise<SubscriptionStatus | null>;
  login: (payload: LoginPayload) => Promise<SubscriptionStatus>;
  logout: () => Promise<void>;
  unbindDevice: () => Promise<SubscriptionStatus>;
  register: (payload: RegisterPayload) => Promise<any>;
  sendCode: (email: string) => Promise<any>;
  sendResetCode: (email: string) => Promise<any>;
  resetPassword: (payload: ResetPasswordPayload) => Promise<any>;
  verifyCard: (cardCode: string) => Promise<SubscriptionStatus>;
}

export const useSubscriptionStore = create<SubscriptionState>((set) => ({
  status: null,
  loading: false,
  error: "",
  fetchStatus: async () => {
    set({ loading: true, error: "" });
    try {
      const status = await subscriptionApi.getStatus();
      set({ status, loading: false });
      return status;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      return null;
    }
  },
  refresh: async () => {
    set({ loading: true, error: "" });
    try {
      const status = await subscriptionApi.refresh();
      set({ status, loading: false });
      return status;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      return null;
    }
  },
  login: async (payload) => {
    set({ loading: true, error: "" });
    try {
      const status = await subscriptionApi.login(payload);
      set({ status, loading: false });
      return status;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  logout: async () => {
    set({ loading: true, error: "" });
    try {
      await subscriptionApi.logout();
      const status = await subscriptionApi.getStatus();
      set({ status, loading: false });
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  unbindDevice: async () => {
    set({ loading: true, error: "" });
    try {
      const status = await subscriptionApi.unbindDevice();
      set({ status, loading: false });
      return status;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  register: async (payload) => {
    set({ loading: true, error: "" });
    try {
      const result = await subscriptionApi.register(payload);
      set({ loading: false });
      return result;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  sendCode: async (email) => {
    set({ loading: true, error: "" });
    try {
      const result = await subscriptionApi.sendCode(email);
      set({ loading: false });
      return result;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  sendResetCode: async (email) => {
    set({ loading: true, error: "" });
    try {
      const result = await subscriptionApi.sendResetCode(email);
      set({ loading: false });
      return result;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  resetPassword: async (payload) => {
    set({ loading: true, error: "" });
    try {
      const result = await subscriptionApi.resetPassword(payload);
      set({ loading: false });
      return result;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
  verifyCard: async (cardCode) => {
    set({ loading: true, error: "" });
    try {
      const status = await subscriptionApi.verifyCard(cardCode);
      set({ status, loading: false });
      return status;
    } catch (error: any) {
      const message = getSubscriptionError(error);
      set({ error: message, loading: false });
      throw error;
    }
  },
}));
